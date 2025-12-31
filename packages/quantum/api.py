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
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import create_client, Client
import uuid
import traceback

# 1. Load environment variables BEFORE importing other things
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from packages.quantum.security import encrypt_token, decrypt_token, get_current_user, get_supabase_user_client
from packages.quantum.security.config import validate_security_config
from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.security.headers_middleware import SecurityHeadersMiddleware

# Validate Security Config on Startup
if os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1":
    print("🔓 DEV AUTH BYPASS ENABLED (expected for local dev only)")
else:
    print("🔒 DEV AUTH BYPASS DISABLED (expected for prod)")
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
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.plaid_history_service import PlaidHistoryService
from packages.quantum.services.rebalance_engine import RebalanceEngine
from packages.quantum.services.risk_budget_engine import RiskBudgetEngine
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

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, compute_features_hash, emit_trade_event

APP_VERSION = os.getenv("APP_VERSION", "v2-dev")

# New Table Constants
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

app = FastAPI(
    title="Portfolio Optimizer API",
    description="Portfolio optimization with real market data",
    version="2.0.0",
)

# Diagnostic endpoint to confirm backend is running correctly
@app.get("/__whoami")
def __whoami():
    return {"server": "packages.quantum.api", "version": APP_VERSION}


@app.get("/health")
def health_check():
    # Sanitize Supabase Status for public response
    safe_supabase_status = {
        "ok": SUPABASE_STATUS.get("ok"),
        "key_type": SUPABASE_STATUS.get("key_type"),
        "connected": SUPABASE_STATUS.get("ok")
    }

    return {
        "status": "ok",
        "app_env": os.getenv("APP_ENV"),
        "supabase": safe_supabase_status,
        "env_loaded": os.path.exists(env_path)
    }


