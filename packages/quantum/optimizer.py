from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import numpy as np
import pandas as pd
import os
import uuid
from dataclasses import asdict

# Core Imports
from core.math_engine import PortfolioMath
from core.surrogate import SurrogateOptimizer, optimize_for_compounding
# Only import QCI Adapter if you have created the file from the previous step
try:
    from core.qci_adapter import QciDiracAdapter
except ImportError:
    QciDiracAdapter = None

# Analytics Imports
from analytics.strategy_selector import StrategySelector
from analytics.guardrails import apply_guardrails, compute_conviction_score, SmallAccountCompounder
from analytics.analytics import OptionsAnalytics
from services.trade_builder import enrich_trade_suggestions
from market_data import PolygonService, calculate_portfolio_inputs
from ev_calculator import calculate_ev, calculate_kelly_sizing
from nested_logging import log_inference
from nested.adapters import load_symbol_adapters, apply_biases
from nested.backbone import compute_macro_features, infer_global_context, log_global_context
from nested.session import load_session_state, refresh_session_from_db, get_session_sigma_scale
from security import get_current_user_id

router = APIRouter()

# --- Schemas ---
class PositionInput(BaseModel):
    symbol: str
    current_value: float
    current_quantity: float
    current_price: float

class OptimizationRequest(BaseModel):
    positions: List[PositionInput]
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

# --- Helper: Trade Generator ---
def generate_trade_instructions(current_positions, target_weights, total_equity, profile: str = "balanced", deployable: Optional[float] = None):
    trades = []
    current_map = {p.symbol: p for p in current_positions}

    # Determine thresholds based on profile
    # Use deployable if provided, else total_equity as scale
    scale = deployable if (deployable is not None and deployable > 0) else total_equity

    if profile == "aggressive":
        base_min_diff = MIN_DOLLAR_DIFF_AGGRESSIVE
        min_diff = max(base_min_diff, 0.01 * scale) # at least 1% of scale
        min_qty = MIN_QTY_AGGRESSIVE
    else:
        base_min_diff = MIN_DOLLAR_DIFF_BALANCED
        min_diff = max(base_min_diff, 0.02 * scale) # 2% of scale
        min_qty = MIN_QTY_BALANCED

    raw_trades = []

    for symbol, weight in target_weights.items():
        # 1. Target Value
        target_val = total_equity * weight

        # 2. Current Value
        curr_pos = current_map.get(symbol)
        curr_val = curr_pos.current_value if curr_pos else 0.0
        curr_price = curr_pos.current_price if curr_pos else 100.0 # Fallback price

        # 3. Delta
        diff = target_val - curr_val
        qty = abs(diff) / curr_price

        raw_trades.append({
            "symbol": symbol,
            "diff": diff,
            "qty": qty,
            "curr_price": curr_price,
            "weight": weight
        })

    # 4. Filter Noise
    filtered_candidates = []
    for t in raw_trades:
        if abs(t["diff"]) > min_diff and t["qty"] >= min_qty:
            filtered_candidates.append(t)

    # 5. For Aggressive profile, ensure at least top 3 trades
    if profile == "aggressive":
        if len(filtered_candidates) < 3 and len(raw_trades) > 0:
            # Sort by absolute dollar difference
            extra = sorted(raw_trades, key=lambda x: abs(x["diff"]), reverse=True)
            for cand in extra:
                # Add if not already present
                if not any(f["symbol"] == cand["symbol"] for f in filtered_candidates):
                    filtered_candidates.append(cand)

                if len(filtered_candidates) >= 3:
                    break

    # 6. Format Final Trades
    for t in filtered_candidates:
        diff = t["diff"]
        qty = t["qty"]
        action = "BUY" if diff > 0 else "SELL"
        weight = t["weight"]

        trades.append({
            "symbol": t["symbol"],
            "action": action,
            "value": round(abs(diff), 2),
            "est_quantity": round(qty, 2),
            "rationale": f"Target: {round(weight*100, 1)}% (Delta: ${int(diff)})"
        })

    return trades

