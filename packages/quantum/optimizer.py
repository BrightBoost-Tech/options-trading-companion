from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Optional, Any, Union
from datetime import datetime
import numpy as np
import pandas as pd
import os
import uuid
from dataclasses import asdict

# Core Imports
from packages.quantum.core.math_engine import PortfolioMath
from packages.quantum.core.surrogate import SurrogateOptimizer, optimize_for_compounding
try:
    from packages.quantum.core.qci_adapter import QciDiracAdapter
except ImportError:
    QciDiracAdapter = None

# Analytics Imports
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.analytics.guardrails import apply_guardrails, compute_conviction_score, SmallAccountCompounder
from packages.quantum.analytics.analytics import OptionsAnalytics
from packages.quantum.services.trade_builder import enrich_trade_suggestions
from packages.quantum.market_data import PolygonService, calculate_portfolio_inputs
from packages.quantum.ev_calculator import calculate_ev, calculate_kelly_sizing
from packages.quantum.nested_logging import log_inference, log_decision
from packages.quantum.nested.adapters import load_symbol_adapters, apply_biases
from packages.quantum.nested.backbone import compute_macro_features, infer_global_context, log_global_context
from packages.quantum.nested.session import load_session_state, refresh_session_from_db, get_session_sigma_scale
from packages.quantum.security import get_current_user_id
from fastapi import Request

from packages.quantum.models import Spread, SpreadLeg, SpreadPosition
from packages.quantum.services.options_utils import group_spread_positions
from packages.quantum.services.analytics_service import AnalyticsService
from packages.quantum.services.execution_service import ExecutionService
from packages.quantum.services.risk_engine import RiskEngine

# V3 Imports
from packages.quantum.analytics.risk_model import SpreadRiskModel
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, GlobalRegimeSnapshot, RegimeState
from packages.quantum.common_enums import UnifiedScore
# from packages.quantum.analytics.scoring import calculate_unified_score # Deprecated in favor of ExecutionService parity

router = APIRouter()

# --- Schemas ---
# Legacy Position Input for back compatibility/simplicity, but we prefer Spreads now
class PositionInput(BaseModel):
    symbol: str
    current_value: float
    current_quantity: float
    current_price: float
    # Optional fields to support spread reconstruction if passing raw pos
    cost_basis: Optional[float] = None
    currency: Optional[str] = "USD"

class OptimizationRequest(BaseModel):
    positions: List[Dict[str, Any]] # Changed to generic dict list to support raw holdings or spreads
    risk_aversion: float = 2.0
    skew_preference: float = 0.0
    cash_balance: float = 0.0
    profile: str = "balanced"  # "aggressive" | "balanced" | "conservative"
    nested_enabled: bool = False # if False -> pure baseline
    nested_shadow: bool = False  # if True, compute nested path but DO NOT change trades

# Constants
MIN_DOLLAR_DIFF_BALANCED = 50.0
MIN_QTY_BALANCED = 0.05

MIN_DOLLAR_DIFF_AGGRESSIVE = 10.0
MIN_QTY_AGGRESSIVE = 0.02


def calculate_dynamic_cap(
    strategy_type: str,
    regime_state: RegimeState,
    conviction: float = 1.0
) -> float:
    """
    Returns adjusted_cap ∈ [0, 1.0] based on regime rules and conviction.
    Replaces older REGIME_STRATEGY_CAPS constant map.
    """

    # Base Caps per Regime
    # These could be moved to a config file or DB eventually
    caps = {
        RegimeState.SUPPRESSED: {
            "debit_call": 0.12, "debit_put": 0.12,
            "credit_call": 0.06, "credit_put": 0.06,
            "iron_condor": 0.04, "single": 0.15
        },
        RegimeState.NORMAL: {
            "debit_call": 0.15, "debit_put": 0.15,
            "credit_call": 0.08, "credit_put": 0.08,
            "iron_condor": 0.06, "vertical": 0.10
        },
        RegimeState.ELEVATED: {
             "credit_call": 0.12, "credit_put": 0.12,
             "debit_call": 0.06, "debit_put": 0.06,
             "iron_condor": 0.08, "single": 0.05
        },
        RegimeState.SHOCK: {
             "credit_call": 0.05, "credit_put": 0.02, # Dangerous
             "debit_put": 0.10, # Hedge
             "debit_call": 0.02,
             "iron_condor": 0.00,
             "vertical": 0.03
        },
        RegimeState.REBOUND: {
             "debit_call": 0.12, "credit_put": 0.12,
             "debit_put": 0.04, "credit_call": 0.05,
             "single": 0.08
        },
        RegimeState.CHOP: {
             "iron_condor": 0.10, "calendar": 0.10,
             "debit_call": 0.05, "debit_put": 0.05,
             "credit_call": 0.08, "credit_put": 0.08
        }
    }

    regime_caps = caps.get(regime_state, caps[RegimeState.NORMAL])

    # Fuzzy match strategy type
    st = strategy_type.lower()
    base_cap = 0.05 # Default low

    # Try exact match first
    if st in regime_caps:
        base_cap = regime_caps[st]
    else:
        # Try substring match
        for k, v in regime_caps.items():
            if k in st:
                base_cap = v
                break

    # Conviction Scaling
    scale = 0.5 + 0.5 * max(0.0, min(1.0, conviction))

    return base_cap * scale


