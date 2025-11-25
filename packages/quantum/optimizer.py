# packages/quantum/optimizer.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import numpy as np

# Import our new core modules
from core.data_loader import fetch_market_data
from core.math_engine import PortfolioMath
from core.surrogate import SurrogateOptimizer
# from polygon_client import PolygonClient # Assuming you have this

router = APIRouter()

class OptimizationRequest(BaseModel):
    tickers: List[str]
    risk_aversion: float = 1.0
    skew_preference: float = 0.0 # 0.0 = Standard MV, >0 = Skew Aware
    max_position_pct: float = 0.20

@router.post("/quantum-ready")
async def optimize_portfolio(req: OptimizationRequest):
    try:
        # 1. Get Data
        # Note: In real app, inject Polygon client dependency here
        # returns_df = await fetch_market_data(req.tickers, polygon_client)

        # MOCK DATA FOR PHASE 1 TESTING IF NO API KEY
        import pandas as pd
        mock_returns = np.random.normal(0.001, 0.02, (100, len(req.tickers)))
        returns_df = pd.DataFrame(mock_returns, columns=req.tickers)

        # 2. Calculate Tensors (The Heavy Lifting)
        math_engine = PortfolioMath(returns_df)
        mu = math_engine.get_mean_returns()
        sigma = math_engine.get_covariance_matrix()
        coskew = math_engine.get_coskewness_tensor()

        # 3. Solve (Using Surrogate for now)
        constraints = {
            "risk_aversion": req.risk_aversion,
            "skew_preference": req.skew_preference,
            "max_position_pct": req.max_position_pct
        }
        
        solver = SurrogateOptimizer()
        weights = solver.solve(mu, sigma, coskew, constraints)
        
        # 4. Format Response
        result = {}
        for i, ticker in enumerate(req.tickers):
            result[ticker] = round(float(weights[i]), 4)

        return {
            "status": "success",
            "method": "surrogate_classical_cubic",
            "weights": result,
            "metrics": {
                "expected_return": float(np.dot(weights, mu)),
                "variance": float(np.dot(weights.T, np.dot(sigma, weights))),
                # Calculate final portfolio skew
                "skewness": float(np.einsum('ijk,i,j,k->', coskew, weights, weights, weights))
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
