from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Dict, Any
from supabase import Client

from packages.quantum.services.decision_service import DecisionService
from packages.quantum.security import get_current_user_id, get_supabase_user_client

router = APIRouter(
    prefix="/decisions",
    tags=["decisions"]
)

@router.get("/lineage")
def get_decision_lineage(
    window: str = Query("7d", pattern="^(7d|30d)$"),
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
) -> Dict[str, Any]:
    """
    Returns aggregated decision lineage stats and diffs for the specified window.
    Supports '7d' and '30d' windows.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database connection unavailable")

    service = DecisionService(supabase)
    return service.get_lineage_diff(user_id, window)