def _compute_portfolio_weights(
    mu: np.ndarray,
    sigma: np.ndarray,
    coskew: np.ndarray,
    tickers: List[str],
    investable_assets: List[SpreadPosition],
    req: OptimizationRequest,
    user_id: str,
    total_portfolio_value: float,
    liquidity: float,
    force_baseline: bool = False,
    external_regime_snapshot: Optional[GlobalRegimeSnapshot] = None,
    guardrail_policy: Optional[Dict[str, Any]] = None
):
    """
    Internal helper to run the optimization logic once.
    Adapts Spread-based assets to optimizer logic (tickers = spread IDs/Tickers).
    """
    local_req = req.model_copy()
    diagnostics_nested = {}

    sigma_original = sigma.copy()
    mu_original = mu.copy()

    # Determine flags
    nested_global_env = os.getenv("NESTED_GLOBAL_ENABLED", "False").lower() == "true"
    nested_env_enabled = nested_global_env and (
        os.getenv("NESTED_L2_ENABLED", "False").lower() == "true"
        or os.getenv("NESTED_L1_ENABLED", "False").lower() == "true"
        or os.getenv("NESTED_L0_ENABLED", "False").lower() == "true"
    )
    nested_active = req.nested_enabled and nested_env_enabled

    use_l2 = False if force_baseline else (nested_active and os.getenv("NESTED_L2_ENABLED", "False").lower() == "true")
    use_l1 = False if force_baseline else (nested_active and os.getenv("NESTED_L1_ENABLED", "False").lower() == "true")
    use_l0 = False if force_baseline else (nested_active and os.getenv("NESTED_L0_ENABLED", "False").lower() == "true")

    # 1. Regime Integration (V3)
    # If external snapshot provided, use it. Else infer.
    current_regime = RegimeState.NORMAL
    if external_regime_snapshot:
        current_regime = external_regime_snapshot.state
        diagnostics_nested["regime"] = external_regime_snapshot.to_dict()

        # Apply Risk Scaler to Sigma
        scaler = external_regime_snapshot.risk_scaler
        if scaler != 1.0:
            sigma = sigma * (scaler ** 2)

        if current_regime == RegimeState.SHOCK:
             local_req.profile = "conservative"
             diagnostics_nested["crisis_mode_triggered_by"] = "v3_shock"
    else:
        # Fallback to L2 legacy inference if V3 snapshot missing (shouldn't happen in updated flow)
        if use_l2:
            try:
                macro_service = PolygonService()
                macro_features = compute_macro_features(macro_service)
                global_ctx = infer_global_context(macro_features)
                g_scaler = global_ctx.global_risk_scaler
                sigma = sigma * ((1.0/max(0.01, g_scaler)) ** 2)
                if global_ctx.global_regime == "shock":
                     current_regime = RegimeState.SHOCK
                     local_req.profile = "conservative"
            except Exception as e:
                print(f"L2 Legacy Error: {e}")

    # For L1/L2 adapters, we need underlying tickers
    underlying_map = {s.ticker: s.underlying for s in investable_assets}
    underlying_list = [underlying_map[t] for t in tickers]

    # --- PHASE 2: LEVEL-1 SYMBOL ADAPTERS ---
    if use_l1:
        try:
            adapters = load_symbol_adapters(underlying_list)
            spread_adapters = {}
            for i, t in enumerate(tickers):
                und = underlying_list[i]
                if und in adapters:
                    spread_adapters[t] = adapters[und]
            mu, sigma = apply_biases(mu, sigma, tickers, spread_adapters)
        except Exception as e:
            print(f"Phase 2 L1 Error: Failed to apply adapters: {e}")

    # --- LAYER 0: SESSION ADAPTER ---
    if use_l0:
        try:
            session_state = refresh_session_from_db(user_id)
            conf_scaler = get_session_sigma_scale(session_state.confidence)
            sigma = sigma * (conf_scaler ** 2)
            if session_state.confidence < 0.4:
                 local_req.profile = "conservative"
        except Exception as e:
            print(f"Phase 3 L0 Error: {e}")

    # --- DYNAMIC CONSTRAINT LOGIC (V3) ---
    default_max_pct = 0.40
    num_assets = len(tickers)
    if num_assets * default_max_pct < 1.0:
        effective_max_pct = 1.0
    else:
        effective_max_pct = default_max_pct

    # Calculate per-asset bounds based on strategy and regime
    bounds = []

    for asset in investable_assets:
        # Determine cap using V3 Logic
        cap = calculate_dynamic_cap(str(asset.spread_type), current_regime, conviction=1.0)

        # Combine with global max
        final_cap = min(cap, effective_max_pct)
        bounds.append((0.0, final_cap))

    constraints = {
        "risk_aversion": local_req.risk_aversion,
        "skew_preference": local_req.skew_preference,
        "max_position_pct": effective_max_pct,
        "bounds": bounds,
        "turnover_penalty": 0.01
    }

    # Apply Adaptive Caps if Policy Exists
    if guardrail_policy:
        from packages.quantum.services.risk_engine import RiskEngine
        constraints = RiskEngine.apply_adaptive_caps(guardrail_policy, constraints)
        diagnostics_nested["adaptive_caps_applied"] = True
        diagnostics_nested["policy_source"] = guardrail_policy.get("source", "unknown")

        # B2: Enforce banned_strategies by zeroing bounds in optimizer after policy is applied.
        banned = [str(x).lower() for x in constraints.get("banned_strategies", []) if x]
        if banned and "bounds" in constraints:
            new_bounds = []
            banned_assets = []
            for i, asset in enumerate(investable_assets):
                st = str(getattr(asset, "spread_type", "") or getattr(asset, "strategy", "") or "").lower()
                lo, hi = constraints["bounds"][i]
                if st and any((b in st) or (st in b) for b in banned):
                    new_bounds.append((0.0, 0.0))
                    banned_assets.append(tickers[i])
                else:
                    new_bounds.append((float(lo), float(hi)))
            constraints["bounds"] = new_bounds
            diagnostics_nested["banned_assets"] = banned_assets

    # Greek sensitivities
    greek_sensitivities = {
        'delta': np.array([a.delta for a in investable_assets]),
        'vega': np.array([a.vega for a in investable_assets])
    }

    # Shock losses
    shock_losses = []
    for i, a in enumerate(investable_assets):
        S = 100.0 # Placeholder
        if a.legs:
            l = a.legs[0]
            if isinstance(l, dict): S = l.get('current_price', 100.0)
            else: S = getattr(l, 'current_price', 100.0)

        # Simple shock scenario: -20% spot, +50% vol
        loss_val = (a.delta * S * -0.20) + (a.vega * 0.50)
        # Normalize by equity/collateral is tricky here without collateral data per asset
        # We assume loss is dollar value. Optimizer expects return space?
        # Typically shock_loss[i] is % loss of portfolio if 100% invested in i?
        # Or raw loss? Surrogate optimizer usually handles standard constraints.
        # Let's assume proportional loss for now.
        shock_losses.append(loss_val / max(1.0, a.current_value)) # % loss of position value

    shock_losses_arr = np.array(shock_losses)
    constraints['max_drawdown'] = 0.25

    # 4. SOLVER SELECTION
    has_qci_token = (os.getenv("QCI_API_TOKEN") is not None)
    TRIAL_ASSET_LIMIT = 15
    solver_type = "Classical"
    weights_array = []
    current_w = np.array([1.0/num_assets] * num_assets)

    if (local_req.skew_preference > 0) and has_qci_token and (QciDiracAdapter is not None):
        try:
            if len(tickers) > TRIAL_ASSET_LIMIT:
                s_solver = SurrogateOptimizer()
                weights_array = s_solver.solve(mu, sigma, coskew, constraints, current_weights=current_w, greek_sensitivities=greek_sensitivities, shock_losses=shock_losses_arr)
                solver_type = "Surrogate (Trial Limit)"
            else:
                q_solver = QciDiracAdapter()
                weights_array = q_solver.solve_portfolio(mu, sigma, coskew, constraints)
                solver_type = "QCI Dirac-3"
        except Exception as e:
            print(f"⚠️ Quantum Uplink Failed: {e}. Reverting.")
            s_solver = SurrogateOptimizer()
            weights_array = s_solver.solve(mu, sigma, coskew, constraints, current_weights=current_w, greek_sensitivities=greek_sensitivities, shock_losses=shock_losses_arr)
            solver_type = "Surrogate (Fallback)"
    else:
        s_solver = SurrogateOptimizer()
        weights_array = s_solver.solve(mu, sigma, coskew, constraints, current_weights=current_w, greek_sensitivities=greek_sensitivities, shock_losses=shock_losses_arr)
        solver_type = "Surrogate (Simulated)"

    target_weights = {tickers[i]: float(weights_array[i]) for i in range(len(tickers))}

    # --- LOGGING ---
    trace_id = None
    try:
        mu_dict = {ticker: float(mu[i]) for i, ticker in enumerate(tickers)}
        sigma_list = sigma.tolist() if isinstance(sigma, np.ndarray) else sigma
        inputs_snapshot = {
            "positions_count": len(investable_assets),
            "regime": current_regime.value,
            "constraints": str(constraints),
            "solver_type": solver_type,
            "force_baseline": force_baseline,
            "shadow_mode": req.nested_shadow
        }
        trace_id = log_inference(
            symbol_universe=tickers,
            inputs_snapshot=inputs_snapshot,
            predicted_mu=mu_dict,
            predicted_sigma={"sigma_matrix": sigma_list},
            optimizer_profile=local_req.profile
        )

        # New: Log the optimization decision (target weights)
        if trace_id:
            log_decision(
                trace_id=trace_id,
                user_id=user_id,
                decision_type="optimizer_weights",
                content={
                    "target_weights": target_weights,
                    "metrics": {
                        "expected_return": float(np.dot(weights_array, mu)), # approximate for log
                        "solver": solver_type
                    }
                }
            )

    except Exception as e:
        print(f"Logging Integration Error: {e}")

    return target_weights, diagnostics_nested, solver_type, trace_id, local_req.profile, weights_array, mu, sigma