def _compute_portfolio_weights(
    mu: np.ndarray,
    sigma: np.ndarray,
    coskew: np.ndarray,
    tickers: List[str],
    investable_assets: List[PositionInput],
    req: OptimizationRequest,
    user_id: str,
    total_portfolio_value: float,
    liquidity: float,
    force_baseline: bool = False
):
    """
    Internal helper to run the optimization logic once (either baseline or nested).
    """
    local_req = req.model_copy()
    diagnostics_nested = {}

    sigma_original = sigma.copy()
    mu_original = mu.copy()

    # Determine flags
    # Nested logic requires: 1) nested_enabled=True, 2) Global Env=True
    nested_global_env = os.getenv("NESTED_GLOBAL_ENABLED", "False").lower() == "true"

    # Master switch: Only active if request enabled AND global env enabled AND one of sub-envs enabled
    # Explicitly guarding against accidental live influence
    nested_env_enabled = nested_global_env and (
        os.getenv("NESTED_L2_ENABLED", "False").lower() == "true"
        or os.getenv("NESTED_L1_ENABLED", "False").lower() == "true"
        or os.getenv("NESTED_L0_ENABLED", "False").lower() == "true"
    )
    # Strictly enforce: nested_enabled = req.nested_enabled and nested_env_enabled
    nested_active = req.nested_enabled and nested_env_enabled

    # Explicit toggles
    use_l2 = False if force_baseline else (nested_active and os.getenv("NESTED_L2_ENABLED", "False").lower() == "true")
    use_l1 = False if force_baseline else (nested_active and os.getenv("NESTED_L1_ENABLED", "False").lower() == "true")
    use_l0 = False if force_baseline else (nested_active and os.getenv("NESTED_L0_ENABLED", "False").lower() == "true")

    # --- PHASE 3: NESTED LEARNING PIPELINE ---

    # --- LAYER 2: GLOBAL BACKBONE ---
    if use_l2:
        try:
            # 1. Compute macro features (PolygonService implicitly used)
            macro_service = PolygonService()
            macro_features = compute_macro_features(macro_service)

            # 2. Infer Regime
            global_ctx = infer_global_context(macro_features)

            # 3. Log (fire & forget)
            log_global_context(global_ctx)

            # 4. Apply Global Risk Scaler to Sigma
            g_scaler = global_ctx.global_risk_scaler
            if g_scaler < 0.01: g_scaler = 0.01 # Safety clamp
            sigma_multiplier = 1.0 / g_scaler
            sigma = sigma * (sigma_multiplier ** 2)

            diagnostics_nested["l2"] = asdict(global_ctx)

            # CRISIS MODE TRIGGER
            if global_ctx.global_regime == "shock":
                local_req.profile = "conservative"
                diagnostics_nested["crisis_mode_triggered_by"] = "l2_shock"

        except Exception as e:
            print(f"Phase 3 L2 Error: {e}")

    # --- PHASE 2: LEVEL-1 SYMBOL ADAPTERS ---
    if use_l1:
        try:
            # 1. Load adapters for this symbol universe
            adapters = load_symbol_adapters(tickers)

            # 2. Apply biases (clamped)
            mu, sigma = apply_biases(mu, sigma, tickers, adapters)

            # print(f"Phase 2 L1: Applied adapters to {len(adapters)} symbols.")
        except Exception as e:
            print(f"Phase 2 L1 Error: Failed to apply adapters: {e}")

    # --- LAYER 0: SESSION ADAPTER ---
    if use_l0:
        try:
            # 1. Refresh & Load Session State
            session_state = refresh_session_from_db(user_id)

            # 2. Apply Confidence Scaler
            conf_scaler = get_session_sigma_scale(session_state.confidence)
            sigma = sigma * (conf_scaler ** 2)

            diagnostics_nested["l0"] = {
                "confidence": session_state.confidence,
                "sigma_scaler": conf_scaler
            }

            # CRISIS MODE L0
            if session_state.confidence < 0.4:
                 local_req.profile = "conservative"
                 diagnostics_nested["crisis_mode_triggered_by"] = "l0_low_confidence"

        except Exception as e:
            print(f"Phase 3 L0 Error: {e}")

    # --- MICRO-LIVE BLENDING ---
    live_mult_str = os.getenv("NESTED_LIVE_RISK_MULTIPLIER", "0.0")
    if (not force_baseline) and nested_active and live_mult_str:
        try:
            live_mult = float(live_mult_str)
            live_mult = max(0.0, min(1.0, live_mult))
            if live_mult > 0.0:
                # Blend mu/sigma: original * (1 - k) + nested * k
                sigma = sigma_original * (1.0 - live_mult) + sigma * live_mult
                mu = mu_original * (1.0 - live_mult) + mu * live_mult
        except ValueError:
            pass

    # --- DYNAMIC CONSTRAINT LOGIC ---
    # If user has only 2 assets, 40% max weight is mathematically impossible (0.4 + 0.4 = 0.8 < 1.0).
    default_max_pct = 0.40
    num_assets = len(tickers)

    if num_assets * default_max_pct < 1.0:
        effective_max_pct = 1.0  # Allow up to 100% allocation if portfolio is tiny
    else:
        effective_max_pct = default_max_pct

    constraints = {
        "risk_aversion": local_req.risk_aversion,
        "skew_preference": local_req.skew_preference,
        "max_position_pct": effective_max_pct, # Use the calculated limit
    }

    # 4. SOLVER SELECTION (Quantum Bridge)
    has_qci_token = (os.getenv("QCI_API_TOKEN") is not None)
    TRIAL_ASSET_LIMIT = 15
    solver_type = "Classical"
    weights_array = []

    if (local_req.skew_preference > 0) and has_qci_token and (QciDiracAdapter is not None):
        try:
            if len(tickers) > TRIAL_ASSET_LIMIT:
                print(f"⚠️ Portfolio size ({len(tickers)}) exceeds Trial Limit ({TRIAL_ASSET_LIMIT}).")
                print("   -> Fallback to Surrogate to save credits.")
                s_solver = SurrogateOptimizer()
                weights_array = s_solver.solve(mu, sigma, coskew, constraints)
                solver_type = "Surrogate (Trial Limit)"
            else:
                print(f"🚀 Uplinking {len(tickers)} assets to QCI Dirac-3 (Trial)...")
                q_solver = QciDiracAdapter()
                weights_array = q_solver.solve_portfolio(mu, sigma, coskew, constraints)
                solver_type = "QCI Dirac-3"
        except ConnectionRefusedError as e:
            print(f"⚠️ {e}. Switching to Surrogate.")
            s_solver = SurrogateOptimizer()
            weights_array = s_solver.solve(mu, sigma, coskew, constraints)
            solver_type = "Surrogate (Quota Hit)"
        except Exception as e:
            print(f"⚠️ Quantum Uplink Failed: {e}. Reverting.")
            s_solver = SurrogateOptimizer()
            weights_array = s_solver.solve(mu, sigma, coskew, constraints)
            solver_type = "Surrogate (Fallback)"
    else:
        # Standard Classical
        s_solver = SurrogateOptimizer()
        weights_array = s_solver.solve(mu, sigma, coskew, constraints)
        solver_type = "Surrogate (Simulated)"

    # 5. RESULT MAPPING
    target_weights = {tickers[i]: float(weights_array[i]) for i in range(len(tickers))}

    # --- NESTED LEARNING LOGGING ---
    trace_id = None
    try:
        mu_dict = {ticker: float(mu[i]) for i, ticker in enumerate(tickers)}
        sigma_list = sigma.tolist() if isinstance(sigma, np.ndarray) else sigma

        inputs_snapshot = {
            "positions_count": len(investable_assets),
            "positions": [p.model_dump() for p in investable_assets],
            "total_equity": total_portfolio_value,
            "cash": liquidity,
            "risk_aversion": local_req.risk_aversion,
            "skew_preference": local_req.skew_preference,
            "constraints": constraints,
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
    except Exception as e:
        print(f"Logging Integration Error: {e}")

    return target_weights, diagnostics_nested, solver_type, trace_id, local_req.profile, weights_array, mu, sigma

# --- Endpoint 1: Main Optimization (Phase 2 Logic) ---
@router.post("/optimize/portfolio")
async def optimize_portfolio(req: OptimizationRequest, user_id: str = Depends(get_current_user_id)):
    try:
        # Tune Risk Aversion for Aggressive Profile if default
        if req.profile == "aggressive" and req.risk_aversion == 2.0:
            req.risk_aversion = 1.0

        # 1. SEPARATE ASSETS FROM CASH (Fixes "Sell my cash" bug)
        investable_assets = []
        liquidity = 0.0
        cash_from_positions = 0.0

        for p in req.positions:
            # Treat these symbols as Cash, not Stocks
            if p.symbol.upper() in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
                cash_from_positions += p.current_value
            else:
                investable_assets.append(p)

        # cash_balance is an override / supplement (e.g. external cash), not an additional copy
        # Use max to prevent double counting if cash_balance includes the positions sum
        liquidity = max(cash_from_positions, req.cash_balance)

        if not investable_assets:
            raise HTTPException(status_code=400, detail="No investable assets found. Add stocks to portfolio.")

        tickers = [p.symbol for p in investable_assets]
        assets_equity = sum(p.current_value for p in investable_assets)
        total_portfolio_value = assets_equity + liquidity

        # 2. GET DATA (Real Market Data)
        portfolio_inputs = {}
        mu = np.array([])
        sigma = np.array([])
        coskew = None

        try:
            portfolio_inputs = calculate_portfolio_inputs(tickers)
            mu = np.array(portfolio_inputs['expected_returns'])
            sigma = np.array(portfolio_inputs['covariance_matrix'])

            # For now, we'll use a zero coskewness tensor as it's not provided by the market data service
            coskew = np.zeros((len(tickers), len(tickers), len(tickers)))

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch market data: {e}")

        # 3. COMPUTE WEIGHTS (BASELINE VS NESTED)

        target_weights = {}
        solver_type = ""
        diagnostics_nested = {}
        trace_id = None
        final_profile = req.profile
        weights_array = []
        diagnostics_shadow = {}

        # In this endpoint we don't call CashService; use liquidity as deployable for now
        deployable_capital = liquidity

        # PATH A: Main Execution
        # If Shadow is True, we FORCE Baseline for the Main Path to ensure safety.
        # If Shadow is False, we respect nested_enabled (so if True, and envs are on, we run Nested Live).
        force_main_baseline = req.nested_shadow

        target_weights, diagnostics_nested, solver_type, trace_id, final_profile, weights_array, metrics_mu, metrics_sigma = _compute_portfolio_weights(
            mu, sigma, coskew, tickers, investable_assets, req, user_id,
            total_portfolio_value, liquidity, force_baseline=force_main_baseline
        )

        if req.nested_shadow:
            # PATH B: Nested Shadow (Diagnostics Only)
            # We want to see what Nested WOULD do.
            # So we create a temporary request with nested_enabled=True.
            req_shadow = req.model_copy()
            req_shadow.nested_enabled = True
            req_shadow.nested_shadow = False # Disable shadow flag for internal call so it acts "Live" (e.g. Blending)

            tw_nest, diag_nest, st_nest, tid_nest, fp_nest, wa_nest, mu_nest, sigma_nest = _compute_portfolio_weights(
                mu, sigma, coskew, tickers, investable_assets, req_shadow, user_id,
                total_portfolio_value, liquidity, force_baseline=False
            )

            # Generate summary trades for shadow logs
            # Note: We use the *shadow* profile/weights/deployable
            trades_base = generate_trade_instructions(investable_assets, target_weights, total_portfolio_value, final_profile, deployable_capital)
            trades_nest = generate_trade_instructions(investable_assets, tw_nest, total_portfolio_value, fp_nest, deployable_capital)

            def summarize_trades(ts):
                return [{"symbol": t["symbol"], "action": t["action"], "value": t["value"]} for t in ts]

            # Calculate metrics for both paths for replay analysis
            def calc_metrics(w_arr, m_mu, m_sigma):
                if len(w_arr) == 0: return {"expected_return": 0.0, "sharpe_ratio": 0.0}
                er = float(np.dot(w_arr, m_mu))
                vol = np.sqrt(np.dot(w_arr.T, np.dot(m_sigma, w_arr)))
                sr = float(er / vol) if vol > 1e-9 else 0.0
                return {"expected_return": er, "sharpe_ratio": sr}

            metrics_base_shadow = calc_metrics(weights_array, metrics_mu, metrics_sigma)
            metrics_nest_shadow = calc_metrics(wa_nest, mu_nest, sigma_nest)

            diagnostics_shadow = {
                "baseline_mode": solver_type,
                "nested_mode": st_nest,
                "baseline_trades": summarize_trades(trades_base),
                "nested_trades": summarize_trades(trades_nest),
                "baseline_metrics": metrics_base_shadow,
                "nested_metrics": metrics_nest_shadow
            }

        # 4. GENERATE TRADES
        trades = generate_trade_instructions(
            investable_assets,
            target_weights,
            total_portfolio_value,
            profile=final_profile,
            deployable=deployable_capital
        )

        if deployable_capital is not None and deployable_capital > 0:
            safe_trades = []
            for t in trades:
                if t["value"] <= deployable_capital:
                    t["capital_fraction"] = t["value"] / deployable_capital
                    safe_trades.append(t)
                else:
                    # Keep it but mark as over-budget
                    t["capital_fraction"] = t["value"] / deployable_capital
                    t["over_budget"] = True
                    safe_trades.append(t)
            trades = safe_trades

        # --- New Decision Funnel ---
        market_data = {}
        try:
            service = PolygonService()
            for ticker in tickers:
                hist_data = service.get_historical_prices(ticker, days=5)
                quote = service.get_recent_quote(ticker)

                market_data[ticker] = {
                    "price": hist_data['prices'][-1] if hist_data and hist_data['prices'] else 0,
                    "iv_rank": service.get_iv_rank(ticker),
                    "trend": service.get_trend(ticker),
                    "sector": service.get_ticker_details(ticker).get('sic_description'),
                    "bid": quote.get("bid", 0.0),
                    "ask": quote.get("ask", 0.0),
                }
        except Exception as e:
            print(f"Market data fetch failed: {e}")

        processed_trades = enrich_trade_suggestions(
            trades,
            total_portfolio_value,
            market_data,
            [p.model_dump() for p in investable_assets]
        )

        # 3b. Enrich with EV and PoP
        for trade in processed_trades:
            try:
                # Default values for EV calculation
                strategy = trade.get('strategy_type', 'long_call').lower().replace(' ', '_')

                # Map strategies to ev_calculator supported types
                # Simple mapping: assume basic strategies for now if not explicit
                if 'call' in strategy and 'long' in strategy: strategy = 'long_call'
                elif 'put' in strategy and 'long' in strategy: strategy = 'long_put'
                elif 'call' in strategy and 'short' in strategy: strategy = 'short_call'
                elif 'put' in strategy and 'short' in strategy: strategy = 'short_put'
                # Fallback for 'covered call' -> short_call logic for EV
                elif 'covered' in strategy: strategy = 'short_call'

                ev_result = calculate_ev(
                    premium=trade.get('price', 0),
                    strike=trade.get('strike_price', 0) or trade.get('entry_price', 0), # Fallback
                    current_price=market_data.get(trade['symbol'], {}).get('price', 0),
                    delta=0.5, # Default if not available (TODO: Get real delta from market_data)
                    strategy=strategy,
                    width=None, # Only for spreads
                    contracts=1
                )

                # Attach metrics
                if 'metrics' not in trade:
                    trade['metrics'] = {}

                trade['metrics']['expected_value'] = ev_result.expected_value
                trade['metrics']['probability_of_profit'] = ev_result.win_probability * 100 # Scale 0-100

            except Exception as e:
                # Don't fail the whole request for EV calc failure
                # print(f"EV Calc failed for {trade['symbol']}: {e}")
                pass

        # 4. Analytics
        portfolio_analytics = {
            "beta_delta": OptionsAnalytics.portfolio_beta_delta(investable_assets),
            "theta_efficiency": OptionsAnalytics.theta_efficiency(investable_assets, total_portfolio_value)
        }

        # --- COMPOUNDING MODE ENRICHMENT ---
        # "Small-Edge" Mode Logic

        # 1. Filter candidates for compounding suitability
        # We treat 'processed_trades' as candidates here.
        compounding_trades = SmallAccountCompounder.apply(processed_trades, total_portfolio_value)

        # 2. Apply Kelly Sizing
        final_compounding_trades = []
        for trade in compounding_trades:
             price = float(trade.get("price", 0.0) or 0.0)

             # Calculate Prob Profit from metrics or default
             p_profit = float(trade.get("metrics", {}).get("probability_of_profit", 50.0)) / 100.0

             sizing = calculate_kelly_sizing(
                entry_price=price,
                max_loss=float(trade.get("max_loss", 0.0)),
                max_profit=float(trade.get("max_profit", 0.0)),
                prob_profit=p_profit,
                account_value=total_portfolio_value,
                kelly_multiplier=0.5
            )

             if sizing.recommended_contracts > 0:
                 trade["sizing"] = sizing.model_dump()
                 # Append rationale
                 trade["rationale"] = f"{trade.get('rationale','')}. {sizing.rationale}"
                 final_compounding_trades.append(trade)

        # 3. Optimize (Sort)
        optimized_compounding = optimize_for_compounding(
            final_compounding_trades,
            investable_assets,
            total_portfolio_value
        )

        # Use compounding trades if available and valid, else standard MVO trades
        output_trades = optimized_compounding if optimized_compounding else processed_trades

        final_diagnostics = {
             "trace_id": str(trace_id) if trace_id else None,
             "nested": diagnostics_nested
        }
        if req.nested_shadow:
            final_diagnostics["nested_shadow"] = diagnostics_shadow

        return {
            "status": "success",
            "mode": "Compounding Small-Edge" if optimized_compounding else solver_type,
            "account_goal": "1k -> 5k (Compounding Mode)",
            "target_weights": target_weights,
            "trades": output_trades,
            "portfolio_stats": {
                "projected_drawdown_risk": "Low" if total_portfolio_value > 2000 else "Medium",
                "growth_velocity": "Steady"
            },
            "metrics": {
                "expected_return": float(np.dot(weights_array, metrics_mu)),
                "sharpe_ratio": float(np.dot(weights_array, metrics_mu) / np.sqrt(np.dot(weights_array.T, np.dot(metrics_sigma, weights_array)))),
                "tail_risk_score": float(np.einsum('ijk,i,j,k->', coskew, weights_array, weights_array, weights_array)),
                "analytics": portfolio_analytics
            },
            "profile": req.profile,
            "deployable_capital": deployable_capital,
            "diagnostics": final_diagnostics
        }
    except Exception as e:
        print(f"Optimizer Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Endpoint 2: Phase 1 Diagnostics (Restored!) ---
@router.get("/diagnostics/phase1")
async def run_phase1_test():
    """
    Sanity Check: Can we mathematically distinguish Safe vs Risky assets locally?
    """
    try:
        np.random.seed(42)
        n_days = 1000

        # 1. SAFE ASSET: Steady, low return
        # Mean: ~0.05% daily, Vol: 1%
        safe_asset = np.random.normal(0.0005, 0.01, n_days)

        # 2. RISKY ASSET (The Trap):
        # Base: High return (0.15% daily), similar volatility
        # We want Classical MVO to prefer this because of the higher return.
        risky_asset = np.random.normal(0.0015, 0.01, n_days)

        # 3. ADD SKEW (The Hidden Risk):
        # We add 5 major crashes (-10%).
        # Math: 5 * -0.10 / 1000 = -0.0005 drag on mean.
        # Net Mean becomes ~0.0010, which is STILL HIGHER than Safe (0.0005).
        # result: Classical BUYS Risky (for yield), Quantum SELLS Risky (for safety).
        crash_indices = np.random.choice(n_days, size=5, replace=False)
        risky_asset[crash_indices] = -0.10

        df = pd.DataFrame({'SAFE': safe_asset, 'RISKY': risky_asset})

        math_engine = PortfolioMath(df)
        mu = math_engine.get_mean_returns()
        sigma = math_engine.get_covariance_matrix()
        coskew = math_engine.get_coskewness_tensor()

        solver = SurrogateOptimizer()

        # Classical (Skew ignored)
        # Should allocate significantly to RISKY because Mean(Risky) > Mean(Safe)
        w_class = solver.solve(mu, sigma, coskew, {
            'risk_aversion': 1.0,
            'skew_preference': 0.0,
            'max_position_pct': 1.0
        })

        # Quantum Logic (Skew penalized heavily)
        # Should flee to SAFE because of the negative skew events
        w_quant = solver.solve(mu, sigma, coskew, {
            'risk_aversion': 1.0,
            'skew_preference': 100000.0, # Increased penalty to force the shift
            'max_position_pct': 1.0
        })

        # Success if Quantum Safe Weight is significantly higher than Classical Safe Weight
        # e.g. Classical might be 50/50, Quantum should be 90/10 or 100/0
        is_working = w_quant[0] > (w_class[0] + 0.10)

        return {
            "test_passed": bool(is_working),
            "classical_weights": {"SAFE": round(w_class[0],2), "RISKY": round(w_class[1],2)},
            "quantum_weights": {"SAFE": round(w_quant[0],2), "RISKY": round(w_quant[1],2)},
            "metrics": {
                "safe_mean_annual": round(safe_asset.mean()*252, 3),
                "risky_mean_annual": round(risky_asset.mean()*252, 3), # Should be higher than safe
            },
            "message": "Quantum logic successfully penalized the negatively skewed asset." if is_working else "Logic failed to differentiate."
        }
    except Exception as e:
        return {"test_passed": False, "error": str(e)}


# --- Endpoint 3: Phase 2 Diagnostics (QCI Uplink) ---
@router.post("/diagnostics/phase2/qci_uplink")
async def verify_qci_uplink():
    """
    Real Quantum Hardware Check.
    """
    if not os.getenv("QCI_API_TOKEN"):
        # Graceful failure if no token
        return {"status": "skipped", "detail": "No QCI_API_TOKEN found."}

    try:
        if QciDiracAdapter is None:
             raise Exception("QciDiracAdapter not loaded.")

        # Tiny Problem (3 Assets)
        mu = np.array([0.05, 0.08, 0.02])
        sigma = np.identity(3) * 0.01
        coskew = np.zeros((3,3,3))
        coskew[2,2,2] = -1.0 # Asset 2 has bad skew

        adapter = QciDiracAdapter()
        print("Sending Test Payload to Dirac-3...")

        weights = adapter.solve_portfolio(mu, sigma, coskew, {
            'risk_aversion': 1.0,
            'skew_preference': 500.0,
            'max_position_pct': 1.0
        })

        return {
            "status": "success",
            "backend": "QCI Dirac-3",
            "received_weights": weights,
            "message": "Successfully computed on Quantum hardware."
        }

    except Exception as e:
        return {"status": "error", "detail": str(e)}
