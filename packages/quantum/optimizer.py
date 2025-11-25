from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import numpy as np
import pandas as pd
from core.math_engine import PortfolioMath
from core.surrogate import SurrogateOptimizer

router = APIRouter()

# --- Schema Definition ---
class PositionInput(BaseModel):
    symbol: str
    current_value: float
    current_quantity: float
    current_price: float

class OptimizationRequest(BaseModel):
    positions: List[PositionInput] # Real holdings from Plaid
    risk_aversion: float = 1.0
    skew_preference: float = 0.0   # 0 = Classical, >0 = Quantum
    cash_balance: float = 0.0

# --- Helper: Trade Calculator ---
def generate_trade_instructions(current_positions, target_weights, total_equity):
    trades = []

    # Map current holdings for easy lookup
    current_map = {p.symbol: p for p in current_positions}

    for symbol, weight in target_weights.items():
        target_value = total_equity * weight

        # Get current state
        curr_pos = current_map.get(symbol)
        curr_val = curr_pos.current_value if curr_pos else 0.0
        curr_price = curr_pos.current_price if curr_pos else 100.0 # Fallback

        diff = target_value - curr_val

        # Filter noise (ignore trades < $10)
        if abs(diff) > 10.0:
            action = "BUY" if diff > 0 else "SELL"
            qty = abs(diff) / curr_price
            trades.append({
                "symbol": symbol,
                "action": action,
                "value": round(abs(diff), 2),
                "est_quantity": round(qty, 4),
                "rationale": f"Target alloc: {round(weight*100,1)}%"
            })

    return trades

# --- Endpoints ---

@router.post("/optimize/portfolio")
async def optimize_portfolio(req: OptimizationRequest):
    try:
        # 1. Extract Data
        tickers = [p.symbol for p in req.positions]
        total_equity = sum(p.current_value for p in req.positions) + req.cash_balance

        # 2. Mock Market Data (Replace with Polygon fetch in prod)
        # We generate slight skew for testing
        mock_returns = np.random.normal(0.001, 0.02, (252, len(tickers)))
        # Artificially induce skew in the first asset to test quantum logic
        mock_returns[:, 0] = np.where(mock_returns[:, 0] < -0.02, mock_returns[:, 0] * 1.5, mock_returns[:, 0])

        returns_df = pd.DataFrame(mock_returns, columns=tickers)

        # 3. Calculate Tensors
        math_engine = PortfolioMath(returns_df)
        mu = math_engine.get_mean_returns()
        sigma = math_engine.get_covariance_matrix()
        coskew = math_engine.get_coskewness_tensor()

        # 4. Solve (Classical or Surrogate Quantum)
        constraints = {
            "risk_aversion": req.risk_aversion,
            "skew_preference": req.skew_preference, # If > 0, cubic terms activate
            "max_position_pct": 1.0
        }

        solver = SurrogateOptimizer()
        weights_array = solver.solve(mu, sigma, coskew, constraints)

        # Map array back to symbols
        target_weights = {tickers[i]: float(weights_array[i]) for i in range(len(tickers))}

        # 5. Generate Trades
        trades = generate_trade_instructions(req.positions, target_weights, total_equity)

        return {
            "status": "success",
            "mode": "Quantum (Surrogate)" if req.skew_preference > 0 else "Classical",
            "target_weights": target_weights,
            "trades": trades,
            "metrics": {
                "expected_return": float(np.dot(weights_array, mu)),
                "sharpe_ratio": float(np.dot(weights_array, mu) / np.sqrt(np.dot(weights_array.T, np.dot(sigma, weights_array)))),
                "tail_risk_score": float(np.einsum('ijk,i,j,k->', coskew, weights_array, weights_array, weights_array))
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/diagnostics/phase1")
async def run_phase1_test():
    """
    Runs a comparison: Classical vs. Quantum on a known skewed dataset.
    """
    try:
        # 1. Setup Data:
        # Asset A (SAFE): Consistent, moderate returns.
        # Asset B (RISKY/TRAP): Higher average returns, same variance, BUT massive occasional crashes.

        np.random.seed(42)
        n_days = 1000

        # SAFE: Normal distribution
        safe_asset = np.random.normal(0.0005, 0.01, n_days)

        # RISKY: Mostly good days, but 1% of days are CATASTROPHIC (-20%)
        # We manually construct this to ensure high return/variance ratio but terrible skew
        risky_asset = np.random.normal(0.0025, 0.003, n_days) # Even better base returns, much lower base vol

        # Introduce "Black Swan" events (High negative skew)
        crash_indices = np.random.choice(n_days, size=10, replace=False)
        risky_asset[crash_indices] = -0.10  # 10% drops

        df = pd.DataFrame({'SAFE': safe_asset, 'RISKY': risky_asset})

        math_engine = PortfolioMath(df)
        mu = math_engine.get_mean_returns()
        sigma = math_engine.get_covariance_matrix()
        coskew = math_engine.get_coskewness_tensor()
        
        solver = SurrogateOptimizer()
        
        # 2. Run Classical
        # Classical sees: RISKY has higher Mean and roughly similar Variance.
        # It should prefer RISKY or mix them evenly.
        w_class = solver.solve(mu, sigma, coskew, {
            'risk_aversion': 1.0,
            'skew_preference': 0.0
        })

        # 3. Run Quantum (Skew penalized)
        # We use a MASSIVE skew_preference because cubic terms are numerically tiny (10^-6)
        # compared to quadratic terms.
        w_quant = solver.solve(mu, sigma, coskew, {
            'risk_aversion': 1.0,
            'skew_preference': 10000.0  # <--- CRITICAL: High scaling factor
        })

        # 4. Assert Difference
        # Quantum should strictly hold LESS of the RISKY asset than Classical
        # Or MORE of the SAFE asset.

        # We check if Quantum Safe Weight > Classical Safe Weight + buffer
        is_working = w_quant[0] > (w_class[0] + 0.05)

        return {
            "test_passed": bool(is_working),
            "classical_weights_raw": w_class.tolist(),
            "quantum_weights_raw": w_quant.tolist(),
            "classical_weights": {"SAFE": round(w_class[0],2), "RISKY": round(w_class[1],2)},
            "quantum_weights": {"SAFE": round(w_quant[0],2), "RISKY": round(w_quant[1],2)},
            "stats": {
                "safe_skew": float(pd.Series(safe_asset).skew()),
                "risky_skew": float(pd.Series(risky_asset).skew())
            },
            "message": "Quantum logic successfully penalized the negatively skewed asset." if is_working else "Logic failed to differentiate."
        }
    except Exception as e:
        import traceback
        return {"test_passed": False, "error": str(e), "trace": traceback.format_exc()}
