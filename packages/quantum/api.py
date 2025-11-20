"""
Portfolio Optimization API v2.0
Now with REAL market data from Polygon.io
"""

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from optimizer import optimize_portfolio, compare_optimizations
from market_data import calculate_portfolio_inputs
from options_scanner import scan_for_opportunities
from trade_journal import TradeJournal
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from models import Holding, SyncResponse
import plaid_service

# 1. Load environment variables BEFORE importing other things
load_dotenv()
 
app = FastAPI(
    title="Portfolio Optimizer API",
    description="Portfolio optimization with real market data",
    version="2.0.0"
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# Initialize Supabase Client
# We check if the vars exist to give a better error message if they are missing
url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    print("CRITICAL ERROR: Missing Supabase Environment Variables.")
    print(f"NEXT_PUBLIC_SUPABASE_URL found? {'Yes' if url else 'No'}")
    print(f"SUPABASE_SERVICE_ROLE_KEY found? {'Yes' if key else 'No'}")
    # We don't raise immediately to let the server start, but endpoints will fail
else:
    print("Supabase config loaded successfully.")

# Initialize client only if vars exist to prevent crash on startup
supabase: Client = create_client(url, key) if url and key else None


# --- Models ---

class OptimizationRequest(BaseModel):
    mode: str = Field(default="classical")
    expected_returns: List[float]
    covariance_matrix: List[List[float]]
    constraints: Optional[Dict[str, float]] = None
    risk_aversion: float = Field(default=2.0)
    asset_names: Optional[List[str]] = None


class RealDataRequest(BaseModel):
    symbols: List[str] = Field(..., description="Stock symbols")
    mode: str = Field(default="classical")
    constraints: Optional[Dict[str, float]] = None
    risk_aversion: float = Field(default=2.0)


# --- Endpoints ---

@app.get("/")
def read_root():
    return {
        "service": "Portfolio Optimizer API",
        "status": "operational",
        "version": "2.0",
        "features": ["classical optimization", "real market data", "options scout", "trade journal"],
        "data_source": "Polygon.io" if os.getenv('POLYGON_API_KEY') else "Mock Data"
    }

@app.get("/health")
def health_check():
    polygon_key = os.getenv('POLYGON_API_KEY')
    return {
        "status": "ok",
        "backend": "classical",
        "market_data": "connected" if polygon_key else "mock"
    }

@app.post("/plaid/sync_holdings", response_model=SyncResponse)
async def sync_holdings(
    authorization: Optional[str] = Header(None),
):
    if not supabase:
         raise HTTPException(status_code=500, detail="Server Error: Database not configured")

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
 
    # 1. Verify User via Supabase Auth
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Token")
 
    # 2. Retrieve Plaid Access Token for this User
    response = supabase.table("plaid_items").select("access_token").eq("user_id", user_id).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="No linked Plaid account found for user.")
        
    access_token = response.data[0]['access_token']
 
    # 3. Fetch from Plaid
    try:
        holdings = plaid_service.fetch_and_normalize_holdings(access_token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 
    # 4. Upsert into Supabase
    data_to_insert = []
    for h in holdings:
        row = h.dict()
        row['user_id'] = user_id
        data_to_insert.append(row)

    if data_to_insert:
        supabase.table("holdings").upsert(
            data_to_insert, 
            on_conflict="user_id,symbol"
        ).execute()

    return SyncResponse(
        status="success",
        count=len(holdings),
        holdings=holdings
    )

@app.post("/optimize")
async def optimize(request: OptimizationRequest):
    """Optimize with provided data"""
    try:
        result = optimize_portfolio(
            mode=request.mode,
            expected_returns=request.expected_returns,
            covariance_matrix=request.covariance_matrix,
            constraints=request.constraints,
            risk_aversion=request.risk_aversion,
            asset_names=request.asset_names
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compare")
async def compare(request: OptimizationRequest):
    """Compare MV vs MVS with provided data"""
    try:
        result = compare_optimizations(
            expected_returns=request.expected_returns,
            covariance_matrix=request.covariance_matrix,
            constraints=request.constraints,
            asset_names=request.asset_names
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/optimize/real")
async def optimize_real(request: RealDataRequest):
    """Optimize using REAL market data from Polygon.io"""
    try:
        inputs = calculate_portfolio_inputs(request.symbols)

        result = optimize_portfolio(
            mode=request.mode,
            expected_returns=inputs['expected_returns'],
            covariance_matrix=inputs['covariance_matrix'],
            constraints=request.constraints,
            risk_aversion=request.risk_aversion,
            asset_names=inputs['symbols']
        )

        result['data_source'] = 'polygon.io' if not inputs.get('is_mock') else 'mock'
        result['data_points'] = inputs['data_points']
        result['symbols'] = inputs['symbols']

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Real data optimization failed: {str(e)}")


@app.post("/compare/real")
async def compare_real(request: RealDataRequest):
    """Compare MV vs MVS using REAL market data"""
    try:
        print(f"Fetching real data for: {request.symbols}")
        inputs = calculate_portfolio_inputs(request.symbols)

        print("Running comparison...")
        result = compare_optimizations(
            expected_returns=inputs['expected_returns'],
            covariance_matrix=inputs['covariance_matrix'],
            constraints=request.constraints,
            asset_names=inputs['symbols']
        )

        result['data_source'] = 'polygon.io' if not inputs.get('is_mock') else 'mock'
        result['data_points'] = inputs['data_points']
        result['symbols'] = inputs['symbols']

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Real data comparison failed: {str(e)}")


@app.get("/scout/weekly")
async def weekly_scout():
    """Get weekly option opportunities"""
    try:
        opportunities = scan_for_opportunities()
        return {
            'count': len(opportunities),
            'top_picks': opportunities[:5],
            'generated_at': datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/journal/stats")
async def journal_stats():
    """Get trade journal statistics"""
    try:
        journal = TradeJournal()
        stats = journal.get_stats()
        patterns = journal.analyze_patterns()
        rules = journal.generate_rules()

        return {
            'stats': stats,
            'patterns': patterns,
            'rules': rules,
            'recent_trades': journal.trades[-10:]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("Starting Portfolio Optimizer API v2.0...")
    print("✨ NEW: Real market data from Polygon.io")
    print("✨ NEW: Weekly Options Scout")
    print("✨ NEW: Trade Journal with Auto-Learning")
    print("API: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
