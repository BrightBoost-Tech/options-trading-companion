import os
import io
import csv
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Literal, Any
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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

# 1. Load environment variables BEFORE importing other things
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from packages.quantum.security import encrypt_token, decrypt_token, get_current_user
from packages.quantum.security.config import validate_security_config
from packages.quantum.security.secrets_provider import SecretsProvider

# Validate Security Config on Startup
validate_security_config()

# Import models and services
from packages.quantum.models import Holding, SyncResponse, PortfolioSnapshot, Spread, SpreadPosition, RiskDashboardResponse, UnifiedPosition, OptimizationRationale
from packages.quantum.config import ENABLE_REBALANCE_CONVICTION, ENABLE_REBALANCE_CONVICTION_SHADOW
from packages.quantum.analytics.conviction_service import ConvictionService, PositionDescriptor
from packages.quantum import plaid_service
from packages.quantum import plaid_endpoints

# Import functionalities
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.services.journal_service import JournalService
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.analytics_service import AnalyticsService
from packages.quantum.optimizer import router as optimizer_router
from packages.quantum.market_data import calculate_portfolio_inputs, PolygonService
# New Services for Cash-Aware Workflow
from packages.quantum.services.workflow_orchestrator import run_morning_cycle, run_midday_cycle, run_weekly_report
from packages.quantum.services.plaid_history_service import PlaidHistoryService
from packages.quantum.services.rebalance_engine import RebalanceEngine
from packages.quantum.services.execution_service import ExecutionService
from packages.quantum.analytics.progress_engine import ProgressEngine, get_week_id_for_last_full_week
from packages.quantum.services.options_utils import group_spread_positions, format_occ_symbol_readable
from packages.quantum.ev_calculator import calculate_ev, calculate_position_size
from packages.quantum.services.enrichment_service import enrich_holdings_with_analytics
from packages.quantum.services.historical_simulation import HistoricalCycleService
from packages.quantum.analytics.loss_minimizer import LossMinimizer, LossAnalysisResult
from packages.quantum.analytics.drift_auditor import audit_plan_vs_execution
from packages.quantum.analytics.greeks_aggregator import aggregate_portfolio_greeks, build_greek_alerts
from packages.quantum.services.risk_engine import RiskEngine
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, GlobalRegimeSnapshot, RegimeState
from packages.quantum.analytics.iv_regime_service import IVRegimeService

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, compute_features_hash, emit_trade_event

TEST_USER_UUID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"
APP_VERSION = os.getenv("APP_VERSION", "v2-dev")

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

# Initialize Supabase Admin Client (Service Role)
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key

supabase_admin: Client = create_client(url, key) if url and key else None

# Initialize Analytics Service (Use Admin Client for system logging)
analytics_service = AnalyticsService(supabase_admin)
app.state.analytics_service = analytics_service

# RLS-Aware Client Dependency
def get_supabase_user_client(
    user_id: str = Depends(get_current_user),
    request: Request = None
) -> Client:
    # Check if we have a real Bearer token
    auth_header = request.headers.get("Authorization")
    is_bearer = auth_header and auth_header.startswith("Bearer ")

    if is_bearer:
        token = auth_header.split(" ")[1]
        if supa_secrets.url and supa_secrets.anon_key:
            client = create_client(supa_secrets.url, supa_secrets.anon_key)
            client.postgrest.auth(token)
            return client

    if os.getenv("APP_ENV") != "production" and os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1":
        if request.headers.get("X-Test-Mode-User") == user_id:
             import jwt
             if supa_secrets.jwt_secret:
                 payload = {
                     "sub": user_id,
                     "aud": "authenticated",
                     "role": "authenticated",
                     "exp": 9999999999
                 }
                 fake_token = jwt.encode(payload, supa_secrets.jwt_secret, algorithm="HS256")
                 client = create_client(supa_secrets.url, supa_secrets.anon_key)
                 client.postgrest.auth(fake_token)
                 return client

    return supabase_admin