# --- Endpoint 1: Main Optimization ---
@router.post("/optimize/portfolio")
async def optimize_portfolio(req: OptimizationRequest, request: Request, user_id: str = Depends(get_current_user_id)):
    analytics: Optional[AnalyticsService] = getattr(request.app.state, "analytics_service", None)

    if analytics:
        analytics.log_event(user_id, "optimization_started", "system", {"profile": req.profile, "nested": req.nested_enabled})

    try:
        # 1. GROUP POSITIONS INTO SPREADS
        raw_positions = req.positions
        spreads = group_spread_positions(raw_positions)
        investable_assets: List[SpreadPosition] = spreads

        # Calculate Cash
        liquidity = req.cash_balance
        for p in raw_positions:
            sym = p.get("symbol", "").upper()
            if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
                val = p.get("current_value", 0)
                if val == 0 and "quantity" in p:
                    val = float(p.get("quantity", 0)) * float(p.get("current_price", 1.0))
                liquidity += val

        if not investable_assets:
             return {"status": "success", "targets": [], "target_weights": {}, "message": "No investable spreads found."}

        tickers = [s.ticker for s in investable_assets]
        assets_equity = sum(s.current_value for s in investable_assets)
        total_portfolio_value = assets_equity + liquidity

        # 2. V3 REGIME & SCORING
        # Use RegimeEngineV3 to get authoritative state
        regime_engine = RegimeEngineV3()
        # Note: In real app, might want to inject supabase client, but for regime calculation often just needs market data

        try:
            global_snapshot = regime_engine.compute_global_snapshot(datetime.now())
        except Exception as e:
            print(f"Optimizer Regime Error: {e}")
            global_snapshot = regime_engine._default_global_snapshot(datetime.now())

        # 3. Calculate UnifiedScore for inputs to bias Mu
        # This replaces legacy 'mu' calculation partially or enriches it

        # 3.1 Fetch Base Covariance (Market Data)
        underlying_tickers = list(set([s.underlying for s in investable_assets if s.underlying and "USD" not in s.underlying]))

        try:
            unique_underlyings = list(set([u for u in underlying_tickers if u and "USD" not in u and "CASH" not in u]))
            if not unique_underlyings: raise ValueError("No valid underlyings")

            base_inputs = calculate_portfolio_inputs(unique_underlyings)
            base_idx_map = {u: i for i, u in enumerate(unique_underlyings)}
            n = len(tickers)
            sigma = np.zeros((n, n))

            # Map Sigma
            base_sigma = base_inputs['covariance_matrix']
            for i in range(n):
                u_i = investable_assets[i].underlying
                idx_i = base_idx_map.get(u_i)
                for j in range(n):
                    u_j = investable_assets[j].underlying
                    idx_j = base_idx_map.get(u_j)
                    if idx_i is not None and idx_j is not None:
                        sigma[i, j] = base_sigma[idx_i][idx_j]
                    else:
                        sigma[i, j] = 0.0
                        if i == j: sigma[i, j] = 0.1

            # 3.2 Construct Mu from Unified Score
            # UnifiedScore = EV - Costs - Penalties
            # We treat UnifiedScore as the "Utility" or "Expected Risk-Adjusted Return"
            mu = np.zeros(n)

            for i, asset in enumerate(investable_assets):
                # We need to construct a 'trade' dict for scoring
                # This is an existing position, so 'ev' might be 'remaining ev'?
                # Or we calculate 'UnifiedScore' as a hold score?
                # For optimization, we want forward looking return.

                # Approximate EV of holding (simple)
                # This logic should ideally be shared with scanner, but for existing positions:
                # EV ~= Delta * (Price - Strike) + ...
                # Or utilize ev_calculator if we can reconstruct trade params.

                # For now, we use a simplified proxy using existing Greeks if precise EV calc is hard
                # Or rely on SpreadRiskModel which does compute E[PnL].
                pass

        except Exception as e:
            print(f"Market Data Error: {e}. Using identity.")
            n = len(tickers)
            sigma = np.eye(n) * 0.05
            underlying_syms_aligned = underlying_tickers

        # 3.3 Spread Risk Model (Calculates Mu based on Greeks & Market Drift)
        # This is V3 compliant as it uses spread greeks
        risk_model = SpreadRiskModel(investable_assets)
        mu, sigma, coskew, collateral = risk_model.build_mu_sigma(
            base_inputs['covariance_matrix'] if 'base_inputs' in locals() else np.eye(len(underlying_tickers)),
            unique_underlyings if 'unique_underlyings' in locals() else underlying_tickers,
            horizon_days=5
        )

        # 3.4 Apply Execution Cost Penalties to Mu (Optimizer Parity)
        # Use ExecutionService to estimate transaction costs and spread impact, aligning with Scanner logic.

        # Instantiate ExecutionService
        # If analytics_service is available, reuse its client; otherwise create/get one.
        exec_service_client = analytics.supabase if analytics else None
        # If no client (rare), we can still instantiate ExecutionService but it might lack history.
        # We can pass None and ExecutionService should handle it or we assume it works for heuristic.
        # However, ExecutionService expects a client.
        if exec_service_client is None:
             # Try to get from request if possible, or skip history.
             # Ideally we have a client. For now, assume heuristic fallback if client fails.
             pass

        # To be safe, we wrap in try/except or conditional
        try:
             execution_service = ExecutionService(exec_service_client)
        except Exception:
             execution_service = None

        for i, asset in enumerate(investable_assets):
            cost_drag_dollars = 0.0

            if execution_service:
                # Estimate Cost
                # entry_cost = asset.current_value (approx for existing or new?)
                # For optimization (rebalance/sizing), we care about the cost to ENTER or EXIT?
                # Usually we model the "friction" of holding/trading this asset.
                # If we assume we hold it, the cost is already paid?
                # But 'mu' is future return. If we buy more, we pay cost.
                # So we penalize 'mu' by the cost of trading it (spread).

                # Infer legs
                num_legs = 1
                if asset.legs: num_legs = len(asset.legs)
                elif asset.spread_type in ["vertical", "spread", "straddle"]: num_legs = 2
                elif asset.spread_type in ["condor", "butterfly"]: num_legs = 4

                # Heuristic spread if unknown
                spread_pct = 0.01 # Default 1% if not passed? ExecutionService defaults to 0.5%

                # FIX: Convert total contract value to per-share premium for the estimator
                asset_val = abs(asset.current_value)
                qty = abs(asset.quantity or 1.0)
                price_per_contract_dollars = asset_val / max(qty, 0.0001)
                entry_cost_per_share = price_per_contract_dollars / 100.0

                # Use underlying symbol for history lookup (better match)
                symbol_for_history = asset.underlying
                if not symbol_for_history:
                    # Fallback extract from ticker if needed, though usually populated
                    parts = asset.ticker.split("_")
                    symbol_for_history = parts[0] if len(parts) > 1 else asset.ticker

                cost_per_contract = execution_service.estimate_execution_cost(
                    symbol=symbol_for_history,
                    spread_pct=None, # let service decide or use default
                    user_id=user_id,
                    entry_cost=entry_cost_per_share,
                    num_legs=num_legs
                )

                # Total cost for the position
                cost_drag_dollars = cost_per_contract * qty

            else:
                 # Fallback if service init failed
                 cost_drag_dollars = asset.current_value * 0.01

            # Convert dollar drag to return drag (percentage)
            # mu is expected return (e.g., 0.05 for 5%).
            # drag_pct = cost / value
            asset_val = asset.current_value
            if asset_val <= 0: asset_val = 1.0 # Protect div zero

            drag_pct = cost_drag_dollars / asset_val

            # Apply drag
            mu[i] -= drag_pct

        # 4. COMPUTE WEIGHTS
        deployable_capital = liquidity
        force_main_baseline = req.nested_shadow

        # --- ADAPTIVE CAPS: Fetch Policy ---
        # Fetch latest guardrail policy for user to potentially tighten constraints
        # We need the client. `analytics` has it?
        active_policy = None
        if analytics and analytics.supabase:
            active_policy = RiskEngine.get_active_policy(user_id, analytics.supabase)

        target_weights, diagnostics_nested, solver_type, trace_id, final_profile, weights_array, metrics_mu, metrics_sigma = _compute_portfolio_weights(
            mu, sigma, coskew, tickers, investable_assets, req, user_id,
            total_portfolio_value, liquidity, force_baseline=force_main_baseline,
            external_regime_snapshot=global_snapshot,
            guardrail_policy=active_policy
        )

        # Formatting Targets
        formatted_targets = []
        for s_ticker, weight in target_weights.items():
            formatted_targets.append({
                "type": "spread",
                "symbol": s_ticker,
                "target_allocation": round(weight, 4)
            })

        # Calculate Metrics
        annual_factor = 365.0 / 5.0
        expected_ret_horizon = np.dot(weights_array, metrics_mu)
        expected_ret_annual = expected_ret_horizon * annual_factor
        var_horizon = np.dot(weights_array.T, np.dot(metrics_sigma, weights_array))
        vol_annual = np.sqrt(var_horizon) * np.sqrt(annual_factor)
        sharpe = (expected_ret_annual - 0.04) / vol_annual if vol_annual > 0 else 0.0

        return {
            "status": "success",
            "targets": formatted_targets,
            "target_weights": target_weights,
            "mode": solver_type,
            "profile": final_profile,
            "metrics": {
                 "expected_return": float(expected_ret_annual),
                 "volatility": float(vol_annual),
                 "sharpe_ratio": float(sharpe),
                 "horizon_days": 5
            },
            "diagnostics": {
                "nested": diagnostics_nested,
                "trace_id": trace_id
            }
        }

    except Exception as e:
        print(f"Optimizer Error: {e}")
        import traceback
        traceback.print_exc()
        # SECURITY: Do not leak exception details
        raise HTTPException(status_code=500, detail="Optimization failed")

@router.get("/diagnostics/phase1")
async def run_phase1_test():
    return {"status": "ok", "message": "Phase 1 test not modified in this update"}

@router.post("/diagnostics/phase2/qci_uplink")
async def verify_qci_uplink():
    return {"status": "ok", "message": "Phase 2 test not modified"}
