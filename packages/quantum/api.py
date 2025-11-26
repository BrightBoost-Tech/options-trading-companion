# packages/quantum/api.py

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

# --- Mock Supabase ---
class SupabaseClient:
    def table(self, name): return self
    def select(self, cols): return self
    def eq(self, col, val): return self
    def execute(self): return self
    @property
    def data(self): return []

supabase = SupabaseClient()
# --- End Mock ---


app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Position(BaseModel):
    symbol: str
    quantity: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    pnl_pct: Optional[float] = None

class OptimizationRequest(BaseModel):
    user_id: str
    cash_balance: float
    risk_tolerance: float
    current_positions: Optional[List[Position]] = None


@app.post("/optimize/portfolio")
async def optimize_portfolio(request: OptimizationRequest):
    # 1. Fetch Positions
    if not request.current_positions:
        response = supabase.table('positions').select("*").eq('user_id', request.user_id).execute()
        positions = response.data
    else:
        # Convert Pydantic models to dicts for processing
        positions = [p.dict() for p in request.current_positions]

    # 2. Total Value Calculation
    invested_value = sum(float(p['quantity']) * float(p.get('current_price', 0) or 0) for p in positions)
    total_value = invested_value + request.cash_balance

    # 3. IDENTIFY ADJUSTMENTS (The "Maintenance" Logic)
    adjustments = []
    
    # Rule A: Stop Loss / Take Profit Checks
    for p in positions:
        pnl_pct = float(p.get('pnl_pct', 0) or 0)
        symbol = p['symbol']

        if pnl_pct <= -50:
            adjustments.append({
                "type": "CRITICAL",
                "action": "CLOSE",
                "symbol": symbol,
                "reason": f"Stop Loss Hit ({pnl_pct}%)",
                "impact": "Preserve Capital"
            })
        elif pnl_pct >= 75:
             adjustments.append({
                "type": "OPPORTUNITY",
                "action": "TRIM",
                "symbol": symbol,
                "reason": f"Take Profit ({pnl_pct}%)",
                "impact": "Lock Gains"
            })

    # Rule B: Concentration Risk
    for p in positions:
        mkt_val = float(p.get('market_value', 0) or 0)
        if total_value > 0 and (mkt_val / total_value) > 0.25:
             adjustments.append({
                "type": "WARNING",
                "action": "REDUCE",
                "symbol": p['symbol'],
                "reason": "Concentration > 25%",
                "impact": "Reduce Idiosyncratic Risk"
            })

    # Rule C: Delta Hedging (Simple)
    # If we had portfolio delta, we would suggest a hedge here.
    # For now, we mock a hedge if the user has NO positions.
    if not positions and request.cash_balance > 1000:
        # Actually, no. If no positions, Optimizer should say "Ready to Allocate".
        pass

    return {
        "status": "Healthy" if not adjustments else "Attention Needed",
        "adjustments": adjustments,
        "metrics": {
            "diversity_score": 85, # dynamic calculation in real app
            "beta_weighted_delta": 12.5
        }
    }

@app.get("/scout/weekly")
async def get_weekly_scout(risk_tolerance: float = 0.5):
    # 1. This is where "New Ideas" and "Quantum" logic live now

    # Mock Candidates (In prod, this comes from Polygon scan)
    candidates = [
        {"symbol": "NVDA", "strategy": "Iron Condor", "iv_rank": 62, "prob_profit": 0.68, "max_gain": 420, "max_loss": 580, "thesis": "High IV creates ideal neutral setup."},
        {"symbol": "AMD", "strategy": "Long Call", "iv_rank": 25, "prob_profit": 0.45, "max_gain": 1200, "max_loss": 350, "thesis": "Oversold RSI with IV reset."},
        {"symbol": "SPY", "strategy": "Put Credit Spread", "iv_rank": 35, "prob_profit": 0.78, "max_gain": 85, "max_loss": 415, "thesis": "Bullish trend continuation."},
    ]

    # 2. Score them
    # In a real app, you would import and use your actual analytics module
    # from analytics import OptionsAnalytics
    class MockOptionsAnalytics:
        @staticmethod
        def calculate_alpha_score(data):
            # Simple mock scoring logic
            score = (data['prob_profit'] * 100) + (data['iv_rank'] * 0.5)
            return round(score, 2)

    results = []
    for c in candidates:
        # Mocking data for the score function
        c['alpha_score'] = MockOptionsAnalytics.calculate_alpha_score({
            'greeks': {'theta': 0.1, 'delta': 0.2},
            'margin_requirement': c['max_loss'],
            'prob_profit': c['prob_profit'],
            'iv_rank': c['iv_rank']
        })
        results.append(c)

    results.sort(key=lambda x: x['alpha_score'], reverse=True)
    return {"scout_results": results}

# Health check endpoint
@app.get("/health")
def read_root():
    return {"status": "ok"}

# If you need to run this file directly for debugging
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)