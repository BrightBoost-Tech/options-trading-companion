import os
import io
import csv
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from supabase import create_client, Client
import json
import requests

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from security import encrypt_token, decrypt_token, get_current_user

# Import models and services
from models import Holding, SyncResponse, PortfolioSnapshot
import plaid_service
import plaid_endpoints

# Import functionalities
from options_scanner import scan_for_opportunities
from services.journal_service import JournalService
from optimizer import router as optimizer_router
from market_data import calculate_portfolio_inputs
from ev_calculator import calculate_ev, calculate_position_size
from services.enrichment_service import enrich_holdings_with_analytics
from typing import Optional, Literal


# 1. Load environment variables BEFORE importing other things
load_dotenv()

TEST_USER_UUID = '75ee12ad-b119-4f32-aeea-19b4ef55d587'
 
app = FastAPI(
    title="Portfolio Optimizer API",
    description="Portfolio optimization with real market data",
    version="2.0.0"
)

# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://your-production-domain.com"], # No more "*"
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
 
# Initialize Supabase Client
url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    print("CRITICAL ERROR: Missing Supabase Environment Variables.")
    print(f"NEXT_PUBLIC_SUPABASE_URL found? {'Yes' if url else 'No'}")
    print(f"SUPABASE_SERVICE_ROLE_KEY found? {'Yes' if key else 'No'}")
else:
    print("Supabase config loaded successfully.")

supabase: Client = create_client(url, key) if url and key else None

# --- Register Plaid Endpoints ---
# Pass supabase client to plaid_endpoints
plaid_endpoints.register_plaid_endpoints(app, plaid_service, supabase)

# --- Register Optimizer Endpoints ---
app.include_router(optimizer_router)

# --- Models ---

class OptimizationRequest(BaseModel):
    expected_returns: List[float]
    covariance_matrix: List[List[float]]
    mode: str = Field(default="classical")
    constraints: Optional[Dict[str, float]] = None
    risk_aversion: float = Field(default=2.0)
    asset_names: Optional[List[str]] = None
    
class RealDataRequest(BaseModel):
    symbols: Optional[List[str]] = Field(None, description="Stock symbols (optional if authenticated)")
    mode: str = Field(default="classical")
    constraints: Optional[Dict[str, float]] = None
    risk_aversion: float = Field(default=2.0)

# --- Helper Functions ---

async def create_portfolio_snapshot(user_id: str):
    """Creates a new portfolio snapshot from current positions."""
    if not supabase:
        return

    # 1. Fetch current holdings from POSITIONS table (Single Truth)
    response = supabase.table("positions").select("*").eq("user_id", user_id).execute()
    holdings = response.data

    if not holdings:
        # Fallback to check holdings table just in case during migration?
        # Prompt says "positions table is the single truth". So no fallback.
        # But we must be graceful.
        pass

    if not holdings:
        return

    # 2. Enrich Holdings with Analytics
    holdings = enrich_holdings_with_analytics(holdings)

    # 3. Calculate Risk Metrics (Basic)
    symbols = [h['symbol'] for h in holdings if h['symbol']]
    risk_metrics = {}

    try:
        # Attempt to get real data for metrics
        if symbols:
            inputs = calculate_portfolio_inputs(symbols)

            risk_metrics = {
                "count": len(symbols),
                "symbols": symbols,
                "data_source": "polygon.io" if not inputs.get('is_mock') else "mock"
            }
    except Exception as e:
        print(f"Failed to calculate risk metrics for snapshot: {e}")
        risk_metrics = {"error": str(e)}

    # 4. Create Snapshot
    snapshot = {
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "snapshot_type": "on-sync",
        "data_source": "plaid",
        "holdings": holdings, # Storing the positions snapshot
        "risk_metrics": risk_metrics,
        "optimizer_status": "ready"
    }

    supabase.table("portfolio_snapshots").insert(snapshot).execute()

# --- Endpoints ---

