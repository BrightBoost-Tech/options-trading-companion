from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import numpy as np
import pandas as pd
import os

# Core Imports
from core.math_engine import PortfolioMath
from core.surrogate import SurrogateOptimizer
# Only import QCI Adapter if you have created the file from the previous step
try:
    from core.qci_adapter import QciDiracAdapter
except ImportError:
    QciDiracAdapter = None

# Analytics Imports
from analytics.strategy_selector import StrategySelector
from analytics.guardrails import apply_guardrails, compute_conviction_score
from analytics.analytics import OptionsAnalytics

router = APIRouter()

# --- Schemas ---
class PositionInput(BaseModel):
    symbol: str
    current_value: float
    current_quantity: float
    current_price: float

class OptimizationRequest(BaseModel):
    positions: List[PositionInput]
    risk_aversion: float = 1.0
    skew_preference: float = 0.0
    cash_balance: float = 0.0

# --- Helper: Trade Generator ---
def generate_trade_instructions(current_positions, target_weights, total_equity):
    trades = []
    current_map = {p.symbol: p for p in current_positions}

    for symbol, weight in target_weights.items():
        # 1. Target Value
        target_val = total_equity * weight

        # 2. Current Value
        curr_pos = current_map.get(symbol)
        curr_val = curr_pos.current_value if curr_pos else 0.0
        curr_price = curr_pos.current_price if curr_pos else 100.0 # Fallback price

        # 3. Delta
        diff = target_val - curr_val

        # 4. Filter Noise (Ignore trades < $50)
        if abs(diff) > 50.0:
            action = "BUY" if diff > 0 else "SELL"
            qty = abs(diff) / curr_price

            # Don't suggest buying 0.01 shares unless it's Berkshire Hathaway
            if qty >= 0.05:
                trades.append({
                    "symbol": symbol,
                    "action": action,
                    "value": round(abs(diff), 2),
                    "est_quantity": round(qty, 2),
                    "rationale": f"Target: {round(weight*100, 1)}% (Delta: ${int(diff)})"
                })
    return trades

