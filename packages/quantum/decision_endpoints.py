from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Literal

from packages.quantum.security import get_current_user_id
from packages.quantum.api import supabase_client
from packages.quantum.services.decision_service import DecisionService

router = APIRouter(prefix="/decisions", tags=["decisions"])

@router.get("/lineage")
def get_decision_lineage(
    window: Literal['7d', '30d'] = Query('7d', description="Time window for analysis"),
    user_id: str = Depends(get_current_user_id)
):
    """
    Retrieves decision lineage statistics and diffs against the previous window.
    """
    service = DecisionService(supabase_client)
    try:
        return service.get_lineage_diff(user_id, window)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