# --- Register Plaid Endpoints ---
plaid_endpoints.register_plaid_endpoints(
    app,
    plaid_service,
    supabase_admin,
    analytics_service,
    get_supabase_user_client
)

# --- Register Optimizer Endpoints ---
app.include_router(optimizer_router)

# --- Register Strategy Endpoints ---
from packages.quantum.strategy_endpoints import router as strategy_router
app.include_router(strategy_router)

# --- Register Paper Trading Endpoints ---
from packages.quantum.paper_endpoints import router as paper_router
app.include_router(paper_router)

# --- Register Internal Task Endpoints ---
from packages.quantum.internal_tasks import router as internal_tasks_router
app.include_router(internal_tasks_router)

# --- IV & Market Context Endpoints ---

@app.get("/market/iv-context")
async def get_iv_context(
    symbol: str,
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        repo = IVRepository(supabase)
        context = repo.get_iv_context(symbol.upper())
        return context
    except Exception as e:
        print(f"Error getting IV context for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks/iv/daily-refresh", deprecated=True)
def iv_daily_refresh_task_deprecated(
    x_cron_secret: str = Header(None, alias="X-Cron-Secret")
):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

# --- Rebalance Engine Endpoints (Step 3) ---

@app.post("/rebalance/execute")
async def execute_rebalance(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Runs the rebalance engine with V3 Regime Engine:
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
    from packages.quantum.optimizer import _compute_portfolio_weights, OptimizationRequest, calculate_dynamic_target

    # --- V3: Regime Engine Integration ---
    # Instantiate services
    market_data = PolygonService()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)
    regime_engine = RegimeEngineV3(market_data, iv_repo, iv_point_service)

    # Compute Global Snapshot
    now = datetime.now()
    universe_symbols = None
    try:
        # Optimization: We could fetch universe, but default basket is usually fine
        pass
    except Exception:
        pass

    global_snap = regime_engine.compute_global_snapshot(now, universe_symbols)

    # Store global snapshot to DB
    try:
        supabase.table("regime_snapshots").insert(global_snap.to_dict()).execute()
    except Exception as e:
        print(f"Failed to persist global regime snapshot: {e}")

    # Build positions for conviction service
    iv_service = IVRegimeService(supabase)
    unique_tickers = [s.ticker for s in current_spreads]
    iv_ctx_map = iv_service.get_iv_context_for_symbols(unique_tickers)

    positions_for_conviction: List[PositionDescriptor] = []
    for spread in current_spreads:
        ctx = iv_ctx_map.get(spread.ticker, {})
        iv_rank = ctx.get("iv_rank")

        positions_for_conviction.append(
            PositionDescriptor(
                symbol=spread.ticker,
                underlying=spread.underlying or spread.ticker,
                strategy_type=spread.spread_type or "other",
                direction="long" if spread.net_delta >= 0 else "short",
                iv_rank=float(iv_rank) if iv_rank is not None else None
            )
        )

    # V3: Regime Context uses Global Snapshot mapping
    current_regime_scoring = regime_engine.map_to_scoring_regime(global_snap.state)

    # Compute Real Universe Median from Risk Score (0-10 scale -> 0-100 scale approximation)
    universe_median = max(20.0, min(80.0, 70.0 - (global_snap.risk_score * 5.0)))

    regime_context = {
        "current_regime": current_regime_scoring, # mapped "normal"/"high_vol"/"panic"
        "global_state": global_snap.state.value,
        "global_score": global_snap.risk_score,
        "risk_scaler": global_snap.risk_scaler,
        "universe_median": universe_median,
    }

    conviction_service = ConvictionService(supabase=supabase)
    real_conviction_map = conviction_service.get_portfolio_conviction(
        positions=positions_for_conviction,
        regime_context=regime_context,
        user_id=user_id,
    )

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
        from packages.quantum.market_data import calculate_portfolio_inputs
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

             # Apply Risk Scaler from Regime Engine to Sigma
             scaler = global_snap.risk_scaler
             if scaler < 0.1: scaler = 0.1 # Safety floor
             sigma_multiplier = 1.0 / scaler

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

             # Apply Regime Scaling
             sigma = sigma * (sigma_multiplier ** 2)

             coskew = np.zeros((n, n, n))

             target_weights, _, _, trace_id, _, _, _, _ = _compute_portfolio_weights(
                 mu, sigma, coskew, tickers, current_spreads, opt_req, user_id, total_val, cash,
                 external_risk_scaler=global_snap.risk_scaler
             )

             red_flags = []
             if not trace_id:
                 red_flags.append("optimizer_trace_missing")

             spread_map = {s.ticker: s for s in current_spreads}

             targets = []
             for sym, w in target_weights.items():
                 spread_obj = spread_map.get(sym)
                 strat_type = spread_obj.spread_type if spread_obj else "other"

                 regime_key = global_snap.state.value

                 # Retrieve Regime for conviction call
                 ctx = iv_ctx_map.get(sym, {})
                 regime = ctx.get("iv_regime", current_regime_scoring)

                 # Default neutral conviction
                 base_conviction = 1.0

                 if ENABLE_REBALANCE_CONVICTION:
                     key = spread_obj.underlying if spread_obj and spread_obj.underlying else sym
                     base_conviction = real_conviction_map.get(key, real_conviction_map.get(sym, 0.5))

                 conviction_used = base_conviction
                 if not ENABLE_REBALANCE_CONVICTION and ENABLE_REBALANCE_CONVICTION_SHADOW:
                     conviction_used = 1.0
                 elif not ENABLE_REBALANCE_CONVICTION:
                     conviction_used = 1.0

                 # Apply Dynamic Constraint with REAL regime & conviction
                 adjusted_w = calculate_dynamic_target(
                     base_weight=w,
                     strategy_type=strat_type,
                     regime=regime_key, # V3 State
                     conviction=conviction_used
                 )

                 targets.append({
                     "type": "spread",
                     "symbol": sym,
                     "target_allocation": adjusted_w
                 })
             return targets, trace_id, red_flags, regime

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Offload heavy compute to thread
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            targets, trace_id, red_flags, regime_val = await loop.run_in_executor(pool, run_optimizer_logic)
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

    # 5. Save to DB with v3 Traceability
    saved_count = 0
    if trades:
        supabase.table(TRADE_SUGGESTIONS_TABLE).delete().eq("user_id", user_id).eq("window", "rebalance").execute()

        db_rows = []
        for t in trades:
            sym = t["symbol"]
            strategy = t.get("spread_type", "custom")

            # Create Trace Context
            features_dict = {
                "symbol": sym,
                "target_allocation": t.get("target_weight", 0),
                "strategy": strategy,
                "global_regime": global_snap.state.value,
                "risk_score": global_snap.risk_score
            }

            ctx = TradeContext.create_new(
                model_version=APP_VERSION,
                window="rebalance",
                strategy=strategy,
                regime=global_snap.state.value
            )
            ctx.features_hash = compute_features_hash(features_dict)

            if "context" not in t:
                t["context"] = {}
            t["context"]["trace_id"] = ctx.trace_id
            t["context"]["regime_details"] = global_snap.to_dict()

            if red_flags:
                emit_props = {"red_flags": red_flags, "symbol": sym}
            else:
                emit_props = {"symbol": sym}

            db_rows.append({
                "user_id": user_id,
                "symbol": sym,
                "strategy": strategy,
                "direction": t["side"].title(),
                "confidence_score": 0,
                "ev": 0,
                "order_json": t,
                "status": "pending",
                "window": "rebalance",
                "created_at": datetime.now().isoformat(),
                "notes": t.get("reason", ""),
                "trace_id": ctx.trace_id,
                "model_version": ctx.model_version,
                "features_hash": ctx.features_hash,
                "regime": ctx.regime
            })

            emit_trade_event(
                analytics_service,
                user_id,
                ctx,
                "suggestion_generated",
                properties={
                    "target_allocation": t.get("target_weight", 0),
                    **emit_props
                }
            )

        res = supabase.table(TRADE_SUGGESTIONS_TABLE).insert(db_rows).execute()
        saved_count = len(res.data) if res.data else 0

    return {
        "status": "ok",
        "count": saved_count,
        "trades": trades
    }

@app.get("/suggestions")
async def get_suggestions(
    window: Optional[str] = None,
    status: Optional[str] = "pending",
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Generic suggestions endpoint used by the dashboard.
    Supported windows: morning_limit, midday_entry, rebalance
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        query = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id)
        if window:
            query = query.eq("window", window)
        if status:
            query = query.eq("status", status)
        res = query.order("created_at", desc=True).execute()

        suggestions = res.data or []
        for s in suggestions:
            sym = s.get("symbol") or s.get("ticker", "")
            if "O:" in sym or (len(sym) > 15 and any(c.isdigit() for c in sym)):
                s["display_symbol"] = format_occ_symbol_readable(sym)
            else:
                s["display_symbol"] = sym

            if "order_json" in s and isinstance(s["order_json"], dict) and "legs" in s["order_json"]:
                for leg in s["order_json"]["legs"]:
                    if "symbol" in leg:
                        leg["display_symbol"] = format_occ_symbol_readable(leg["symbol"])

        return {"suggestions": suggestions}
    except Exception as e:
        print(f"Error fetching suggestions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch suggestions")

@app.get("/rebalance/suggestions")
async def get_rebalance_suggestions(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    return await get_suggestions(window="rebalance", status="pending", user_id=user_id, supabase=supabase)

# --- Helper Functions ---

def get_active_user_ids() -> List[str]:
    """Helper to get list of active user IDs."""
    if not supabase_admin:
        return []
    try:
        # For now, derive from user_settings table
        res = supabase_admin.table("user_settings").select("user_id").execute()
        return [r["user_id"] for r in res.data or []]
    except Exception as e:
        print(f"Error fetching active users: {e}")
        return []


def verify_cron_secret(x_cron_secret: str = Header(None, alias="X-Cron-Secret")):
    """Dependency to verify the Cron Secret header."""
    cron_secret = os.getenv("CRON_SECRET")
    if not cron_secret or x_cron_secret != cron_secret:
        raise HTTPException(status_code=401, detail="Unauthorized task caller")


async def create_portfolio_snapshot(user_id: str, supabase_client: Client = None) -> None:
    """Creates a new portfolio snapshot from current positions."""
    # Use passed client if available (for RLS), else fallback to admin for internal tasks
    client = supabase_client or supabase_admin
    if not client:
        return

    # 1. Fetch current holdings from POSITIONS table (Single Truth)
    response = (
        client.table("positions").select("*").eq("user_id", user_id).execute()
    )
    holdings = response.data

    # If no holdings, just abort snapshot creation gracefully
    if not holdings:
        return

    # 2. Enrich Holdings with Analytics
    holdings = enrich_holdings_with_analytics(holdings)

    # 3. Calculate Risk Metrics (Basic)
    # Filter out CASH and CUR:USD to prevent Polygon 400 errors
    symbols = [
        h["symbol"]
        for h in holdings
        if h.get("symbol")
        and not h["symbol"].startswith("CUR:")
        and not h["symbol"].startswith("O:CUR:")
        and h["symbol"] not in ["USD", "CASH", "USD CASH"]
    ]
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
        # Soft failure: log error but don't crash, return partial metrics
        risk_metrics = {"error": str(e)}

    # Group into spreads for snapshot
    spreads = group_spread_positions(holdings)
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
    }

    client.table("portfolio_snapshots").insert(snapshot).execute()


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
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Endpoint for frontend to log events securely.
    """
    user_analytics = AnalyticsService(supabase)
    user_analytics.log_event(
        user_id=user_id,
        event_name=req.event_name,
        category=req.category,
        properties=req.properties
    )
    return {"status": "logged"}


# --- Cron Task Endpoints (DEPRECATED) ---

@app.post("/tasks/morning-brief", deprecated=True)
async def morning_brief_deprecated(_: None = Depends(verify_cron_secret)):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

@app.post("/tasks/midday-scan", deprecated=True)
async def midday_scan_deprecated(_: None = Depends(verify_cron_secret)):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

@app.post("/tasks/weekly-report", deprecated=True)
async def weekly_report_deprecated(_: None = Depends(verify_cron_secret)):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

@app.post("/tasks/universe/sync", deprecated=True)
async def universe_sync_deprecated(_: None = Depends(verify_cron_secret)):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

@app.post("/tasks/plaid/backfill-history", deprecated=True)
async def backfill_history_deprecated(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
    x_cron_secret: str = Header(None, alias="X-Cron-Secret")
):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")


# --- Rebalance Endpoints (Spec B) ---

@app.post("/rebalance/preview")
async def preview_rebalance(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Preview rebalance suggestions without executing or persisting heavily.
    Matches logic of /rebalance/execute as much as possible for consistency.
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
    from packages.quantum.optimizer import _compute_portfolio_weights, OptimizationRequest, calculate_dynamic_target

    # --- V3: Regime Engine Integration (Preview Mode: Global Only for Speed) ---
    market_data = PolygonService()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)
    regime_engine = RegimeEngineV3(market_data, iv_repo, iv_point_service)

    now = datetime.now()
    global_snap = regime_engine.compute_global_snapshot(now) # Skip symbol snapshot for preview speed

    # Build positions for conviction service
    iv_service = IVRegimeService(supabase)
    unique_tickers = [s.ticker for s in current_spreads]
    iv_ctx_map = iv_service.get_iv_context_for_symbols(unique_tickers)

    positions_for_conviction: List[PositionDescriptor] = []
    for spread in current_spreads:
        ctx = iv_ctx_map.get(spread.ticker, {})
        iv_rank = ctx.get("iv_rank")

        positions_for_conviction.append(
            PositionDescriptor(
                symbol=spread.ticker,
                underlying=spread.underlying or spread.ticker,
                strategy_type=spread.spread_type or "other",
                direction="long" if spread.net_delta >= 0 else "short",
                iv_rank=float(iv_rank) if iv_rank is not None else None
            )
        )

    current_regime_scoring = regime_engine.map_to_scoring_regime(global_snap.state)
    universe_median = max(20.0, min(80.0, 70.0 - (global_snap.risk_score * 5.0)))

    regime_context = {
        "current_regime": current_regime_scoring,
        "global_state": global_snap.state.value,
        "global_score": global_snap.risk_score,
        "risk_scaler": global_snap.risk_scaler,
        "universe_median": universe_median,
    }

    conviction_service = ConvictionService(supabase=supabase)
    real_conviction_map = conviction_service.get_portfolio_conviction(
        positions=positions_for_conviction,
        regime_context=regime_context,
        user_id=user_id,
    )

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
        from packages.quantum.market_data import calculate_portfolio_inputs
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

             scaler = global_snap.risk_scaler
             if scaler < 0.1: scaler = 0.1
             sigma_multiplier = 1.0 / scaler

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

             sigma = sigma * (sigma_multiplier ** 2)
             coskew = np.zeros((n, n, n))

             target_weights, _, _, trace_id, _, _, _, _ = _compute_portfolio_weights(
                 mu, sigma, coskew, tickers, current_spreads, opt_req, user_id, total_val, cash
             )

             spread_map = {s.ticker: s for s in current_spreads}
             targets = []
             for sym, w in target_weights.items():
                 spread_obj = spread_map.get(sym)
                 strat_type = spread_obj.spread_type if spread_obj else "other"
                 regime_key = global_snap.state.value
                 base_conviction = 1.0

                 if ENABLE_REBALANCE_CONVICTION:
                     key = spread_obj.underlying if spread_obj and spread_obj.underlying else sym
                     base_conviction = real_conviction_map.get(key, real_conviction_map.get(sym, 0.5))

                 conviction_used = base_conviction
                 if not ENABLE_REBALANCE_CONVICTION and ENABLE_REBALANCE_CONVICTION_SHADOW:
                     conviction_used = 1.0
                 elif not ENABLE_REBALANCE_CONVICTION:
                     conviction_used = 1.0

                 adjusted_w = calculate_dynamic_target(
                     base_weight=w,
                     strategy_type=strat_type,
                     regime=regime_key,
                     conviction=conviction_used
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

# --- Development Endpoints ---

@app.post("/tasks/run-all")
async def run_all(user_id: str = Depends(get_current_user)):
    """Dev-only: Manually trigger all workflows for the current user."""
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")

    print(f"DEV: Running Morning Cycle for {user_id}")
    await run_morning_cycle(supabase_admin, user_id)

    print(f"DEV: Running Midday Cycle for {user_id}")
    await run_midday_cycle(supabase_admin, user_id)

    print(f"DEV: Running Weekly Report for {user_id}")
    await run_weekly_report(supabase_admin, user_id)

    return {"status": "ok", "message": "All workflows triggered manually"}


# --- New Data Endpoints ---

@app.post("/historical/run-cycle")
async def run_historical_cycle(
    cursor: str = Body(..., embed=True),
    symbol: Optional[str] = Body("SPY", embed=True),
    mode: Optional[str] = Body("deterministic", embed=True),
    seed: Optional[int] = Body(None, embed=True),
    user_id: str = Depends(get_current_user),
):
    try:
        service = HistoricalCycleService()
        result = service.run_cycle(cursor, symbol, user_id=user_id, mode=mode, seed=seed)
        return result
    except Exception as e:
        print(f"Historical cycle error: {e}")
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")

class DriftSummaryResponse(BaseModel):
    window_days: int
    total_suggestions: int
    disciplined_execution: int
    impulse_trades: int
    size_violations: int
    disciplined_rate: float
    impulse_rate: float
    size_violation_rate: float

@app.get("/weekly-reports")
async def get_weekly_reports(
    limit: int = 4,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
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
@limiter.limit("5/minute")
async def sync_holdings(
    request: Request,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
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
            pass

    if not supabase:
        raise HTTPException(
            status_code=500, detail="Server Error: Database not configured"
        )

    # 2. Retrieve Plaid Access Token
    plaid_access_token: Optional[str] = None
    if supabase:
        from packages.quantum.services.token_store import PlaidTokenStore
        token_store = PlaidTokenStore(supabase)
        plaid_access_token = token_store.get_access_token(user_id)

    # 3. Fetch from Plaid
    errors: List[str] = []
    holdings: List[Holding] = []
    sync_attempted = False

    if plaid_access_token:
        try:
            print("Fetching Plaid holdings...")
            plaid_holdings = plaid_service.fetch_and_normalize_holdings(
                plaid_access_token
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
        await create_portfolio_snapshot(user_id, supabase_client=supabase)

        # Log Sync Completed
        analytics_service.log_event(user_id, "plaid_sync_completed", "system", {"status": "success"})

        # 6. Drift Audit
        if supabase:
            try:
                snap_res = supabase.table("portfolio_snapshots").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
                current_snapshot = snap_res.data[0] if snap_res.data else None
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
                sugg_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id).gte("created_at", cutoff).execute()
                recent_suggestions = sugg_res.data or []

                if current_snapshot:
                    print(f"🕵️  Running Drift Auditor for user {user_id}")
                    audit_plan_vs_execution(user_id, current_snapshot, recent_suggestions, supabase)

            except Exception as e:
                print(f"⚠️  Drift Auditor failed: {e}")

    return SyncResponse(status="success", count=len(holdings), holdings=holdings)


@app.get("/holdings/export")
async def export_holdings_csv(
    brokerage: Optional[str] = None,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(
            status_code=500, detail="Server Error: Database not configured"
        )

    query = supabase.table("positions").select("*").eq("user_id", user_id)
    response = query.execute()
    positions = response.data

    if not positions:
        raise HTTPException(
            status_code=404, detail="No holdings found to export"
        )

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


@app.get("/risk/dashboard", response_model=RiskDashboardResponse)
async def get_risk_dashboard(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
    raw_positions = res.data or []
    enriched = enrich_holdings_with_analytics(raw_positions)
    unified_positions = RiskEngine.build_unified_positions(enriched)
    summary = RiskEngine.compute_risk_summary(unified_positions)

    return RiskDashboardResponse(**summary)

@app.get("/portfolio/snapshot")
async def get_portfolio_snapshot(
    user_id: str = Depends(get_current_user),
    refresh: bool = False,
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

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

    if snapshot_data:
        if "holdings" in snapshot_data:
            for h in snapshot_data["holdings"]:
                s = h.get("symbol", "")
                if "O:" in s or h.get("asset_type") == "OPTION" or len(s) > 15:
                    h["display_symbol"] = format_occ_symbol_readable(s)
                else:
                    h["display_symbol"] = s

            snapshot_data["spreads"] = group_spread_positions(snapshot_data["holdings"])
            for spread in snapshot_data["spreads"]:
                for leg in spread.legs:
                    leg["display_symbol"] = format_occ_symbol_readable(leg["symbol"])

    if snapshot_data:
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
            pass
        return snapshot_data
    else:
        return {"message": "No snapshot found", "holdings": [], "spreads": []}


@app.get("/scout/weekly")
async def weekly_scout(
    mode: str = "holdings",
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        symbols_to_scan = None
        source_label = "user-holdings"

        if mode == "holdings":
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
            source_label = "market-universe"

        opportunities = scan_for_opportunities(
            symbols=symbols_to_scan,
            supabase_client=supabase
        )

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
async def get_journal_entries(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        journal_service = JournalService(supabase)
        entries = journal_service.get_journal_entries(user_id)

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


@app.get("/journal/drift-summary", response_model=DriftSummaryResponse)
async def get_drift_summary(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    data = None
    try:
        res = supabase.table("discipline_score_per_user") \
            .select("disciplined_count, impulse_count, size_violation_count, discipline_score") \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        row = res.data
        if row:
            disciplined = int(row.get("disciplined_count", 0))
            impulse = int(row.get("impulse_count", 0))
            size_v = int(row.get("size_violation_count", 0))
            total = disciplined + impulse + size_v

            disciplined_rate = float(row.get("discipline_score", 0.0))
            impulse_rate = (impulse / total) if total else 0.0
            size_rate = (size_v / total) if total else 0.0

            data = {
                "window_days": 7,
                "total_suggestions": total,
                "disciplined_execution": disciplined,
                "impulse_trades": impulse,
                "size_violations": size_v,
                "disciplined_rate": disciplined_rate,
                "impulse_rate": impulse_rate,
                "size_violation_rate": size_rate,
            }
    except Exception:
        data = None

    if not data:
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
        except Exception:
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
async def get_journal_stats(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
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
        return default_stats

    try:
        journal_service = JournalService(supabase)
        if not hasattr(journal_service, "get_journal_stats"):
             return default_stats

        stats = journal_service.get_journal_stats(user_id)
        if not stats:
            return default_stats

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
    except Exception:
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


@app.post("/optimizer/explain", response_model=OptimizationRationale)
async def explain_optimizer_run(
    run_id: str = Body("latest", embed=True),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        query = supabase.table("inference_log").select("*")
        if run_id != "latest":
            query = query.eq("trace_id", run_id)
        res = query.order("created_at", desc=True).limit(1).execute()

        if not res.data:
            return OptimizationRationale(
                status="OPTIMAL",
                trace_id=None,
                regime_detected="unknown",
                conviction_used=1.0,
                active_constraints=["No optimization run found."]
            )

        log_entry = res.data[0]
        diagnostics = log_entry.get("diagnostics") or {}

        status = "OPTIMAL"
        if diagnostics.get("error"):
            status = "FAILED"
        elif diagnostics.get("constrained") or diagnostics.get("solver_fallback"):
            status = "CONSTRAINED"

        constraints = []
        if diagnostics.get("solver_fallback"):
            constraints.append("Fallback: Classical Solver used (Quantum unavailable/failed)")
        if diagnostics.get("clamped_weights"):
            constraints.append("Risk Guardrail: Weights clamped to safety limits")
        if diagnostics.get("high_volatility"):
            constraints.append("Regime: High Volatility dampeners active")

        regime = "normal"
        if "regime_context" in log_entry:
            regime = log_entry["regime_context"].get("current_regime", "normal")

        return OptimizationRationale(
            status=status,
            trace_id=log_entry.get("trace_id"),
            regime_detected=regime,
            conviction_used=float(log_entry.get("confidence_score") or 1.0),
            alpha_score=None,
            active_constraints=constraints
        )

    except Exception as e:
        print(f"Error in optimizer/explain: {e}")
        return OptimizationRationale(
            status="FAILED",
            trace_id=None,
            active_constraints=[f"Error retrieving explanation: {str(e)}"]
        )


@app.post("/journal/trades", status_code=201)
async def add_trade_to_journal(
    trade: Dict,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
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
    supabase: Client = Depends(get_supabase_user_client)
):
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
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("id", suggestion_id).eq("user_id", user_id).single().execute()
        suggestion = res.data
        if not suggestion:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        order_json = suggestion.get("order_json") or {}
        entry_price = order_json.get("price") or order_json.get("limit_price") or 0.0

        symbol = (
            suggestion.get("symbol") or
            suggestion.get("ticker") or
            order_json.get("symbol") or
            "<unknown>"
        )

        contracts = 1
        if "contracts" in order_json:
            contracts = order_json["contracts"]
        elif "legs" in order_json and len(order_json["legs"]) > 0:
            contracts = abs(order_json["legs"][0].get("quantity", 1))

        leg_notes = None
        if "legs" in order_json:
            leg_notes = ", ".join([f"{leg.get('symbol', 'Leg')} x {leg.get('quantity', 0)}" for leg in order_json["legs"]])

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

        journal_service = JournalService(supabase)
        new_entry = journal_service.add_trade(user_id, trade_data)

        supabase.table(TRADE_SUGGESTIONS_TABLE).update({"status": "executed"}).eq("id", suggestion_id).execute()

        return new_entry

    except Exception as e:
        print(f"Error logging trade from suggestion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to log trade: {e}")


@app.post("/journal/trades/{trade_id}/close-from-position")
async def close_trade_from_position(
    trade_id: int,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        res = supabase.table("trade_journal_entries").select("*").eq("id", trade_id).eq("user_id", user_id).single().execute()
        trade = res.data
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        symbol = trade.get("symbol")
        pos_res = supabase.table("positions").select("current_price").eq("user_id", user_id).eq("symbol", symbol).single().execute()

        exit_price = 0.0
        if pos_res.data:
            exit_price = pos_res.data.get("current_price", 0.0)

        if exit_price == 0.0:
            snap_res = supabase.table("portfolio_snapshots").select("holdings").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
            if snap_res.data:
                holdings = snap_res.data[0].get("holdings", [])
                for h in holdings:
                    if h.get("symbol") == symbol:
                        exit_price = h.get("current_price", 0.0)
                        break

        if exit_price == 0.0:
             raise HTTPException(status_code=400, detail=f"Could not determine current price for {symbol}. Sync holdings first.")

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


@app.post("/suggestions/{suggestion_id}/execute")
async def execute_suggestion(
    suggestion_id: str,
    fill_details: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
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
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
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
    try:
        result = LossMinimizer.analyze_position(
            position=request.position,
            user_threshold=request.user_threshold,
            market_data=request.market_data
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Loss analysis failed: {e}")

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
