import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from models import Holding, SyncResponse
import plaid_service
 
app = FastAPI()

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# Initialize Supabase Client (Server-side)
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")  # Reading shared env
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Must use Service Role for backend writes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
 
@app.get("/")
def read_root():
    return {"status": "Quantum API operational"}
 
@app.post("/plaid/sync_holdings", response_model=SyncResponse)
async def sync_holdings(
    authorization: Optional[str] = Header(None),
    # In a real app, we would accept the access_token or look it up via user_id
    # For this phase, we will assume we look up the access_token from Supabase 
    # based on the user ID in the JWT.
):
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
    # NOTE: Assuming a 'plaid_items' table exists. If not, you might need to pass 
    # the access_token temporarily from frontend for dev, but let's try to query it.
    # This is a placeholder query logic:
    response = supabase.table("plaid_items").select("access_token").eq("user_id", user_id).execute()
    
    if not response.data:
        # FALLBACK FOR DEV ONLY: If no DB record, check if passed in headers (insecure but useful for quick testing)
        # or return error. Let's return error to force proper setup.
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

    if not data_to_insert:
        return SyncResponse(status="success", count=0, holdings=[])
 
    try:
        # Upsert based on (user_id, symbol)
        supabase.table("holdings").upsert(data_to_insert, on_conflict="user_id,symbol").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save holdings: {e}")
    return SyncResponse(
        status="success",
        count=len(holdings),
        holdings=holdings
    )