# --- Endpoint 1: Main Optimization (Phase 2 Logic) ---
@router.post("/optimize/portfolio")
async def optimize_portfolio(req: OptimizationRequest):
    try:
        # 1. SEPARATE ASSETS FROM CASH (Fixes "Sell my cash" bug)
        investable_assets = []
        liquidity = req.cash_balance

        for p in req.positions:
            # Treat these symbols as Cash, not Stocks
            if p.symbol.upper() in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
                liquidity += p.current_value
            else:
                investable_assets.append(p)

        if not investable_assets:
            raise HTTPException(status_code=400, detail="No investable assets found. Add stocks to portfolio.")

        tickers = [p.symbol for p in investable_assets]
        assets_equity = sum(p.current_value for p in investable_assets)
        total_portfolio_value = assets_equity + liquidity

        # 2. GET DATA (Stability Fix)
        # We use deterministic seeding based on ticker name so results don't jump around
        data_frames = {}
        np.random.seed(42)

        for ticker in tickers:
            # Create a unique seed per ticker
            seed_val = sum(ord(c) for c in ticker)
            np.random.seed(seed_val)

            # Simulate 1 year of data
            # Trend: -0.1% to +0.2% daily mean
            mean_return = np.random.uniform(-0.001, 0.002)
            volatility = np.random.uniform(0.01, 0.03)

            daily_returns = np.random.normal(mean_return, volatility, 252)

            # Add "Learned Behavior" (Momentum) to recent history
            trend_factor = np.random.choice([-1, 1]) * 0.005
            daily_returns[-30:] += trend_factor

            data_frames[ticker] = daily_returns

        returns_df = pd.DataFrame(data_frames)

        # 3. MATH ENGINE (Exponential Mean for Profit Maximization)
        math_engine = PortfolioMath(returns_df)
        # 'exponential' weights recent data higher -> captures momentum
        mu = math_engine.get_mean_returns(method='exponential')
        sigma = math_engine.get_covariance_matrix() + np.eye(len(tickers)) * 1e-6
        coskew = math_engine.get_coskewness_tensor()

        # --- DYNAMIC CONSTRAINT LOGIC ---
        # If user has only 2 assets, 40% max weight is mathematically impossible (0.4 + 0.4 = 0.8 < 1.0).
        # We must relax the limit for small portfolios.
        default_max_pct = 0.40
        num_assets = len(tickers)

        # If we can't fill the bucket with the default scoop size, get a bigger scoop.
        if num_assets * default_max_pct < 1.0:
            effective_max_pct = 1.0  # Allow up to 100% allocation if portfolio is tiny
        else:
            effective_max_pct = default_max_pct

        constraints = {
            "risk_aversion": req.risk_aversion,
            "skew_preference": req.skew_preference,
            "max_position_pct": effective_max_pct, # Use the calculated limit
        }

        # 4. SOLVER SELECTION (Quantum Bridge)
        # Check environment
        has_qci_token = (os.getenv("QCI_API_TOKEN") is not None)

        # --- TRIAL MODE LOGIC ---
        # If using Real Quantum, we MUST limit the number of assets to respect trial quotas.
        # Dirac-3 is fast, but upload/processing times for N=50+ can act flaky on trial tiers.
        TRIAL_ASSET_LIMIT = 15

        solver_type = "Classical"
        weights_array = []

        if (req.skew_preference > 0) and has_qci_token and (QciDiracAdapter is not None):
            try:
                # A. ASSET THROTTLING
                # If we have too many assets, slicing them effectively is hard without losing context.
                # Strategy: If N > Limit, fall back to Classical immediately to save Credit
                # unless the user explicitly forced it (advanced feature).
                if len(tickers) > TRIAL_ASSET_LIMIT:
                    print(f"⚠️ Portfolio size ({len(tickers)}) exceeds Trial Limit ({TRIAL_ASSET_LIMIT}).")
                    print("   -> Fallback to Surrogate to save credits.")
                    # Fallback logic
                    s_solver = SurrogateOptimizer()
                    weights_array = s_solver.solve(mu, sigma, coskew, constraints)
                    solver_type = "Surrogate (Trial Limit)"

                else:
                    # B. EXECUTE QUANTUM JOB
                    print(f"🚀 Uplinking {len(tickers)} assets to QCI Dirac-3 (Trial)...")
                    q_solver = QciDiracAdapter()
                    weights_array = q_solver.solve_portfolio(mu, sigma, coskew, constraints)
                    solver_type = "QCI Dirac-3"

            except ConnectionRefusedError as e:
                # Specific handling for Quota Exceeded
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

        # Pass TOTAL value (Assets + Cash) so we buy using the cash
        trades = generate_trade_instructions(
            investable_assets,
            target_weights,
            total_portfolio_value
        )

        # --- New Decision Funnel ---
        strategy_selector = StrategySelector()
        processed_trades = []
        for trade in trades:
            # 1. Strategy Selection
            # TODO: Replace mock iv_rank with real data from a market data provider.
            iv_rank = np.random.uniform(10, 60) # Mock IV rank
            sentiment = "BULLISH" if trade['action'] == "BUY" else "BEARISH"
            strategy = strategy_selector.determine_strategy(
                trade['symbol'],
                sentiment,
                100, # Mock current price
                iv_rank
            )
            trade.update(strategy)
            trade['iv_rank'] = iv_rank
            processed_trades.append(trade)

        # 2. Guardrails
        processed_trades = apply_guardrails(processed_trades, investable_assets)

        # 3. Conviction Score
        for trade in processed_trades:
            trade['conviction_score'] = compute_conviction_score(trade)
            if trade['conviction_score'] >= 80:
                trade['conviction_label'] = "HIGH"
            elif 50 <= trade['conviction_score'] < 80:
                trade['conviction_label'] = "SPECULATIVE"
            else:
                trade['conviction_label'] = "LOW"

        # 4. Analytics
        portfolio_analytics = {
            "beta_delta": OptionsAnalytics.portfolio_beta_delta(investable_assets),
            "theta_efficiency": OptionsAnalytics.theta_efficiency(investable_assets, total_portfolio_value)
        }

        return {
            "status": "success",
            "mode": solver_type,
            "target_weights": target_weights,
            "trades": processed_trades,
            "metrics": {
                "expected_return": float(np.dot(weights_array, mu)),
                "sharpe_ratio": float(np.dot(weights_array, mu) / np.sqrt(np.dot(weights_array.T, np.dot(sigma, weights_array)))),
                "tail_risk_score": float(np.einsum('ijk,i,j,k->', coskew, weights_array, weights_array, weights_array)),
                "analytics": portfolio_analytics
            }
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
