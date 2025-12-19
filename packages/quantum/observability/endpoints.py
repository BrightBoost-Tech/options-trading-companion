from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Any, Dict
from packages.quantum.security import get_current_user
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(get_current_user)]
)

# Admin Client Init
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key
supabase_admin: Client = create_client(url, key) if url and key else None

def get_admin_client():
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")
    return supabase_admin

@router.get("/trade_attribution")
async def get_trade_attribution(
    limit: int = Query(50, le=100),
    window: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    client: Client = Depends(get_admin_client)
):
    """
    Query the trade_attribution_v3 view.
    """
    query = client.table("trade_attribution_v3").select("*").order("created_at", desc=True).limit(limit)

    if window:
        # Quote "window" just in case, though library handles it.
        # But for filters, Supabase-py maps string keys.
        query = query.eq("window", window)
    if strategy:
        query = query.eq("strategy", strategy)
    if regime:
        query = query.eq("regime", regime)

    try:
        res = query.execute()
        return res.data
    except Exception as e:
        print(f"Error querying trade_attribution_v3: {e}")
        raise HTTPException(status_code=500, detail="Failed to query trade attribution")

@router.get("/ev_leakage")
async def get_ev_leakage(
    limit: int = Query(50, le=100),
    client: Client = Depends(get_admin_client)
):
    """
    Query ev_leakage_by_bucket_v3 view, sorted by most negative ev_leakage.
    """
    try:
        query = client.table("ev_leakage_by_bucket_v3").select("*").order("ev_leakage", desc=False).limit(limit)
        res = query.execute()
        return res.data
    except Exception as e:
        print(f"Error querying ev_leakage_by_bucket_v3: {e}")
        raise HTTPException(status_code=500, detail="Failed to query EV leakage")
