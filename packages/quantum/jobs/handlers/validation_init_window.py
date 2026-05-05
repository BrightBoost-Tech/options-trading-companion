"""
Validation Forward-Window Initialization Job Handler.

v4-L1F: Validates/repairs paper_window_start and paper_window_end on
`go_live_progression` BEFORE Day 1 of the test, preventing "repair
window at checkpoint time" surprises. Does NOT increment streak,
change readiness, or trigger fail-fast.

Migrated 2026-05-04 from inline sync execution at
`/tasks/validation/init-window` (#71 PR-3). The endpoint layer keeps
the paper-mode + paused gates (rejects before enqueue); this handler
is a thin wrapper around the service call.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_NAME = "validation_init_window"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Run forward-window initialization for a single user.

    Idempotent at the service layer (upsert-shaped on
    go_live_progression). Failure observability via
    job_runs.status='failed' — exceptions propagate.

    Payload:
        user_id: str (required — endpoint enforces presence)
        date: str (ISO date, optional — for log/diagnostic context)
    """
    from packages.quantum.jobs.handlers.utils import get_admin_client
    from packages.quantum.services.go_live_validation_service import (
        GoLiveValidationService,
    )

    user_id = payload.get("user_id")
    if not user_id:
        return {"status": "error", "reason": "user_id required"}

    eval_date = payload.get("date")

    supabase = get_admin_client()
    service = GoLiveValidationService(supabase)

    result = service.ensure_forward_window_initialized(user_id)

    logger.info(
        f"validation_init_window_complete: user={user_id} date={eval_date} "
        f"status={result.get('status')} was_repaired={result.get('was_repaired')}"
    )

    return {
        "status": "ok",
        "user_id": user_id,
        "eval_date": eval_date,
        "result": result,
    }
