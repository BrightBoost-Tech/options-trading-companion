from fastapi import APIRouter, Depends, Body, Request, HTTPException, Query
from typing import Dict, Any, Optional
from packages.quantum.security import get_current_user
from packages.quantum.analytics.behavior_analysis import BehaviorAnalysisService
from packages.quantum.services.system_health_service import SystemHealthService

router = APIRouter()

@router.get("/analytics/behavior")
def get_behavior_summary(
    request: Request,
    window: str = Query("7d", regex="^(7d|30d)$"),
    strategy: Optional[str] = None,
    user_id: str = Depends(get_current_user)
):
    """
    Get aggregated behavior summary (veto rates, constraints, fallbacks).
    """
    try:
        supabase = request.app.state.supabase
        service = BehaviorAnalysisService(supabase)

        days = int(window.replace("d", ""))
        return service.get_behavior_summary(user_id, window_days=days, strategy_family=strategy)
    except Exception as e:
        print(f"Error fetching behavior summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/system/health")
def get_system_health(
    request: Request,
    user_id: str = Depends(get_current_user)
):
    """
    Get high-level system health metrics and status.
    """
    try:
        supabase = request.app.state.supabase
        service = SystemHealthService(supabase)
        return service.get_system_health(user_id)
    except Exception as e:
        print(f"Error fetching system health: {e}")
        # Return a safe default instead of crashing the dashboard
        return {
            "status": "Normal",
            "veto_rate_7d": 0.0,
            "veto_rate_30d": 0.0,
            "active_constraints": [],
            "not_executable_pct": 0.0,
            "partial_outcomes_pct": 0.0,
            "error": str(e)
        }

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
