import os
from dotenv import load_dotenv
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from models import Holding, SyncResponse
import plaid_service

# 1. Load environment variables BEFORE importing other things
load_dotenv()
 
app = FastAPI()

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
 
@app.get("/")
def read_root():
    return {"status": "Quantum API operational"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
 
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