@app.get("/")
def read_root():
    return {
        "status": "Quantum API operational",
        "service": "Portfolio Optimizer API",
        "version": "2.0",
        "features": ["classical optimization", "real market data", "options scout", "trade journal"],
        "data_source": "Polygon.io" if os.getenv('POLYGON_API_KEY') else "Mock Data"
    }

@app.get("/health")
def health_check():
    polygon_key = os.getenv('POLYGON_API_KEY')
    return {
        "status": "ok",
        "market_data": "connected" if polygon_key else "not configured",
    }

@app.post("/plaid/sync_holdings", response_model=SyncResponse)
@limiter.limit("5/minute") # Rate Limit: 5 syncs per minute per IP
async def sync_holdings(
    request: Request,
    user_id: str = Depends(get_current_user) # NOW REQUIRES REAL JWT
):
    """
    Syncs holdings from Plaid and updates the positions table.
    """
    # 1. Log Audit
    if supabase:
        try:
            supabase.table("audit_logs").insert({
                "user_id": user_id,
                "action": "SYNC_HOLDINGS",
                "ip_address": request.client.host
            }).execute()
        except Exception:
            # Audit log failure shouldn't stop the sync
            pass

    if not supabase:
        raise HTTPException(status_code=500, detail="Server Error: Database not configured")
 
    # 2. Retrieve Plaid Access Token
    plaid_access_token = None
    if supabase:
        # Check user_settings first (preferred)
        try:
            res = supabase.table("user_settings").select("plaid_access_token").eq("user_id", user_id).single().execute()
            if res.data:
                raw_token = res.data.get('plaid_access_token')
                try:
                    plaid_access_token = decrypt_token(raw_token)
                except Exception:
                    # Fallback to raw if decryption fails (e.g. migration)
                    plaid_access_token = raw_token
        except Exception:
            pass

        # Fallback to plaid_items if not in user_settings
        if not plaid_access_token:
             try:
                 response = supabase.table("plaid_items").select("access_token").eq("user_id", user_id).limit(1).execute()
                 if response.data:
                     raw_token = response.data[0]['access_token']
                     try:
                        plaid_access_token = decrypt_token(raw_token)
                     except Exception:
                        plaid_access_token = raw_token
             except Exception:
                 pass
    
    # 3. Fetch from Plaid
    errors = []
    holdings = []
    sync_attempted = False

    if plaid_access_token:
        try:
            print("Fetching Plaid holdings...")
            # This returns normalized Holding objects
            plaid_holdings = plaid_service.fetch_and_normalize_holdings(plaid_access_token)
            print(f"✅ PLAID RAW RETURN: Found {len(plaid_holdings)} holdings.")
            for h in plaid_holdings:
               print(f"   - Symbol: {h.symbol}, Qty: {h.quantity}, Price: {h.current_price}")
            holdings.extend(plaid_holdings)
            sync_attempted = True
        except Exception as e:
            print(f"Plaid Sync Error: {e}")
            errors.append(f"Plaid: {str(e)}")

    if not sync_attempted:
         raise HTTPException(status_code=404, detail="No linked broker accounts found.")

    if errors and not holdings:
        raise HTTPException(status_code=500, detail=f"Failed to sync holdings: {'; '.join(errors)}")
 
    # 4. Upsert into POSITIONS (Single Truth)
    if supabase and holdings:
        data_to_insert = []
        for h in holdings:
            row = h.model_dump()
            position_row = {
                "user_id": user_id,
                "symbol": row['symbol'],
                "quantity": row['quantity'],
                "cost_basis": row['cost_basis'],
                "current_price": row['current_price'],
                "currency": row['currency'],
                "source": "plaid",
                "updated_at": datetime.now().isoformat()
            }
            data_to_insert.append(position_row)

        try:
            supabase.table("positions").upsert(
                data_to_insert,
                on_conflict="user_id,symbol"
            ).execute()
        except Exception as e:
            print(f"Failed to upsert positions: {e}")
            raise HTTPException(status_code=500, detail=f"Database Error: {e}")

        # 5. Create Snapshot
        await create_portfolio_snapshot(user_id)

    return SyncResponse(
        status="success",
        count=len(holdings),
        holdings=holdings
    )

