# packages/quantum/api.py
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import logging
from datetime import datetime

# --- Internal Imports ---
# Ensure you have fixed the relative imports as discussed before
from database import supabase
from plaid_service import PlaidService
from polygon_client import PolygonClient
from heuristics import TradeGuardrails
from analytics import OptionsAnalytics

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quantum_api")

# --- App Initialization ---
app = FastAPI(title="Quantum Options API", version="2.1.0")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Services ---
# Initialize services once
polygon_api_key = os.getenv("POLYGON_API_KEY")
plaid_service = PlaidService()
polygon_client = PolygonClient(api_key=polygon_api_key)

# ==========================================
# 1. PLAID & PORTFOLIO ROUTES (RESTORED)
# ==========================================

@app.get("/plaid/status")
async def get_plaid_status(user_id: str):
    """Check if user has linked a broker"""
    try:
        response = supabase.table('user_settings').select("plaid_access_token").eq("user_id", user_id).execute()
        is_connected = bool(response.data and response.data[0].get('plaid_access_token'))
        return {"is_connected": is_connected}
    except Exception as e:
        logger.error(f"Plaid status error: {e}")
        return {"is_connected": False}

@app.post("/plaid/create_link_token")
async def create_link_token(user_id: str = Body(..., embed=True)):
    """Generate token to initialize Plaid Link on frontend"""
    try:
        link_token = plaid_service.create_link_token(user_id)
        return {"link_token": link_token}
    except Exception as e:
        logger.error(f"Link token error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/plaid/exchange_public_token")
async def exchange_token(user_id: str = Body(...), public_token: str = Body(...)):
    """Swap public token for permanent access token"""
    try:
        access_token = plaid_service.exchange_public_token(public_token)
        # Store encrypted token in DB
        plaid_service.store_access_token(user_id, access_token)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/plaid/sync_holdings")
async def sync_holdings(user_id: str = Body(..., embed=True)):
    """
    CRITICAL: Fetches holdings from Plaid, gets prices from Polygon,
    and updates the 'positions' table.
    """
    try:
        logger.info(f"Syncing holdings for {user_id}...")

        # 1. Get Access Token
        access_token = plaid_service.get_access_token(user_id)
        if not access_token:
            raise HTTPException(status_code=400, detail="No broker connected")

        # 2. Fetch from Plaid
        holdings = plaid_service.get_holdings(access_token)

        # 3. Enrich with Polygon Data & Upsert to DB
        updated_positions = []
        for h in holdings:
            symbol = h['symbol']

            # --- POLYGON FIX: Skip Cash tickers ---
            current_price = 1.0
            if "CUR:" not in symbol and symbol != "USD":
                try:
                    # Fetch real price
                    # Assuming get_last_quote returns a float
                    quote = polygon_client.get_last_quote(symbol)
                    current_price = quote if quote else h['price']
                except Exception as poly_error:
                    logger.warning(f"Polygon error for {symbol}: {poly_error}")
                    current_price = h['price'] # Fallback to Plaid price

            # Upsert into Supabase
            position_data = {
                "user_id": user_id,
                "symbol": symbol,
                "quantity": h['quantity'],
                "cost_basis": h['cost_basis'],
                "current_price": current_price,
                "market_value": h['quantity'] * current_price,
                "pnl_pct": ((current_price - h['cost_basis']) / h['cost_basis'] * 100) if h['cost_basis'] else 0
            }

            # Upsert logic (Symbol + User_ID is unique key)
            supabase.table('positions').upsert(position_data, on_conflict="user_id, symbol").execute()
            updated_positions.append(position_data)

        return {"status": "synced", "count": len(updated_positions)}

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio/snapshot")
async def get_portfolio_snapshot(user_id: str):
    """Get current positions for the dashboard"""
    try:
        response = supabase.table('positions').select("*").eq("user_id", user_id).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 2. OPTIMIZER ROUTES (MAINTENANCE MODE)
# ==========================================

class OptimizationRequest(BaseModel):
    user_id: str
    cash_balance: float = Field(..., description="Current available cash")
    risk_tolerance: float = Field(0.5, ge=0.0, le=1.0)
    current_positions: Optional[List[dict]] = None

@app.post("/optimize/portfolio")
async def optimize_portfolio(request: OptimizationRequest):
    """
    Analyzes CURRENT positions for risks (Maintenance).
    Does NOT suggest new random trades.
    """
    # 1. Fetch Positions
    if not request.current_positions:
        response = supabase.table('positions').select("*").eq('user_id', request.user_id).execute()
        positions = response.data
    else:
        positions = request.current_positions

    # 2. Total Value Calculation
    invested_value = sum(float(p['quantity']) * float(p.get('current_price', 0) or 0) for p in positions)
    total_value = invested_value + request.cash_balance

    # 3. IDENTIFY ADJUSTMENTS
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
                "reason": f"Stop Loss Hit ({pnl_pct:.1f}%)",
                "impact": "Preserve Capital"
            })
        elif pnl_pct >= 75:
             adjustments.append({
                "type": "OPPORTUNITY",
                "action": "TRIM",
                "symbol": symbol,
                "reason": f"Take Profit ({pnl_pct:.1f}%)",
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

    return {
        "status": "Healthy" if not adjustments else "Attention Needed",
        "adjustments": adjustments,
        "metrics": {
            "diversity_score": 85,
            "beta_weighted_delta": 12.5
        }
    }

# ==========================================
# 3. SCOUT ROUTES (GROWTH MODE)
# ==========================================

@app.get("/scout/weekly")
async def get_weekly_scout(risk_tolerance: float = 0.5):
    """
    Generates NEW trade ideas (Growth).
    """
    # Mock Candidates (In prod, this comes from Polygon scan)
    candidates = [
        {"symbol": "NVDA", "strategy": "Iron Condor", "iv_rank": 62, "prob_profit": 0.68, "max_gain": 420, "max_loss": 580, "thesis": "High IV creates ideal neutral setup."},
        {"symbol": "AMD", "strategy": "Long Call", "iv_rank": 25, "prob_profit": 0.45, "max_gain": 1200, "max_loss": 350, "thesis": "Oversold RSI with IV reset."},
        {"symbol": "SPY", "strategy": "Put Credit Spread", "iv_rank": 35, "prob_profit": 0.78, "max_gain": 85, "max_loss": 415, "thesis": "Bullish trend continuation."},
    ]

    # Score them
    results = []
    for c in candidates:
        c['alpha_score'] = OptionsAnalytics.calculate_alpha_score({
            'greeks': {'theta': 0.1, 'delta': 0.2},
            'margin_requirement': c['max_loss'],
            'prob_profit': c['prob_profit'],
            'iv_rank': c['iv_rank']
        })
        results.append(c)

    results.sort(key=lambda x: x['alpha_score'], reverse=True)
    return {"scout_results": results}

# ==========================================
# 4. JOURNAL ROUTES (RESTORED)
# ==========================================

@app.get("/journal/stats")
async def get_journal_stats(user_id: str):
    """Get win rate and PnL stats"""
    # Simply mocking or fetching from DB
    return {
        "win_rate": 66.7,
        "total_pnl": 1250.00,
        "trades_count": 12
    }