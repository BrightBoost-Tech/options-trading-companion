import logging
import traceback
from typing import Dict, Any

from packages.quantum.nested_logging import _get_supabase_client
from packages.quantum.services.go_live_validation_service import GoLiveValidationService

JOB_NAME = "validation_eval"

logger = logging.getLogger(__name__)

def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for Go-Live Validation evaluation.
    Payload:
      - mode: "paper" | "historical"
      - user_id: str (optional, but usually required)
      - config: dict (for historical)
    """
    logger.info(f"Starting validation_eval job with payload: {payload}")

    try:
        supabase = _get_supabase_client()
        if not supabase:
            return {"error": "Database unavailable"}

        service = GoLiveValidationService(supabase)

        mode = payload.get("mode", "paper")
        user_id = payload.get("user_id")

        if not user_id:
            # If cron triggered without user_id, we might want to run for ALL active users?
            # Or fail?
            # Spec says "Payload includes mode='paper' (default) and optional user_id override."
            # If optional user_id is missing, maybe we iterate over users?
            # "Calls eval_paper for target user(s)" implies support for multiple.
            # But eval_paper is single user.
            # We'll fetch active users from v3_go_live_state or just all users?
            # Safer to require user_id for now or iterate a known set if needed.
            # Let's iterate users who have a state entry?

            # Fetch users with active state
            # Or just fetch all users?
            res = supabase.table("v3_go_live_state").select("user_id").execute()
            users = [r["user_id"] for r in (res.data or [])]

            results = {}
            for uid in users:
                try:
                    if mode == "paper":
                        # v4-L1: Use checkpoint-based evaluation
                        res = service.eval_paper_forward_checkpoint(uid)
                        results[uid] = res.get("status")
                    # Historical is usually per-user triggered, but if cron triggered?
                    # Historical is heavy, probably shouldn't run for all users in one job.
                except Exception as ex:
                    logger.error(f"Error for user {uid}: {ex}")
                    results[uid] = "error"

            return {"status": "batch_completed", "results": results}

        # Single User Mode
        if mode == "paper":
            # v4-L1: Use checkpoint-based evaluation
            result = service.eval_paper_forward_checkpoint(user_id)
            return {"status": "completed", "result": result}

        elif mode == "historical":
            config = payload.get("config", {})

            # PR4: Check if training mode is enabled
            if config.get("train", False):
                logger.info(f"Running training loop for user {user_id}")
                result = service.train_historical(user_id, config)
                return {"status": "completed", "mode": "train", "result": result}
            else:
                result = service.eval_historical(user_id, config)
                return {"status": "completed", "result": result}

        else:
            return {"error": f"Unknown mode: {mode}"}

    except Exception as e:
        logger.error(f"Validation job failed: {e}")
        logger.error(traceback.format_exc())
        # Never raise unhandled exception as per spec
        return {"status": "failed", "error": str(e)}
