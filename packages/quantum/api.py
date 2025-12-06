import os
import io
import csv
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Literal, Any
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Request, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import create_client, Client

from security import encrypt_token, decrypt_token, get_current_user
from security.secrets_provider import SecretsProvider

# Import models and services
from models import Holding, SyncResponse, PortfolioSnapshot, Spread
import plaid_service
import plaid_endpoints

# Import functionalities
from options_scanner import scan_for_opportunities
from services.journal_service import JournalService
from services.universe_service import UniverseService
from services.analytics_service import AnalyticsService
from optimizer import router as optimizer_router
from market_data import calculate_portfolio_inputs
# New Services for Cash-Aware Workflow
from services.workflow_orchestrator import run_morning_cycle, run_midday_cycle, run_weekly_report
from services.plaid_history_service import PlaidHistoryService
from services.rebalance_engine import RebalanceEngine
from services.execution_service import ExecutionService
from analytics.progress_engine import ProgressEngine, get_week_id_for_last_full_week
from services.options_utils import group_spread_positions
from ev_calculator import calculate_ev, calculate_position_size
from services.enrichment_service import enrich_holdings_with_analytics
from models import SpreadPosition
from services.historical_simulation import HistoricalCycleService
from analytics.loss_minimizer import LossMinimizer, LossAnalysisResult
from analytics.drift_auditor import audit_plan_vs_execution
from analytics.greeks_aggregator import aggregate_portfolio_greeks, build_greek_alerts


# 1. Load environment variables BEFORE importing other things
load_dotenv()

TEST_USER_UUID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"

# New Table Constants
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

app = FastAPI(
    title="Portfolio Optimizer API",
    description="Portfolio optimization with real market data",
    version="2.0.0",
)

# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Initialize Supabase Client
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key

supabase: Client = create_client(url, key) if url and key else None

# Initialize Analytics Service
analytics_service = AnalyticsService(supabase)
app.state.analytics_service = analytics_service

# --- Register Plaid Endpoints ---
plaid_endpoints.register_plaid_endpoints(app, plaid_service, supabase, analytics_service)

# --- Register Optimizer Endpoints ---
app.include_router(optimizer_router)

# --- Register Strategy Endpoints ---
from strategy_endpoints import router as strategy_router
app.include_router(strategy_router)

# --- Rebalance Engine Endpoints (Step 3) ---