@app.get("/__auth_debug")
def auth_debug(request: Request, user_id: str = Depends(get_current_user)):
    """
    Dev-only endpoint to debug authentication resolution.
    Strictly limited to localhost AND development/test environments.
    """
    app_env = os.getenv("APP_ENV", "development")

    # 🛡️ Sentinel: Whitelist safe environments only
    if app_env not in ["development", "test"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 🛡️ Sentinel: Enforce localhost check regardless of environment setting
    is_local = request.client.host in ("127.0.0.1", "::1", "localhost") if request.client else False
    if not is_local:
        raise HTTPException(status_code=403, detail="Forbidden: Localhost only")

    return {
        "app_env": app_env,
        "enable_dev_auth_bypass": os.getenv("ENABLE_DEV_AUTH_BYPASS"),
        "has_authorization_header": "Authorization" in request.headers,
        "has_x_test_mode_user": "X-Test-Mode-User" in request.headers,
        "resolved_user_id": user_id,
        "is_localhost": is_local
    }


@app.post("/dev/run-midday")
async def dev_run_midday(
    request: Request,
    body: Optional[Dict[str, bool]] = Body(None),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Dev-only endpoint to force run the midday cycle inline.
    Bypasses Redis/RQ.
    """
    # 1. Guardrails
    app_env = os.getenv("APP_ENV", "production")
    dev_bypass = os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1"

    if app_env not in ["development", "test"] and not dev_bypass:
        raise HTTPException(status_code=403, detail="Dev mode only")

    is_local = request.client.host in ("127.0.0.1", "::1", "localhost") if request.client else False
    if not is_local:
        raise HTTPException(status_code=403, detail="Localhost only")

    print(f"🔧 DEV run_midday_cycle invoked for user {user_id}")

    # 2. Run Cycle Inline
    try:
        if not supabase:
            raise HTTPException(status_code=503, detail="Database not available")

        await run_midday_cycle(supabase, user_id)
    except Exception as e:
        print(f"❌ DEV Midday Cycle Failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Cycle failed: {str(e)}")

    return {"status": "ok", "note": "midday cycle executed inline"}


@app.post("/dev/run-all")
async def dev_run_all(
    request: Request,
    user_id: str = Depends(get_current_user),
    x_test_mode_user: Optional[str] = Header(None, alias="X-Test-Mode-User")
):
    """
    Dev-only endpoint to force run morning, midday, and weekly cycles inline.
    Bypasses Redis/RQ. Requires ENABLE_DEV_AUTH_BYPASS=1.
    Strictly restricted to localhost.
    Accepts valid auth token OR X-Test-Mode-User header.
    """
    # 1. Enforce Dev Mode
    if os.getenv("ENABLE_DEV_AUTH_BYPASS") != "1":
        raise HTTPException(status_code=403, detail="Dev mode only")

    # 2. Enforce Localhost
    is_local = request.client.host in ("127.0.0.1", "::1", "localhost") if request.client else False
    if not is_local:
        raise HTTPException(status_code=403, detail="Forbidden: Localhost only")

    # Resolve effective user_id
    effective_user_id = user_id or x_test_mode_user
    if not effective_user_id:
        raise HTTPException(status_code=401, detail="Authentication required (Token or X-Test-Mode-User)")

    print(f"🔧 DEV: Manually triggering ALL workflows for {effective_user_id}")

    try:
        # Run sequentially
        print(">>> Starting Morning Cycle...")
        await run_morning_cycle(supabase_admin, effective_user_id)

        print(">>> Starting Midday Cycle...")
        await run_midday_cycle(supabase_admin, effective_user_id)

        print(">>> Starting Weekly Report...")
        await run_weekly_report(supabase_admin, effective_user_id)

    except Exception as e:
        print(f"❌ DEV Run-All Failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Cycle failed: {str(e)}")

    return {"status": "ok", "message": "All workflows executed inline"}


# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 🛡️ Sentinel: Load allowed origins from env for production flexibility
env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
parsed_origins = [o.strip() for o in env_origins.split(",") if o.strip()]

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
] + parsed_origins

# Add Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Global Exception Handler for CORS on 500s
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = str(uuid.uuid4())[:8]

    # 🛡️ Sentinel: Safe logging
    # In production, we log the error but suppress the stack trace to avoid leaking sensitive data.
    app_env = os.getenv("APP_ENV", "development")

    print(f"Global Exception Handler [Trace: {trace_id}]: {type(exc).__name__}: {exc}")

    if app_env != "production":
        traceback.print_exc()
    else:
        print(f"Stack trace suppressed in production (Trace ID: {trace_id})")

    origin = request.headers.get("origin")
    headers = {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }

    # Mirror allowed origins logic
    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "trace_id": trace_id,
            "note": "Check server logs for full stack trace."
        },
        headers=headers
    )

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase Admin Client (Service Role)
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url

# Deterministic Key Selection
key = None
key_type = "none"

if supa_secrets.service_role_key:
    key = supa_secrets.service_role_key
    key_type = "service_role"
elif supa_secrets.anon_key:
    key = supa_secrets.anon_key
    key_type = "anon (degraded)"
    print("⚠️ WARNING: Using Anon Key for Admin Client. Some operations may fail.")

supabase_admin: Client = create_client(url, key) if url and key else None

# Supabase Startup Validation
SUPABASE_STATUS = {
    "ok": False,
    "url": url,
    "key_type": key_type,
    "error": None
}

if supabase_admin:
    try:
        # Real network request to validate credentials
        # We try to fetch 1 row from scanner_universe which should exist.
        # If this fails with APIError (401), we know keys are bad.
        supabase_admin.table("scanner_universe").select("symbol").limit(1).execute()

        # Redact key for logging
        redacted_key = f"{key[:6]}...{key[-4:]}" if key and len(key) > 10 else "N/A"
        print(f"✅ Supabase Validated: URL={url}, KeyType={key_type}, Key={redacted_key}")
        SUPABASE_STATUS["ok"] = True
    except Exception as e:
        print(f"❌ Supabase Startup Validation Failed: {e}")
        SUPABASE_STATUS["error"] = str(e)
        # We do NOT kill the app, but health check will report failure.
else:
    msg = "Supabase URL or Key missing in environment."
    print(f"❌ {msg}")
    SUPABASE_STATUS["error"] = msg

# Initialize Analytics Service (Use Admin Client for system logging)
analytics_service = AnalyticsService(supabase_admin)
app.state.analytics_service = analytics_service

# --- Register Plaid Endpoints ---
plaid_endpoints.register_plaid_endpoints(
    app,
    plaid_service,
    supabase_admin,
    analytics_service,
    get_supabase_user_client,
    limiter
)

# --- Register Optimizer Endpoints ---
app.include_router(optimizer_router)

# --- Register Strategy Endpoints ---
from packages.quantum.strategy_endpoints import router as strategy_router
app.include_router(strategy_router)

# --- Register Dashboard Endpoints ---
from packages.quantum.dashboard_endpoints import router as dashboard_router
app.include_router(dashboard_router)

# --- Register Paper Trading Endpoints ---
from packages.quantum.paper_endpoints import router as paper_router
app.include_router(paper_router)

# --- Register Internal Task Endpoints ---
from packages.quantum.internal_tasks import router as internal_tasks_router
app.include_router(internal_tasks_router)

# --- Register Public Task Endpoints (Permanent Option A) ---
from packages.quantum.public_tasks import router as public_tasks_router
app.include_router(public_tasks_router)

# --- Register Job Monitoring Endpoints ---
from packages.quantum.jobs.endpoints import router as jobs_router
app.include_router(jobs_router)

# --- Register Observability Endpoints (Internal Dashboard) ---
from packages.quantum.observability.endpoints import router as observability_router
app.include_router(observability_router)

# --- Register Analytics Endpoints ---
from packages.quantum.analytics_endpoints import router as analytics_router
app.include_router(analytics_router)

# --- Register Historical Simulation Endpoints ---
from packages.quantum.historical_endpoints import router as historical_router
app.include_router(historical_router)

# --- Capabilities Endpoint ---
from packages.quantum.services.capability_service import CapabilityResolver

@app.get("/capabilities")
@limiter.limit("20/minute")
def get_user_capabilities(
    request: Request,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    resolver = CapabilityResolver(supabase)
    return resolver.resolve_capabilities(user_id)

# --- Scout Endpoints (New) ---

@app.get("/scout/weekly")
@limiter.limit("5/minute")
def scout_weekly(request: Request, user_id: str = Depends(get_current_user)):
    try:
        results = scan_for_opportunities(user_id=user_id)
        return {
            "count": len(results),
            "top_picks": results,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Scout weekly error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate scout picks")

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
        # SECURITY: Do not leak exception details
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/tasks/iv/daily-refresh", deprecated=True)
def iv_daily_refresh_task_deprecated(
    x_cron_secret: str = Header(None, alias="X-Cron-Secret")
):
    raise HTTPException(status_code=410, detail="Endpoint moved to /internal/tasks/...")

# --- Rebalance Engine Endpoints (Step 3) ---

@app.post("/rebalance/execute")
@limiter.limit("5/minute")
async def execute_rebalance(
    request: Request,
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

    # Convert to SpreadPosition for engine compatibility
    # Assuming Spread and SpreadPosition are similar enough or we adapt
    spread_positions = []
    for s in current_spreads:
        # map fields
        sp = SpreadPosition(
            id=s.id,
            user_id=user_id,
            spread_type=s.spread_type,
            underlying=s.underlying,
            ticker=s.ticker,
            legs=[l.dict() for l in s.legs],
            net_cost=s.net_cost,
            current_value=s.current_value,
            delta=s.delta or 0.0,
            gamma=s.gamma or 0.0,
            vega=s.vega or 0.0,
            theta=s.theta or 0.0,
            quantity=s.quantity
        )
        spread_positions.append(sp)

    # Calculate Cash
    cash = 0.0
    for p in raw_positions:
        sym = p.get("symbol", "").upper()
        if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
             val = p.get("current_value", 0)
             if val == 0:
                 val = float(p.get("quantity", 0)) * float(p.get("current_price", 1.0))
             cash += val

    # Instantiate RiskBudgetEngine
    risk_budget_engine = RiskBudgetEngine()
    total_equity = sum(s.current_value for s in spread_positions) + cash
    risk_summary = risk_budget_engine.compute(spread_positions, total_equity)

    # 3. Run Optimizer directly to get targets
    from packages.quantum.optimizer import _compute_portfolio_weights, OptimizationRequest, calculate_dynamic_target

    # --- V3: Regime Engine Integration ---
    # Instantiate services
    market_data = PolygonService() # Keep for safety if used elsewhere
    truth_layer = MarketDataTruthLayer()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

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

    positions_for_conviction: List[PositionDescriptor] = []

    # Pre-fetch regime snapshots for portfolio symbols if needed, or compute on fly.
    # RegimeEngine V3 usually works per symbol.

    for spread in current_spreads:
        # Compute Symbol Snapshot via Regime Engine
        sym_snap = regime_engine.compute_symbol_snapshot(spread.ticker, global_snap)

        iv_rank = sym_snap.iv_rank # This is authoritative now

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
        "trace_id": None # Will be filled by optimizer
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

    # Pre-calculate symbol regimes to pass to thread
    symbol_regime_map = {}
    for t in tickers:
        s_snap = regime_engine.compute_symbol_snapshot(t, global_snap)
        eff = regime_engine.get_effective_regime(s_snap, global_snap)
        symbol_regime_map[t] = eff.value

    # Get Prices for engine
    # In real app, optimizer uses prices from market_data.
    # We can fetch or mock.
    # For now, simplistic:
    pricing_data = {t: 100.0 for t in tickers} # Placeholder if not in market_data
    # Or rely on what optimizer used if we can extract it.
    # Actually, current_spreads have values, but we need per-unit price for sizing.
    for s in current_spreads:
        # Approximate price per unit
        if s.quantity and s.current_value:
             pricing_data[s.ticker] = s.current_value / s.quantity
        else:
             pricing_data[s.ticker] = 100.0


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

             targets = {}
             target_list = []
             for sym, w in target_weights.items():
                 spread_obj = spread_map.get(sym)
                 strat_type = spread_obj.spread_type if spread_obj else "other"

                 # Use symbol-specific regime from V3
                 regime_key_sym = symbol_regime_map.get(sym, global_snap.state.value)

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
                     regime=regime_key_sym, # V3 Effective Regime
                     conviction=conviction_used
                 )

                 targets[sym] = adjusted_w

                 target_list.append({
                     "type": "spread",
                     "symbol": sym,
                     "target_allocation": adjusted_w
                 })

             # Return global regime value for logging/consistency
             return targets, trace_id, red_flags, global_snap.state.value

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Offload heavy compute to thread
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            targets_dict, trace_id, red_flags, regime_val = await loop.run_in_executor(pool, run_optimizer_logic)
        except Exception as e:
             print(f"Rebalance optimization error: {e}")
             # SECURITY: Do not leak exception details
             raise HTTPException(status_code=500, detail="Optimization failed")

    # 4. Generate Trades
    engine = RebalanceEngine(
        conviction_service=conviction_service,
        iv_regime_service=iv_point_service
    )

    # Enrich market context with trace ID
    regime_context["trace_id"] = trace_id

    trades = engine.generate_trades(
        spread_positions,
        targets_dict,
        total_equity,
        cash,
        pricing_data,
        market_context=regime_context,
        risk_summary=risk_summary
    )

    # 5. Save to DB with v3 Traceability
    saved_count = 0
    if trades:
        supabase.table(TRADE_SUGGESTIONS_TABLE).delete().eq("user_id", user_id).eq("window", "rebalance").execute()

        db_rows = []
        for t in trades:
            sym = t["ticker"] # Use ticker from trade dict
            strategy = t.get("type", "custom") # rebalance_buy etc

            # Create Trace Context
            features_dict = {
                "symbol": sym,
                "target_allocation": 0, # Could pass actual target weight
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

            # context field might not exist in t, but we can add
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
                "direction": t["action"].title(),
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
                    "target_allocation": 0,
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

@app.post("/rebalance/preview")
@limiter.limit("5/minute")
async def preview_rebalance(
    request: Request,
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
    # group_spread_positions now returns SpreadPosition objects directly (No, it returns dicts, need convert)
    spreads_dicts = group_spread_positions(raw_positions)
    current_spreads = [Spread(**s) for s in spreads_dicts]

    # Convert to SpreadPosition for engine compatibility
    spread_positions = []
    for s in current_spreads:
        # map fields
        sp = SpreadPosition(
            id=s.id,
            user_id=user_id,
            spread_type=s.spread_type,
            underlying=s.underlying,
            ticker=s.ticker,
            legs=[l.dict() for l in s.legs],
            net_cost=s.net_cost,
            current_value=s.current_value,
            delta=s.delta or 0.0,
            gamma=s.gamma or 0.0,
            vega=s.vega or 0.0,
            theta=s.theta or 0.0,
            quantity=s.quantity
        )
        spread_positions.append(sp)

    # Calculate Cash
    cash = 0.0
    for p in raw_positions:
        sym = p.get("symbol", "").upper()
        if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
             val = p.get("current_value", 0)
             if val == 0:
                 val = float(p.get("quantity", 0)) * float(p.get("current_price", 1.0))
             cash += val

    # Instantiate RiskBudgetEngine
    risk_budget_engine = RiskBudgetEngine()
    total_equity = sum(s.current_value for s in spread_positions) + cash
    risk_summary = risk_budget_engine.compute(spread_positions, total_equity)

    # 3. Run Optimizer directly to get targets
    from packages.quantum.optimizer import _compute_portfolio_weights, OptimizationRequest, calculate_dynamic_target

    # --- V3: Regime Engine Integration (Preview Mode: Global Only for Speed) ---
    market_data = PolygonService() # Keep for safety if used elsewhere
    truth_layer = MarketDataTruthLayer()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

    now = datetime.now()
    global_snap = regime_engine.compute_global_snapshot(now) # Skip symbol snapshot for preview speed

    # Build positions for conviction service

    positions_for_conviction: List[PositionDescriptor] = []

    # We need IV rank for conviction. Since preview is "global only for speed",
    # we might skip full symbol snapshots if too slow, or just do it.
    # Rebalance preview should be reasonably accurate.

    for spread in current_spreads:
        # If we skip symbol snapshot, we lack IV rank.
        # But we need IV rank for conviction.
        # Let's do it properly even for preview, it's safer.
        sym_snap = regime_engine.compute_symbol_snapshot(spread.ticker, global_snap)
        iv_rank = sym_snap.iv_rank

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
        "trace_id": None
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

    # Pre-calculate symbol regimes to pass to thread
    symbol_regime_map = {}
    for t in tickers:
        s_snap = regime_engine.compute_symbol_snapshot(t, global_snap)
        eff = regime_engine.get_effective_regime(s_snap, global_snap)
        symbol_regime_map[t] = eff.value

    # Pricing data
    pricing_data = {t: 100.0 for t in tickers}
    for s in current_spreads:
        if s.quantity and s.current_value:
             pricing_data[s.ticker] = s.current_value / s.quantity
        else:
             pricing_data[s.ticker] = 100.0

    # Helper function for heavy compute
    def run_optimizer_logic_preview():
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
             targets = {}
             for sym, w in target_weights.items():
                 spread_obj = spread_map.get(sym)
                 strat_type = spread_obj.spread_type if spread_obj else "other"

                 regime_key_sym = symbol_regime_map.get(sym, global_snap.state.value)
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
                     regime=regime_key_sym,
                     conviction=conviction_used
                 )

                 targets[sym] = adjusted_w
             return targets, trace_id

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Offload heavy compute to thread
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        try:
            targets_dict, trace_id = await loop.run_in_executor(pool, run_optimizer_logic_preview)
        except Exception as e:
             print(f"Rebalance optimization error: {e}")
             return {"status": "error", "message": str(e), "trades": []}

    regime_context["trace_id"] = trace_id

    # 4. Generate Trades
    engine = RebalanceEngine(
        conviction_service=conviction_service,
        iv_regime_service=iv_point_service
    )
    trades = engine.generate_trades(
        spread_positions,
        targets_dict,
        total_equity,
        cash,
        pricing_data,
        market_context=regime_context,
        risk_summary=risk_summary
    )

    # 5. Return trades directly (Preview)
    # Map to UI friendly format same as stored ones
    ui_trades = []
    for t in trades:
        ui_trades.append({
            "ticker": t["ticker"],
            "strategy": t.get("type", "custom"),
            "direction": t.get("action", "Hold").title(),
            "order_json": t,
            "notes": t.get("reason", "")
        })

    return {
        "status": "ok",
        "count": len(ui_trades),
        "trades": ui_trades,
        "risk_summary": risk_summary # Optional debug info
    }
