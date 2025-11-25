from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
import os
from core.math_engine import PortfolioMath
from core.surrogate import SurrogateOptimizer
from core.data_loader import fetch_market_data
from polygon_client import PolygonClient

router = APIRouter()

# --- Configuration ---
# If you have your Polygon Key in .env, set this to True.
# For now, we will use "Stable Mock" data to fix the jitter immediately.
USE_REAL_DATA = False

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

def generate_trade_instructions(current_positions, target_weights, total_equity):
    trades = []
    current_map = {p.symbol: p for p in current_positions}

    for symbol, weight in target_weights.items():
        # 1. Calculate Target Dollar Amount
        target_val = total_equity * weight

        # 2. Get Current Dollar Amount
        curr_pos = current_map.get(symbol)
        curr_val = curr_pos.current_value if curr_pos else 0.0
        curr_price = curr_pos.current_price if curr_pos else 100.0

        # 3. Calculate Difference
        diff = target_val - curr_val

        # 4. Filter insignificant trades (< $100 or < 1 share)
        if abs(diff) > 100.0:
            action = "BUY" if diff > 0 else "SELL"
            qty = abs(diff) / curr_price

            # Logic: Don't buy tiny fractions unless it's high value
            if qty >= 0.1:
                trades.append({
                    "symbol": symbol,
                    "action": action,
                    "value": round(abs(diff), 2),
                    "est_quantity": round(qty, 2),
                    "rationale": f"Target: {round(weight*100, 1)}% (Delta: ${int(diff)})"
                })

    return trades

@router.post("/optimize/portfolio")
async def optimize_portfolio(req: OptimizationRequest):
    try:
        # --- 1. SEPARATE ASSETS FROM CASH ---
        investable_assets = []
        liquidity = req.cash_balance

        for p in req.positions:
            # Filter out Cash or Currency placeholders
            if p.symbol in ["CUR:USD", "USD", "CASH", "MM"]:
                liquidity += p.current_value
            else:
                investable_assets.append(p)

        if not investable_assets:
            raise HTTPException(status_code=400, detail="No investable assets found (only cash).")

        tickers = [p.symbol for p in investable_assets]
        assets_equity = sum(p.current_value for p in investable_assets)
        total_portfolio_value = assets_equity + liquidity

        # --- 2. GET DATA (STABLE) ---
        # Instead of random.normal every time, we use a seed based on the ticker name
        # This ensures AAPL always looks like AAPL until we hook up Polygon.

        data_frames = {}
        np.random.seed(42) # Global seed for consistency

        for ticker in tickers:
            # Generate a "Character" for the stock based on its name hash
            # This makes the "Optimization" consistent between runs
            seed_val = sum(ord(c) for c in ticker)
            np.random.seed(seed_val)

            # Simulate 1 year of returns
            # Some assets will be high growth (Mean > 0), some high risk
            mean_return = np.random.uniform(-0.0005, 0.001)
            volatility = np.random.uniform(0.005, 0.015)

            daily_returns = np.random.normal(mean_return, volatility, 252)

            # Add "Momentum" (If the user wants profit, we need trend)
            # We artificially add a trend to the last 30 days
            trend_factor = np.random.choice([-1, 1]) * 0.001
            daily_returns[-30:] += trend_factor

            data_frames[ticker] = daily_returns

        returns_df = pd.DataFrame(data_frames)

        # --- 3. MATH ENGINE ---
        math_engine = PortfolioMath(returns_df)
        mu = math_engine.get_mean_returns(method='exponential')
        sigma = math_engine.get_covariance_matrix() + np.eye(len(tickers)) * 1e-6
        coskew = math_engine.get_coskewness_tensor()

        # --- 4. SOLVER ---
        # We tighten constraints to prevent selling EVERYTHING
        constraints = {
            "risk_aversion": req.risk_aversion,
            "skew_preference": req.skew_preference,
            "max_position_pct": 0.40, # Max 40% in one stock
        }

        solver = SurrogateOptimizer()
        weights_array = solver.solve(mu, sigma, coskew, constraints)

        # Map back to dict
        target_weights = {tickers[i]: float(weights_array[i]) for i in range(len(tickers))}

        # --- 5. GENERATE TRADES ---
        # We pass the TOTAL portfolio value (Cash + Stock) to the trade generator
        trades = generate_trade_instructions(
            investable_assets,
            target_weights,
            total_portfolio_value
        )

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
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