@app.get("/holdings/export")
async def export_holdings_csv(
    brokerage: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Exports holdings to a CSV file from POSITIONS table.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Server Error: Database not configured")

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Token")

    # Fetch from POSITIONS
    query = supabase.table("positions").select("*").eq("user_id", user_id)

    response = query.execute()
    positions = response.data

    if brokerage:
        # Filter if needed (e.g. source=plaid)
        pass

    if not positions:
        raise HTTPException(status_code=404, detail="No holdings found to export")

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["accountId", "symbol", "quantity", "cost_basis", "current_price", "currency", "source"])

    for p in positions:
        writer.writerow([
            p.get('account_id', ''),
            p.get('symbol', ''),
            p.get('quantity', 0),
            p.get('cost_basis', 0),
            p.get('current_price', 0),
            p.get('currency', 'USD'),
            p.get('source', '')
        ])

    output.seek(0)
    filename = f"portfolio_export_{datetime.now().strftime('%Y-%m-%d')}.csv"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/portfolio/snapshot")
async def get_portfolio_snapshot(
    user_id: str = Depends(get_current_user),
    refresh: bool = False
):
    """Retrieves the most recent portfolio snapshot for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    # 1. Get latest snapshot from the database
    try:
        response = supabase.table("portfolio_snapshots") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    snapshot_data = response.data[0] if response.data else None

    # 2. Check for staleness (e.g., older than 15 minutes) - Note: refresh logic is a stub
    if snapshot_data:
        created_at_str = snapshot_data['created_at']
        # Ensure timezone awareness for correct comparison
        created_at = datetime.fromisoformat(created_at_str).replace(tzinfo=timezone.utc)
        is_stale = (datetime.now(timezone.utc) - created_at) > timedelta(minutes=15)

    if snapshot_data:
        # Add buying power if available from a related table
        try:
            res = supabase.table("plaid_items").select("buying_power").eq("user_id", user_id).single().execute()
            if res.data and res.data.get('buying_power') is not None:
                snapshot_data['buying_power'] = res.data.get('buying_power')
        except Exception:
            pass  # Non-critical, ignore if it fails
        return snapshot_data
    else:
        # Return the same structure as before for consistency
        return {"message": "No snapshot found", "holdings": []}




@app.get("/scout/weekly")
async def weekly_scout(user_id: str = Depends(get_current_user)):
    """Get weekly option opportunities based on the user's current holdings."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")

    try:
        # 1. Fetch user's holdings from the single source of truth
        response = supabase.table("positions").select("symbol").eq("user_id", user_id).execute()
        holdings = response.data

        if not holdings:
            return {
                'count': 0,
                'top_picks': [],
                'generated_at': datetime.now().isoformat(),
                'source': 'user-holdings',
                'message': 'No holdings found to generate opportunities.'
            }

        # 2. Extract symbols to scan
        symbols = list(set([h['symbol'] for h in holdings if h.get('symbol') and "USD" not in h['symbol'] and "CASH" not in h['symbol']]))

        if not symbols:
            return {
                'count': 0,
                'top_picks': [],
                'generated_at': datetime.now().isoformat(),
                'source': 'user-holdings',
                'message': 'No scannable assets in your portfolio.'
            }

        # 3. Scan for opportunities based on these symbols
        opportunities = scan_for_opportunities(symbols=symbols)

        return {
            'count': len(opportunities),
            'top_picks': opportunities[:5],
            'generated_at': datetime.now().isoformat(),
            'source': 'user-holdings'
        }
    except Exception as e:
      print(f"Error in weekly_scout: {e}")
      return {
          "top_picks": [],
          "error": "scout_unavailable",
          "message": f"An error occurred while scouting for opportunities: {e}"
      }

       print(f"Error in weekly_scout: {e}")
        return {
            "top_picks": [],
            "error": "scout_unavailable",
            "message": f"An error occurred while scouting for opportunities: {e}"
        }
 main

