from fastapi import APIRouter, Depends, Body, Request, HTTPException
from typing import Dict, Any, Optional
from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.evolution_service import EvolutionService
from supabase import Client

router = APIRouter()

@router.get("/analytics/evolution")
async def get_system_evolution(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns system evolution metrics for the last 7 days.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    service = EvolutionService(supabase)
    return service.get_weekly_evolution(user_id)

@router.post("/analytics/events")
async def log_analytics_event(
    request: Request,
    event_name: str = Body(..., embed=True),
    category: str = Body("general", embed=True),
    properties: Dict[str, Any] = Body({}, embed=True),
    user_id: str = Depends(get_current_user)
):
    """
    Log an analytics event.
    Accepts event details and uses the AnalyticsService (stored in app.state) to log.
    Always returns 200 OK to prevent blocking client UI.
    """
    try:
        analytics_service = request.app.state.analytics_service
        if analytics_service:
            analytics_service.log_event(
                user_id=user_id,
                event_name=event_name,
                category=category,
                properties=properties
            )
    except Exception as e:
        # Swallow errors to ensure non-blocking behavior
        print(f"Failed to log analytics event: {e}")

    return {"status": "ok"}