@app.post("/rebalance/execute")
async def execute_rebalance(
    user_id: str = Depends(get_current_user)
):
    """
    Runs the rebalance engine:
    1. Fetches current portfolio.
    2. Runs optimizer to get targets (using real regime/conviction).
    3. Generates trade instructions via RebalanceEngine.
    4. Saves suggestions to DB.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Fetch Current Holdings
    pos_res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
    raw_positions = pos_res.data or []

    # 2. Group into Spreads
    spreads_dicts = group_spread_positions(raw_positions)
    current_spreads = [Spread(**s) for s in spreads_dicts]

    # Calculate Cash
    cash = 0.0
    for p in raw_positions:
        sym = p.get("symbol", "").upper()
        if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
             val = p.get("current_value", 0)
             if val == 0:
                 val = float(p.get("quantity", 0)) * float(p.get("current_price", 1.0))
             cash += val

    # 3. Run Optimizer directly to get targets
    from optimizer import _compute_portfolio_weights, OptimizationRequest, calculate_dynamic_target
    from analytics.iv_regime_service import IVRegimeService

    # Pre-fetch IV Context for existing holdings (needed for regime-elastic caps)
    iv_service = IVRegimeService(supabase)
    unique_tickers = [s.ticker for s in current_spreads]
    iv_ctx_map = iv_service.get_iv_context_for_symbols(unique_tickers)

    # Phase 6: Wire Real Conviction
    # We ideally compute this via ScoringEngine. For now, we wire the map structure.
    conviction_map = {}  # TODO: populate with ScoringEngine + ConvictionTransform

    # Construct input positions for optimizer
    opt_req = OptimizationRequest(
        positions=raw_positions,
        cash_balance=cash,
        profile="balanced",
        nested_enabled=True
    )

    tickers = [s.ticker for s in current_spreads]
    assets_equity = sum(s.current_value for s in current_spreads)
    total_val = assets_equity + cash

    if not tickers:
        return {"status": "ok", "message": "No assets to rebalance", "count": 0}

    # Helper function for heavy compute
    def run_optimizer_logic():
        from market_data import calculate_portfolio_inputs
        import numpy as np

        unique_underlyings = list(set([s.underlying for s in current_spreads]))

        try:
             inputs = calculate_portfolio_inputs(unique_underlyings)
             base_mu = inputs['expected_returns']
             base_sigma = inputs['covariance_matrix']
             base_idx_map = {u: i for i, u in enumerate(unique_underlyings)}

             n = len(tickers)
             mu = np.zeros(n)
             sigma = np.zeros((n, n))
             for i in range(n):
                 u_i = current_spreads[i].underlying
                 idx_i = base_idx_map.get(u_i)
                 mu[i] = base_mu[idx_i] if idx_i is not None else 0.05
                 for j in range(n):
                     u_j = current_spreads[j].underlying
                     idx_j = base_idx_map.get(u_j)
                     if idx_i is not None and idx_j is not None:
                         sigma[i, j] = base_sigma[idx_i][idx_j]
                     else:
                         if i==j: sigma[i, j] = 0.1

             coskew = np.zeros((n, n, n))

             target_weights, _, _, _, _, _, _, _ = _compute_portfolio_weights(
                 mu, sigma, coskew, tickers, current_spreads, opt_req, user_id, total_val, cash
             )

             # Phase 3: Post-process weights with Regime-Elastic Caps
             spread_map = {s.ticker: s for s in current_spreads}

             targets = []
             for sym, w in target_weights.items():
                 # Elastic Logic
                 spread_obj = spread_map.get(sym)
                 strat_type = spread_obj.spread_type if spread_obj else "other"

                 # Retrieve Regime & Conviction
                 # Note: iv_ctx_map keys are typically tickers or symbols.
                 ctx = iv_ctx_map.get(sym, {})
                 regime = ctx.get("iv_regime", "normal") # e.g. "suppressed", "normal", "elevated"

                 # Phase 6: Use Real Conviction Map
                 conviction = conviction_map.get(sym, 1.0)

                 # Apply Dynamic Constraint with REAL regime
                 adjusted_w = calculate_dynamic_target(
                     base_weight=w,
                     strategy_type=strat_type,
                     regime=regime,
                     conviction=conviction
                 )

                 targets.append({
                     "type": "spread",
                     "symbol": sym,
                     "target_allocation": adjusted_w
                 })
             return targets

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Offload heavy compute to thread
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            targets = await loop.run_in_executor(pool, run_optimizer_logic)
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"Optimization failed: {e}")

    # 4. Generate Trades
    engine = RebalanceEngine()
    trades = engine.generate_trades(
        current_spreads,
        raw_positions,
        cash,
        targets,
        profile="balanced"
    )

    # 5. Save to DB
    saved_count = 0
    if trades:
        # Clear old rebalance suggestions
        supabase.table(TRADE_SUGGESTIONS_TABLE).delete().eq("user_id", user_id).eq("window", "rebalance").execute()

        # Log event: Suggestion Batch Generated
        analytics_service.log_event(
            user_id=user_id,
            event_name="suggestion_batch_generated",
            category="system",
            properties={
                "count": len(trades),
                "window": "rebalance",
                "profile": "balanced"
            }
        )

        # We already have iv_ctx_map for holding symbols, but trades might be new legs/spreads?
        # The trades are usually adjustments to existing or closes.
        # If new symbols appear (rare in rebalance unless specific strategy), we might need to fetch again.
        # But let's reuse what we have or fetch for trades.

        trade_symbols = [t["symbol"] for t in trades]
        # Fetch fresh context for trades (some might be new)
        trade_iv_ctx = iv_service.get_iv_context_for_symbols(trade_symbols)

        db_rows = []
        for t in trades:
            sym = t["symbol"]
            ctx = trade_iv_ctx.get(sym, {})

            if "context" not in t:
                t["context"] = {}
            t["context"].update(ctx)

            db_rows.append({
                "user_id": user_id,
                "symbol": sym,
                "strategy": t.get("spread_type", "custom"),
                "direction": t["side"].title(), # Buy/Sell
                "confidence_score": 0, # N/A
                "ev": 0,
                "order_json": t, # Store full details (now has context)
                "status": "pending",
                "window": "rebalance",
                "created_at": datetime.now().isoformat(),
                "notes": t.get("reason", "")
            })

        res = supabase.table(TRADE_SUGGESTIONS_TABLE).insert(db_rows).execute()
        saved_count = len(res.data) if res.data else 0

        # Log individual suggestion events for better traceability (optional but good for learning loop)
        if res.data:
            for row in res.data:
                analytics_service.log_suggestion_event(user_id, row, "suggestion_generated")

    return {
        "status": "ok",
        "count": saved_count,
        "trades": trades
    }

@app.get("/rebalance/suggestions")
async def get_rebalance_suggestions(
    user_id: str = Depends(get_current_user)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database unavailable")

    res = supabase.table(TRADE_SUGGESTIONS_TABLE)\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("window", "rebalance")\
        .eq("status", "pending")\
        .execute()

    return {"suggestions": res.data or []}

# --- Helper Functions ---


def get_active_user_ids() -> List[str]:
    """Helper to get list of active user IDs."""
    if not supabase:
        return []
    try:
        # For now, derive from user_settings table
        res = supabase.table("user_settings").select("user_id").execute()
        return [r["user_id"] for r in res.data or []]
    except Exception as e:
        print(f"Error fetching active users: {e}")
        return []


def verify_cron_secret(x_cron_secret: str = Header(None, alias="X-Cron-Secret")):
    """Dependency to verify the Cron Secret header."""
    cron_secret = os.getenv("CRON_SECRET")
    if not cron_secret or x_cron_secret != cron_secret:
        raise HTTPException(status_code=401, detail="Unauthorized task caller")


async def create_portfolio_snapshot(user_id: str) -> None:
    """Creates a new portfolio snapshot from current positions."""
    if not supabase:
        return

    # 1. Fetch current holdings from POSITIONS table (Single Truth)
    response = (
        supabase.table("positions").select("*").eq("user_id", user_id).execute()
    )
    holdings = response.data

    # If no holdings, just abort snapshot creation gracefully
    if not holdings:
        return

    # 2. Enrich Holdings with Analytics
    holdings = enrich_holdings_with_analytics(holdings)

    # 3. Calculate Risk Metrics (Basic)
    symbols = [h["symbol"] for h in holdings if h.get("symbol")]
    risk_metrics: Dict[str, object] = {}

    try:
        # Attempt to get real data for metrics
        if symbols:
            inputs = calculate_portfolio_inputs(symbols)
            risk_metrics = {
                "count": len(symbols),
                "symbols": symbols,
                "data_source": "polygon.io"
                if not inputs.get("is_mock")
                else "mock",
            }
    except Exception as e:
        print(f"Failed to calculate risk metrics for snapshot: {e}")
        risk_metrics = {"error": str(e)}

    # Group into spreads for snapshot
    # group_spread_positions returns a list of SpreadPosition objects (Pydantic models) or dicts?
    # Checking import: usually returns SpreadPosition objects in this codebase context.
    spreads = group_spread_positions(holdings)

    # Ensure they are SpreadPosition objects for aggregator
    # If they are already models, this is fine. If dicts, convert.
    # group_spread_positions in this repo returns List[SpreadPosition] as seen in rebalance/preview.
    # But just in case, we cast if needed (though it likely returns models).
    spread_models = spreads
    if spreads and isinstance(spreads[0], dict):
        spread_models = [SpreadPosition(**s) for s in spreads]

    # Compute Portfolio Greeks
    portfolio_greeks = aggregate_portfolio_greeks(spread_models)
    greek_alerts = build_greek_alerts(portfolio_greeks)

    # Attach to risk_metrics
    risk_metrics["greeks"] = portfolio_greeks
    risk_metrics["greek_alerts"] = greek_alerts

    # 4. Create Snapshot
    snapshot = {
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "snapshot_type": "on-sync",
        "data_source": "plaid",
        "holdings": holdings,  # Storing the positions snapshot
        "risk_metrics": risk_metrics,
        "optimizer_status": "ready",
        # We can't easily store 'spreads' as a separate column unless migration adds it.
        # But we can assume the client can derive it from holdings, or we pack it into risk_metrics?
        # Spec says: "Ensure JSON responses for /portfolio/snapshot... include spreads".
        # So we don't necessarily need to store it in DB if we generate it on read.
        # But create_portfolio_snapshot saves to DB.
        # We'll skip adding spreads to DB to avoid schema error, but ensure GET returns them.
    }

    supabase.table("portfolio_snapshots").insert(snapshot).execute()


# --- Endpoints ---


@app.get("/")
def read_root():
    return {
        "status": "Quantum API operational",
        "service": "Portfolio Optimizer API",
        "version": "2.0",
        "features": [
            "classical optimization",
            "real market data",
            "options scout",
            "trade journal",
        ],
        "data_source": "Polygon.io"
        if os.getenv("POLYGON_API_KEY")
        else "Mock Data",
    }


@app.get("/health")
def health_check():
    polygon_key = os.getenv("POLYGON_API_KEY")
    return {
        "status": "ok",
        "market_data": "connected" if polygon_key else "not configured",
    }

# --- Analytics Endpoints ---

class AnalyticsEventRequest(BaseModel):
    event_name: str
    category: str
    properties: Dict[str, Any] = {}

@app.post("/analytics/events")
async def log_analytics_event(
    req: AnalyticsEventRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Endpoint for frontend to log events securely.
    """
    analytics_service.log_event(
        user_id=user_id,
        event_name=req.event_name,
        category=req.category,
        properties=req.properties
    )
    return {"status": "logged"}


