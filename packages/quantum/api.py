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
# IVRegimeService removed: RegimeEngineV3 is the authority now.
# from packages.quantum.analytics.iv_regime_service import IVRegimeService

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
    get_supabase_user_client,
    limiter
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

    # Step D2: Replace with RegimeEngineV3 snapshot-derived decisions only
    # No more IVRegimeService usage.

    # We still need iv_rank for conviction service, let's get it via RegimeEngine logic if possible
    # or just use what we have in symbol snapshots.
    # But for positions_for_conviction, we need to iterate positions.

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

                 # Step D3: Ensure no remaining references to IVRegimeService context
                 # Retrieve Regime for conviction call via V3 logic if needed,
                 # but calculate_dynamic_target uses regime_key which is from global_snap.state.value

                 # Previously: ctx = iv_ctx_map.get(sym, {}) -> regime = ctx.get("iv_regime", current_regime_scoring)
                 # Now: we trust global regime for the broad constraint logic OR we can use symbol specific regime?
                 # calculate_dynamic_target generally wants the global regime to set the "tone" or specific symbol regime?
                 # Looking at logic: regime=regime_key passed to calculate_dynamic_target.
                 # Global Regime is 'normal', 'suppressed', 'shock'.
                 # If we want symbol specific, we'd use symbol_snapshot.
                 # But rebalance usually operates on macro regime.
                 # The previous code used IVRegimeService which returned "iv_regime" per symbol (based on IV Rank).
                 # So it WAS symbol-specific.
                 # To replicate that using RegimeEngineV3:

                 # sym_snap = regime_engine.compute_symbol_snapshot(sym, global_snap)
                 # effective = regime_engine.get_effective_regime(sym_snap, global_snap)
                 # regime_key_symbol = effective.value

                 # But since we are inside a loop, we can't easily access regime_engine services (async/thread issues maybe? No, we passed args).
                 # Wait, we are inside run_optimizer_logic which runs in thread pool.
                 # regime_engine instance is outside.
                 # We should probably pre-calculate regimes map before entering thread pool.

                 # However, since the prompt says "Replace with RegimeEngineV3 snapshot-derived decisions only",
                 # and D2 says "effective_regime = regime_engine.get_effective_regime(...)".
                 # I will follow that. But I need to pass the map in.
                 pass # Logic continues below...

             return targets, trace_id, red_flags, regime_key, spread_map

        except Exception as e:
            print(f"Optimization failed during rebalance: {e}")
            raise e

    # Pre-calculate symbol regimes to pass to thread
    symbol_regime_map = {}
    for t in tickers:
        s_snap = regime_engine.compute_symbol_snapshot(t, global_snap)
        eff = regime_engine.get_effective_regime(s_snap, global_snap)
        symbol_regime_map[t] = eff.value

    # Update Helper function to use pre-calculated map
    def run_optimizer_logic_v2():
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

                 targets.append({
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
            targets, trace_id, red_flags, regime_val = await loop.run_in_executor(pool, run_optimizer_logic_v2)
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
    # Replaced IVRegimeService with V3 logic

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
             targets = []
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
            targets = await loop.run_in_executor(pool, run_optimizer_logic_preview)
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