@app.get("/journal/entries")
async def get_journal_entries(user_id: str = Depends(get_current_user)):
    """Retrieves all journal entries for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    try:
        journal_service = JournalService(supabase)
        entries = journal_service.get_journal_entries(user_id)
        return {"count": len(entries), "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@app.get("/journal/stats")
async def get_journal_stats(user_id: str = Depends(get_current_user)):
    """Gets trade journal statistics for the authenticated user."""
        raise HTTPException(status_code=500, detail=f"An error occurred while scouting for opportunities: {e}")

@app.get("/journal/entries")
async def get_journal_entries(user_id: str = Depends(get_current_user)):
    """Retrieves all journal entries for the authenticated user."""
 main
 main
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    try:
        journal_service = JournalService(supabase)
        entries = journal_service.get_journal_entries(user_id)

        if isinstance(entries, str):
            try:
                entries = json.loads(entries)
            except json.JSONDecodeError:
                entries = []

        if not isinstance(entries, list):
            entries = []

        if not entries:
            return {
                "stats": {"win_rate": 0, "total_trades": 0, "profit_factor": 0, "avg_return": 0},
                "recent_trades": []
            }

        # Placeholder for real stats calculation
        return {
             "stats": {"win_rate": 50, "total_trades": len(entries), "profit_factor": 1.5, "avg_return": 10},
             "recent_trades": entries
        }

 fix/indentation-error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

=======
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

=======
        return {"count": len(entries), "entries": entries}
    except Exception as e:

    main
 main

class EVRequest(BaseModel):
    premium: float
    strike: float
    current_price: float
    delta: float
    strategy: Literal["long_call", "long_put", "short_call", "short_put",
                      "credit_spread", "debit_spread", "iron_condor", "strangle"]
    width: Optional[float] = None
    contracts: int = 1
    account_value: Optional[float] = None
    max_risk_percent: Optional[float] = 2.0

@app.post("/ev")
async def get_expected_value(request: EVRequest):
    result = calculate_ev(
        premium=request.premium,
        strike=request.strike,
        current_price=request.current_price,
        delta=request.delta,
        strategy=request.strategy,
        width=request.width,
        contracts=request.contracts
    )

    response = result.to_dict()

    if request.account_value and result.max_loss > 0:
        position_size = calculate_position_size(
            account_value=request.account_value,
            max_risk_percent=request.max_risk_percent,
            max_loss_per_contract=result.max_loss
        )
        response["position_sizing"] = position_size

    return response

# --- Trade Journal Endpoints ---

@app.post("/journal/trades", status_code=201)
async def add_trade_to_journal(trade: Dict, user_id: str = Depends(get_current_user)):
    """Adds a new trade to the journal for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    try:
        journal_service = JournalService(supabase)
        new_trade = journal_service.add_trade(user_id, trade)
        return new_trade
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to add trade: {e}")

@app.put("/journal/trades/{trade_id}/close")
async def close_trade_in_journal(trade_id: int, exit_date: str, exit_price: float, user_id: str = Depends(get_current_user)):
    """Closes an existing trade in the journal for the authenticated user."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    try:
        journal_service = JournalService(supabase)
        closed_trade = journal_service.close_trade(user_id, trade_id, exit_date, exit_price)
        return closed_trade
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to close trade: {e}")

if __name__ == "__main__":
    import uvicorn
    print("Starting Portfolio Optimizer API v2.0...")
    print("✨ NEW: Real market data from Polygon.io")
    print("✨ NEW: Weekly Options Scout")
    print("✨ NEW: Trade Journal with Auto-Learning")
    print("API: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000)