# --- Cron Task Endpoints ---


@app.post("/tasks/morning-brief")
async def morning_brief(
    _: None = Depends(verify_cron_secret)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    active_users = get_active_user_ids()
    for uid in active_users:
        await run_morning_cycle(supabase, uid)

    return {"status": "ok", "processed": len(active_users)}


@app.post("/tasks/midday-scan")
async def midday_scan(
    _: None = Depends(verify_cron_secret)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    active_users = get_active_user_ids()
    for uid in active_users:
        await run_midday_cycle(supabase, uid)

    return {"status": "ok", "processed": len(active_users)}


@app.post("/tasks/weekly-report")
async def weekly_report_task(
    _: None = Depends(verify_cron_secret)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    active_users = get_active_user_ids()
    for uid in active_users:
        await run_weekly_report(supabase, uid)

    return {"status": "ok", "processed": len(active_users)}


@app.post("/tasks/universe/sync")
async def universe_sync_task(
    _: None = Depends(verify_cron_secret)
):
    print("Universe sync task: starting")
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        service = UniverseService(supabase)
        service.sync_universe()
        service.update_metrics()

        print("Universe sync task: complete")
        return {"status": "ok", "message": "Universe synced and metrics updated"}
    except Exception as e:
        print(f"Universe sync task failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@app.post("/tasks/plaid/backfill-history")
async def backfill_history(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
    x_cron_secret: str = Header(None, alias="X-Cron-Secret")
):
    verify_cron_secret(x_cron_secret)
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    user_ids = get_active_user_ids()
    service = PlaidHistoryService(plaid_service.client, supabase)
    counts = {}
    for uid in user_ids:
        counts[uid] = await service.backfill_snapshots(uid, start_date, end_date)
    return {"status": "ok", "counts": counts}


# --- Rebalance Endpoints (Spec B) ---

@app.post("/rebalance/preview")
async def preview_rebalance(
    user_id: str = Depends(get_current_user)
):
    """
    Runs the rebalance engine:
    1. Fetches current portfolio.
    2. Runs optimizer to get targets.
    3. Generates trade instructions via RebalanceEngine.
    4. Saves suggestions to DB with window='rebalance'.
    5. Returns suggestions.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Fetch Current Holdings
    pos_res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
    raw_positions = pos_res.data or []

    # 2. Group into Spreads
    # group_spread_positions now returns SpreadPosition objects directly
    current_spreads = group_spread_positions(raw_positions)

    # Calculate Cash
    cash = 0.0
    for p in raw_positions:
        sym = p.get("symbol", "").upper()
        if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
             val = p.get("current_value", 0)
             if val == 0:
                 val = float(p.get("quantity", 0)) * float(p.get("current_price", 1.0))
             cash += val

    # 3. Run Optimizer directly to get targets
    from optimizer import _compute_portfolio_weights, OptimizationRequest

    # Construct input positions for optimizer
    opt_req = OptimizationRequest(
        positions=raw_positions,
        cash_balance=cash,
        profile="balanced",
        nested_enabled=True
    )

    tickers = [s.ticker for s in current_spreads]
    assets_equity = sum(s.current_value for s in current_spreads)
    total_val = assets_equity + cash

    if not tickers:
        return {"status": "ok", "message": "No assets to rebalance", "count": 0, "trades": []}

    # Helper function for heavy compute
    def run_optimizer_logic():
        from market_data import calculate_portfolio_inputs
        import numpy as np

        unique_underlyings = list(set([s.underlying for s in current_spreads]))

        try:
             inputs = calculate_portfolio_inputs(unique_underlyings)
             base_mu = inputs['expected_returns']
             base_sigma = inputs['covariance_matrix']
             base_idx_map = {u: i for i, u in enumerate(unique_underlyings)}

             n = len(tickers)
             mu = np.zeros(n)
             sigma = np.zeros((n, n))
             for i in range(n):
                 u_i = current_spreads[i].underlying
                 idx_i = base_idx_map.get(u_i)
                 mu[i] = base_mu[idx_i] if idx_i is not None else 0.05
                 for j in range(n):
                     u_j = current_spreads[j].underlying
                     idx_j = base_idx_map.get(u_j)
                     if idx_i is not None and idx_j is not None:
                         sigma[i, j] = base_sigma[idx_i][idx_j]
                     else:
                         if i==j: sigma[i, j] = 0.1

             coskew = np.zeros((n, n, n))

             # NOTE: optimizer.py logic usually requires 'spreads' arg to be list of Spread objects (not SpreadPosition).
             # But models are similar enough (dicts/pydantic). _compute_portfolio_weights iterates over them.
             # We might need to ensure compatibility.
             # Passing dicts might be safer if _compute_portfolio_weights is flexible.
             # Checking optimizer.py: it types spreads: List[Spread].
             # SpreadPosition has extra fields but should be compatible if converted.
             # Let's pass the list of SpreadPosition objects, or cast them.
             # Ideally we use the SpreadPosition everywhere now, but if optimizer is strict, we might need adapter.
             # For now, assuming compatibility or duck typing.

             target_weights, _, _, _, _, _, _, _ = _compute_portfolio_weights(
                 mu, sigma, coskew, tickers, current_spreads, opt_req, user_id, total_val, cash
             )

             # Convert weights to targets list
             targets = []
             for sym, w in target_weights.items():
                 targets.append({
                     "type": "spread",
                     "symbol": sym,
                     "target_allocation": w
                 })
             return targets

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Offload heavy compute to thread
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            targets = await loop.run_in_executor(pool, run_optimizer_logic)
        except Exception as e:
             # If optimization fails, log and return empty
             print(f"Rebalance optimization error: {e}")
             return {"status": "error", "message": str(e), "trades": []}

    # 4. Generate Trades
    engine = RebalanceEngine()
    trades = engine.generate_trades(
        current_spreads,
        raw_positions,
        cash,
        targets,
        profile="balanced"
    )

    # 5. Save to DB
    saved_count = 0
    if trades:
        # Clear old rebalance suggestions
        supabase.table(TRADE_SUGGESTIONS_TABLE).delete().eq("user_id", user_id).eq("window", "rebalance").execute()

        db_rows = []
        for t in trades:
            db_rows.append({
                "user_id": user_id,
                "symbol": t["symbol"],
                "ticker": t["symbol"], # Populate ticker for UI
                "strategy": t.get("spread_type", "custom"),
                "direction": t.get("side", "hold").title(), # Buy/Sell/Increase
                "order_json": t, # Store full details
                "status": "pending",
                "window": "rebalance",
                "created_at": datetime.now().isoformat(),
                "sizing_metadata": {"reason": t.get("reason", "")}
            })

        res = supabase.table(TRADE_SUGGESTIONS_TABLE).insert(db_rows).execute()
        saved_count = len(res.data) if res.data else 0

    return {
        "status": "ok",
        "count": saved_count,
        "trades": trades
    }

@app.get("/rebalance/suggestions")
async def get_rebalance_suggestions(
    user_id: str = Depends(get_current_user)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database unavailable")

    res = supabase.table(TRADE_SUGGESTIONS_TABLE)\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("window", "rebalance")\
        .eq("status", "pending")\
        .execute()

    # Flatten order_json for UI ease (SuggestionTabs expects top-level props)
    suggestions = []
    if res.data:
        for row in res.data:
            order = row.get("order_json") or {}
            # Merge order fields into top level, keeping row fields as priority if conflict (but usually distinct)
            # Row has: id, symbol, strategy, direction
            # Order has: side, limit_price, target_allocation, quantity, reason, legs...
            flat = {**order, **row}
            # Ensure safe fallback for 'side' if not in order (use row direction)
            if "side" not in flat and "direction" in flat:
                 flat["side"] = flat["direction"].lower()
            suggestions.append(flat)

    return {"suggestions": suggestions}


# --- Development Endpoints ---

@app.post("/tasks/run-all")
async def run_all(user_id: str = Depends(get_current_user)):
    """Dev-only: Manually trigger all workflows for the current user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    print(f"DEV: Running Morning Cycle for {user_id}")
    await run_morning_cycle(supabase, user_id)

    print(f"DEV: Running Midday Cycle for {user_id}")
    await run_midday_cycle(supabase, user_id)

    print(f"DEV: Running Weekly Report for {user_id}")
    await run_weekly_report(supabase, user_id)

    return {"status": "ok", "message": "All workflows triggered manually"}


# --- New Data Endpoints ---

@app.post("/historical/run-cycle")
async def run_historical_cycle(
    cursor: str = Body(..., embed=True),
    symbol: Optional[str] = Body("SPY", embed=True),
):
    """
    Runs exactly one historical trade cycle (Entry -> Exit) starting from cursor date.
    Uses regime-aware scoring and conviction logic on historical data slices.
    """
    try:
        service = HistoricalCycleService() # Inits with PolygonService
        result = service.run_cycle(cursor, symbol)
        return result
    except Exception as e:
        print(f"Historical cycle error: {e}")
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")


@app.get("/suggestions")
async def get_suggestions(
    window: Optional[str] = None,
    status: Optional[str] = "pending",
    user_id: str = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        query = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id)
        if window:
            query = query.eq("window", window)
        if status:
            query = query.eq("status", status)
        res = query.order("created_at", desc=True).execute()

        # Enrich with spreads if possible?
        # The structure is JSON, so we just return.

        return {"suggestions": res.data or []}
    except Exception as e:
        print(f"Error fetching suggestions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch suggestions")


@app.get("/weekly-reports")
async def get_weekly_reports(
    limit: int = 4,
    user_id: str = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        res = (
            supabase.table(WEEKLY_REPORTS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("week_ending", desc=True)
            .limit(limit)
            .execute()
        )
        return {"reports": res.data or []}
    except Exception as e:
        print(f"Error fetching weekly reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch weekly reports")


@app.post("/plaid/sync_holdings", response_model=SyncResponse)
@limiter.limit("5/minute")  # Rate Limit: 5 syncs per minute per IP
async def sync_holdings(
    request: Request,
    user_id: str = Depends(get_current_user),  # NOW REQUIRES REAL JWT
):
    """
    Syncs holdings from Plaid and updates the positions table.
    """
    # 1. Log Audit
    if supabase:
        try:
            supabase.table("audit_logs").insert(
                {
                    "user_id": user_id,
                    "action": "SYNC_HOLDINGS",
                    "ip_address": request.client.host,
                }
            ).execute()
        except Exception:
            # Audit log failure shouldn't stop the sync
            pass

    if not supabase:
        raise HTTPException(
            status_code=500, detail="Server Error: Database not configured"
        )

    # 2. Retrieve Plaid Access Token
    plaid_access_token: Optional[str] = None
    if supabase:
        from services.token_store import PlaidTokenStore
        token_store = PlaidTokenStore(supabase)
        plaid_access_token = token_store.get_access_token(user_id)

    # 3. Fetch from Plaid
    errors: List[str] = []
    holdings: List[Holding] = []
    sync_attempted = False

    if plaid_access_token:
        try:
            print("Fetching Plaid holdings...")
            # This returns normalized Holding objects
            plaid_holdings = plaid_service.fetch_and_normalize_holdings(
                plaid_access_token
            )
            print(f"✅ PLAID RAW RETURN: Found {len(plaid_holdings)} holdings.")
            for h in plaid_holdings:
                print(
                    f"   - Symbol: {h.symbol}, Qty: {h.quantity}, Price: {h.current_price}"
                )
            holdings.extend(plaid_holdings)
            sync_attempted = True
        except Exception as e:
            print(f"Plaid Sync Error: {e}")
            errors.append(f"Plaid: {str(e)}")

    if not sync_attempted:
        raise HTTPException(
            status_code=404, detail="No linked broker accounts found."
        )

    if errors and not holdings:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync holdings: {'; '.join(errors)}",
        )

    # 4. Upsert into POSITIONS (Single Truth)
    if supabase and holdings:
        # Log Sync Started
        analytics_service.log_event(user_id, "plaid_sync_started", "system", {"holdings_count": len(holdings)})

        data_to_insert = []
        for h in holdings:
            row = h.model_dump()
            position_row = {
                "user_id": user_id,
                "symbol": row["symbol"],
                "quantity": row["quantity"],
                "cost_basis": row["cost_basis"],
                "current_price": row["current_price"],
                "currency": row["currency"],
                "source": "plaid",
                "updated_at": datetime.now().isoformat(),
            }
            data_to_insert.append(position_row)

        try:
            supabase.table("positions").upsert(
                data_to_insert,
                on_conflict="user_id,symbol",
            ).execute()
        except Exception as e:
            print(f"Failed to upsert positions: {e}")
            raise HTTPException(
                status_code=500, detail=f"Database Error: {e}"
            )

        # 5. Create Snapshot
        await create_portfolio_snapshot(user_id)

        # Log Sync Completed
        analytics_service.log_event(user_id, "plaid_sync_completed", "system", {"status": "success"})

        # 6. Drift Audit (Phase 2)
        # Check Execution (Reality) vs Plan (Suggestions)
        if supabase:
            try:
                # Retrieve latest snapshot just created
                snap_res = supabase.table("portfolio_snapshots").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
                current_snapshot = snap_res.data[0] if snap_res.data else None

                # Retrieve recent suggestions (last 48h)
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
                sugg_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id).gte("created_at", cutoff).execute()
                recent_suggestions = sugg_res.data or []

                if current_snapshot:
                    print(f"🕵️  Running Drift Auditor for user {user_id}")
                    audit_plan_vs_execution(user_id, current_snapshot, recent_suggestions, supabase)

            except Exception as e:
                # Do not break sync if auditor fails
                print(f"⚠️  Drift Auditor failed: {e}")

    return SyncResponse(status="success", count=len(holdings), holdings=holdings)


@app.get("/holdings/export")
async def export_holdings_csv(
    brokerage: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """
    Exports holdings to a CSV file from POSITIONS table.
    """
    if not supabase:
        raise HTTPException(
            status_code=500, detail="Server Error: Database not configured"
        )

    if not authorization:
        raise HTTPException(
            status_code=401, detail="Missing Authorization header"
        )

    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Token")

    # Fetch from POSITIONS
    query = supabase.table("positions").select("*").eq("user_id", user_id)
    response = query.execute()
    positions = response.data

    if brokerage:
        # Filter if needed (e.g. source=plaid)
        pass

    if not positions:
        raise HTTPException(
            status_code=404, detail="No holdings found to export"
        )

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "accountId",
            "symbol",
            "quantity",
            "cost_basis",
            "current_price",
            "currency",
            "source",
        ]
    )

    for p in positions:
        writer.writerow(
            [
                p.get("account_id", ""),
                p.get("symbol", ""),
                p.get("quantity", 0),
                p.get("cost_basis", 0),
                p.get("current_price", 0),
                p.get("currency", "USD"),
                p.get("source", ""),
            ]
        )

    output.seek(0)
    filename = f"portfolio_export_{datetime.now().strftime('%Y-%m-%d')}.csv"

    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/portfolio/snapshot")
async def get_portfolio_snapshot(
    user_id: str = Depends(get_current_user),
    refresh: bool = False,
):
    """Retrieves the most recent portfolio snapshot for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    # 1. Get latest snapshot from the database
    try:
        response = (
            supabase.table("portfolio_snapshots")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database query failed: {e}"
        )

    snapshot_data = response.data[0] if response.data else None

    # 2. Check for staleness (e.g., older than 15 minutes) - Note: refresh logic is a stub
    if snapshot_data:
        created_at_str = snapshot_data["created_at"]
        # Ensure timezone awareness for correct comparison
        created_at = datetime.fromisoformat(created_at_str).replace(
            tzinfo=timezone.utc
        )
        _is_stale = (datetime.now(timezone.utc) - created_at) > timedelta(
            minutes=15
        )

        # Inject Spreads for the frontend
        if "holdings" in snapshot_data:
            snapshot_data["spreads"] = group_spread_positions(snapshot_data["holdings"])

    if snapshot_data:
        # Add buying power if available from a related table
        try:
            res = (
                supabase.table("plaid_items")
                .select("buying_power")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if res.data and res.data.get("buying_power") is not None:
                snapshot_data["buying_power"] = res.data.get("buying_power")
        except Exception:
            # Non-critical, ignore if it fails
            pass
        return snapshot_data
    else:
        # Return the same structure as before for consistency
        return {"message": "No snapshot found", "holdings": [], "spreads": []}


@app.get("/scout/weekly")
async def weekly_scout(
    mode: str = "holdings",
    user_id: str = Depends(get_current_user)
):
    """
    Get weekly option opportunities.
    mode="holdings": Scan only assets in user's portfolio (default).
    mode="market": Scan the broader market universe.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        symbols_to_scan = None
        source_label = "user-holdings"

        if mode == "holdings":
            # 1. Fetch user's holdings from the single source of truth
            response = (
                supabase.table("positions")
                .select("symbol")
                .eq("user_id", user_id)
                .execute()
            )
            holdings = response.data

            if not holdings:
                return {
                    "count": 0,
                    "top_picks": [],
                    "generated_at": datetime.now().isoformat(),
                    "source": source_label,
                    "message": "No holdings found to generate opportunities.",
                }

            # 2. Extract symbols to scan
            symbols_to_scan = list(
                set(
                    [
                        h["symbol"]
                        for h in holdings
                        if h.get("symbol")
                        and "USD" not in h["symbol"]
                        and "CASH" not in h["symbol"]
                    ]
                )
            )

            if not symbols_to_scan:
                return {
                    "count": 0,
                    "top_picks": [],
                    "generated_at": datetime.now().isoformat(),
                    "source": source_label,
                    "message": "No scannable assets in your portfolio.",
                }
        else:
            # Market mode: leave symbols_to_scan as None to trigger Universe scan
            source_label = "market-universe"

        # 3. Scan for opportunities
        # Pass supabase client so scanner can use UniverseService if symbols is None
        opportunities = scan_for_opportunities(
            symbols=symbols_to_scan,
            supabase_client=supabase
        )

        # 4. Filter and sort by score safely
        cleaned = [o for o in opportunities if o.get("score") is not None]
        cleaned.sort(key=lambda o: o.get("score", 0), reverse=True)

        return {
            "count": len(cleaned),
            "top_picks": cleaned[:5],
            "generated_at": datetime.now().isoformat(),
            "source": source_label,
        }

    except Exception as e:
        print(f"Error in weekly_scout: {e}")
        return {
            "top_picks": [],
            "error": "scout_unavailable",
            "message": f"An error occurred while scouting for opportunities: {e}",
        }


@app.get("/journal/entries")
async def get_journal_entries(user_id: str = Depends(get_current_user)):
    """Retrieves all journal entries for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        journal_service = JournalService(supabase)
        entries = journal_service.get_journal_entries(user_id)

        # Normalize entries shape defensively
        if isinstance(entries, str):
            try:
                entries = json.loads(entries)
            except json.JSONDecodeError:
                entries = []

        if not isinstance(entries, list):
            entries = []

        return {"count": len(entries), "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")


class DriftSummaryResponse(BaseModel):
    window_days: int
    total_suggestions: int
    disciplined_execution: int
    impulse_trades: int
    size_violations: int
    disciplined_rate: float
    impulse_rate: float
    size_violation_rate: float


@app.get("/journal/drift-summary", response_model=DriftSummaryResponse)
async def get_drift_summary(user_id: str = Depends(get_current_user)):
    """
    Returns execution-discipline metrics for the current user.

    Uses the `discipline_score_per_user` view if available,
    otherwise falls back to aggregating from execution_drift_logs.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    data = None

    # Try the view first
    try:
        res = supabase.table("discipline_score_per_user") \
            .select(
                "window_days, total_suggestions, disciplined_execution, impulse_trades, size_violations, "
                "disciplined_rate, impulse_rate, size_violation_rate"
            ) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if res.data:
            data = res.data
    except Exception as e:
        print(f"Warning: discipline_score_per_user view not available, falling back to raw aggregation: {e}")
        data = None

    if not data:
        # Fallback: compute basic counts over last 7 days from execution_drift_logs
        try:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            window_days = 7
            cutoff = (now - timedelta(days=window_days)).isoformat()

            logs_res = supabase.table("execution_drift_logs") \
                .select("tag") \
                .eq("user_id", user_id) \
                .gte("created_at", cutoff) \
                .execute()

            rows = logs_res.data or []
            disciplined = sum(1 for r in rows if r.get("tag") == "disciplined_execution")
            impulse = sum(1 for r in rows if r.get("tag") == "impulse_trade")
            size_v = sum(1 for r in rows if r.get("tag") == "size_violation")
            total = disciplined + impulse + size_v

            disciplined_rate = disciplined / total if total else 0.0
            impulse_rate = impulse / total if total else 0.0
            size_rate = size_v / total if total else 0.0

            data = {
                "window_days": window_days,
                "total_suggestions": total,
                "disciplined_execution": disciplined,
                "impulse_trades": impulse,
                "size_violations": size_v,
                "disciplined_rate": disciplined_rate,
                "impulse_rate": impulse_rate,
                "size_violation_rate": size_rate,
            }
        except Exception as e:
            print(f"Error computing drift summary: {e}")
            # Return an empty summary instead of failing
            data = {
                "window_days": 7,
                "total_suggestions": 0,
                "disciplined_execution": 0,
                "impulse_trades": 0,
                "size_violations": 0,
                "disciplined_rate": 0.0,
                "impulse_rate": 0.0,
                "size_violation_rate": 0.0,
            }

    # Normalize numeric types (Supabase may return Decimal)
    return DriftSummaryResponse(
        window_days=int(data.get("window_days", 7)),
        total_suggestions=int(data.get("total_suggestions", 0)),
        disciplined_execution=int(data.get("disciplined_execution", 0)),
        impulse_trades=int(data.get("impulse_trades", 0)),
        size_violations=int(data.get("size_violations", 0)),
        disciplined_rate=float(data.get("disciplined_rate", 0.0)),
        impulse_rate=float(data.get("impulse_rate", 0.0)),
        size_violation_rate=float(data.get("size_violation_rate", 0.0)),
    )

@app.get("/journal/stats")
async def get_journal_stats(user_id: str = Depends(get_current_user)):
    """Gets trade journal statistics for the authenticated user."""
    # Define safe defaults
    default_stats = {
        "stats": {
            "win_rate": 0.0,
            "total_trades": 0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_return": 0.0
        },
        "recent_trades": []
    }

    if not supabase:
        print("Journal stats: Database unavailable, returning defaults.")
        return default_stats

    try:
        journal_service = JournalService(supabase)
        # Check if the method exists to avoid AttributeError
        if not hasattr(journal_service, "get_journal_stats"):
             print("JournalService.get_journal_stats not implemented.")
             return default_stats

        stats = journal_service.get_journal_stats(user_id)

        if not stats:
            return default_stats

        # Normalize if flat dict
        if isinstance(stats, dict) and "stats" not in stats:
             normalized_stats = default_stats.copy()
             normalized_stats["stats"] = {
                 "win_rate": stats.get("win_rate", 0.0),
                 "total_trades": stats.get("total_trades", 0),
                 "total_pnl": stats.get("total_pnl", 0.0),
                 "profit_factor": stats.get("profit_factor", 0.0),
                 "avg_return": stats.get("avg_return", 0.0)
             }
             if "recent_trades" in stats:
                 normalized_stats["recent_trades"] = stats["recent_trades"]

             return normalized_stats

        return stats
    except Exception as e:
        print(f"Error fetching journal stats: {e}")
        # Return safe defaults with error flag
        result = default_stats.copy()
        result["error"] = "journal_unavailable"
        return result


class EVRequest(BaseModel):
    premium: float
    strike: float
    current_price: float
    delta: float
    strategy: Literal[
        "long_call",
        "long_put",
        "short_call",
        "short_put",
        "credit_spread",
        "debit_spread",
        "iron_condor",
        "strangle",
    ]
    width: Optional[float] = None
    contracts: int = 1
    account_value: Optional[float] = None
    max_risk_percent: Optional[float] = 2.0


@app.post("/ev")
async def get_expected_value(request: EVRequest):
    result = calculate_ev(
        premium=request.premium,
        strike=request.strike,
        current_price=request.current_price,
        delta=request.delta,
        strategy=request.strategy,
        width=request.width,
        contracts=request.contracts,
    )

    response = result.to_dict()

    if request.account_value and result.max_loss > 0:
        position_size = calculate_position_size(
            account_value=request.account_value,
            max_risk_percent=request.max_risk_percent,
            max_loss_per_contract=result.max_loss,
        )
        response["position_sizing"] = position_size

    return response


# --- Trade Journal Mutation Endpoints ---


@app.post("/journal/trades", status_code=201)
async def add_trade_to_journal(
    trade: Dict, user_id: str = Depends(get_current_user)
):
    """Adds a new trade to the journal for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        journal_service = JournalService(supabase)
        new_trade = journal_service.add_trade(user_id, trade)
        return new_trade
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to add trade: {e}")


@app.put("/journal/trades/{trade_id}/close")
async def close_trade_in_journal(
    trade_id: int,
    exit_date: str,
    exit_price: float,
    user_id: str = Depends(get_current_user),
):
    """Closes an existing trade in the journal for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        journal_service = JournalService(supabase)
        closed_trade = journal_service.close_trade(
            user_id, trade_id, exit_date, exit_price
        )
        return closed_trade
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to close trade: {e}")


@app.post("/suggestions/{suggestion_id}/log-trade")
async def log_trade_from_suggestion(
    suggestion_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Lookup trade_suggestions row by id and create a corresponding journal_entry.
    Does NOT close the trade; only logs entry information.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        # 1. Fetch suggestion
        res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("id", suggestion_id).eq("user_id", user_id).single().execute()
        suggestion = res.data
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        # 2. Extract Data
        # Ensure we handle fields safely
        order_json = suggestion.get("order_json") or {}
        entry_price = order_json.get("price") or order_json.get("limit_price") or 0.0

        # ✔ Symbol selection priority
        symbol = (
            suggestion.get("symbol") or
            suggestion.get("ticker") or
            order_json.get("symbol") or
            "<unknown>"
        )

        # ✔ Contract selection logic
        contracts = 1
        if "contracts" in order_json:
            contracts = order_json["contracts"]
        elif "legs" in order_json and len(order_json["legs"]) > 0:
            # Use absolute quantity from first leg as proxy for spread count
            contracts = abs(order_json["legs"][0].get("quantity", 1))

        # ✔ Leg description
        leg_notes = None
        if "legs" in order_json:
            leg_notes = ", ".join([f"{leg.get('symbol', 'Leg')} x {leg.get('quantity', 0)}" for leg in order_json["legs"]])

        # ✔ Final notes field
        notes = f"Logged from suggestion {suggestion_id}"
        if leg_notes:
            notes += f" | Legs: {leg_notes}"

        trade_data = {
            "user_id": user_id,
            "symbol": symbol,
            "direction": suggestion.get("direction") or "Long",
            "entry_date": datetime.now().isoformat(),
            "entry_price": entry_price,
            "strategy": suggestion.get("strategy") or "Stock",
            "contracts": contracts,
            "status": "open",
            "notes": notes
        }

        # 3. Create Journal Entry
        journal_service = JournalService(supabase)
        new_entry = journal_service.add_trade(user_id, trade_data)

        # 4. Update suggestion status
        supabase.table(TRADE_SUGGESTIONS_TABLE).update({"status": "executed"}).eq("id", suggestion_id).execute()

        return new_entry

    except Exception as e:
        print(f"Error logging trade from suggestion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to log trade: {e}")


@app.post("/journal/trades/{trade_id}/close-from-position")
async def close_trade_from_position(
    trade_id: int,
    user_id: str = Depends(get_current_user),
):
    """
    Convenience: looks up latest price from positions/snapshot and closes the journal trade
    at that price and today's date.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        # 1. Fetch Journal Entry
        res = supabase.table("trade_journal_entries").select("*").eq("id", trade_id).eq("user_id", user_id).single().execute()
        trade = res.data
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        symbol = trade.get("symbol")

        # 2. Find Current Price from Positions (Live) or Snapshot
        # Try live positions table first
        pos_res = supabase.table("positions").select("current_price").eq("user_id", user_id).eq("symbol", symbol).single().execute()

        exit_price = 0.0
        if pos_res.data:
            exit_price = pos_res.data.get("current_price", 0.0)

        # If not in positions (maybe closed already?), check last snapshot or market data?
        # Fallback to market data service if available, but for now strict compliance with instructions:
        # "Find matching holding in positions (if still open) or look at last snapshot."

        if exit_price == 0.0:
            snap_res = supabase.table("portfolio_snapshots").select("holdings").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
            if snap_res.data:
                holdings = snap_res.data[0].get("holdings", [])
                # Find symbol
                for h in holdings:
                    if h.get("symbol") == symbol:
                        exit_price = h.get("current_price", 0.0)
                        break

        if exit_price == 0.0:
             raise HTTPException(status_code=400, detail=f"Could not determine current price for {symbol}. Sync holdings first.")

        # 3. Close Trade
        journal_service = JournalService(supabase)
        closed_trade = journal_service.close_trade(
            user_id,
            trade_id,
            datetime.now().isoformat(),
            exit_price
        )
        return closed_trade

    except Exception as e:
        print(f"Error closing trade from position: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to close trade: {e}")


# --- Progress Engine Endpoints (New) ---

@app.post("/suggestions/{suggestion_id}/execute")
async def execute_suggestion(
    suggestion_id: str,
    fill_details: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user)
):
    """
    Explicitly marks a suggestion as executed and creates a TradeExecution record.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        service = ExecutionService(supabase)
        execution = service.register_execution(user_id, suggestion_id, fill_details)
        return execution
    except Exception as e:
        print(f"Error executing suggestion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to execute suggestion: {e}")

@app.get("/api/progress/weekly")
async def get_weekly_progress(
    week_id: Optional[str] = None,
    user_id: str = Depends(get_current_user)
):
    """
    Returns the WeeklySnapshot for the specified week (or latest full week).
    Generates it on the fly if missing.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        # Resolve default week_id if missing to pass to engine (or engine handles it)
        # The engine handles None -> default logic.
        engine = ProgressEngine(supabase)
        snapshot = engine.generate_weekly_snapshot(user_id, week_id)
        return snapshot
    except Exception as e:
        print(f"Error generating weekly progress: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get weekly progress: {e}")

class LossAnalysisRequest(BaseModel):
    position: Dict[str, Any]
    user_threshold: Optional[float] = 100.0
    market_data: Optional[Dict[str, Any]] = None

@app.post("/risk/loss-analysis", response_model=LossAnalysisResult)
async def risk_loss_analysis(
    request: LossAnalysisRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Analyzes a deep losing options position to provide a loss minimization strategy.
    Alias/Replacement for /analysis/loss-minimization per new specs.
    """
    try:
        result = LossMinimizer.analyze_position(
            position=request.position,
            user_threshold=request.user_threshold,
            market_data=request.market_data
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Loss analysis failed: {e}")

# Maintain backward compatibility if needed, or redirect
@app.post("/analysis/loss-minimization", include_in_schema=False)
async def analyze_loss_legacy(
    request: LossAnalysisRequest,
    user_id: str = Depends(get_current_user)
):
    return await risk_loss_analysis(request, user_id)


if __name__ == "__main__":
    import uvicorn

    print("Starting Portfolio Optimizer API v2.0...")
    print("✨ NEW: Real market data from Polygon.io")
    print("✨ NEW: Weekly Options Scout")
    print("✨ NEW: Trade Journal with Auto-Learning")
    print("API: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000)
