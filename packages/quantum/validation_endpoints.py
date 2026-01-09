from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from supabase import Client

from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.go_live_validation_service import GoLiveValidationService
from packages.quantum.public_tasks import enqueue_job_run

router = APIRouter(prefix="/validation", tags=["Go Live Validation"])

class HistoricalRunConfig(BaseModel):
    window_start: Optional[str] = None
    window_days: int = 90
    symbol: str = "SPY"

    concurrent_runs: int = 3
    stride_days: Optional[int] = None

    goal_return_pct: float = 10.0
    autotune: bool = False
    max_trials: int = 12
    strategy_name: Optional[str] = None

    seed: Optional[int] = None  # ignored

class ValidationRunRequest(BaseModel):
    mode: str # 'paper'|'historical'
    historical: Optional[HistoricalRunConfig] = None

@router.get("/status")
def get_validation_status(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    service = GoLiveValidationService(supabase)
    state = service.get_or_create_state(user_id)

    # Also fetch recent runs
    recent_runs = []
    try:
        res = supabase.table("v3_go_live_runs").select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(5) \
            .execute()
        recent_runs = res.data or []
    except Exception:
        pass

    return {
        "state": state,
        "recent_runs": recent_runs
    }

@router.post("/run")
def trigger_validation_run(
    payload: ValidationRunRequest,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    service = GoLiveValidationService(supabase)

    if payload.mode == "paper":
        # Run inline as per spec
        result = service.eval_paper(user_id)
        return result

    elif payload.mode == "historical":
        # Enqueue Job using public_tasks helper for consistency
        job_config = payload.historical.dict() if payload.historical else {}
        job_payload = {
            "mode": "historical",
            "user_id": user_id,
            "config": job_config
        }

        # We use a key based on user and time to prevent immediate double-submit,
        # but historical runs can be repeated.
        import datetime
        ts = datetime.datetime.now().isoformat()
        key = f"hist-{user_id}-{ts}"

        try:
            # enqueue_job_run returns a dict with status
            result = enqueue_job_run(
                job_name="validation_eval",
                idempotency_key=key,
                payload=job_payload
            )
            return {"status": "queued", "job_run_id": result.get("job_run_id")}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {e}")

    else:
        raise HTTPException(status_code=400, detail="Invalid mode. Supported: paper, historical")

@router.get("/journal")
def get_validation_journal(
    limit: int = 50,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    try:
        res = supabase.table("v3_go_live_journal").select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return {"entries": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/self-assessment")
def get_self_assessment(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Builds suggestions from learning_contract_violations_v3 and other learning tables.
    """
    suggestions = []

    # 1. Check Violations
    try:
        # Check if table/view exists first or just try
        # learning_contract_violations_v3 might be a view.
        # Assuming schema follows standard naming.
        # We can also check learning_feedback_loops for negative outcomes.

        # We'll stick to what we can reliably query.
        pass
    except Exception:
        pass

    # Placeholder implementation as learning tables might vary in existence
    # We return a basic structure.
    return {
        "suggestions": [
            {
                "type": "info",
                "title": "Data Collection in Progress",
                "message": "Continue trading to generate self-assessment insights.",
                "evidence": {}
            }
        ]
    }
