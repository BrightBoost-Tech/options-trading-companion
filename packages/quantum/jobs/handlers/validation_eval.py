import logging
import time
import traceback
from typing import Dict, Any

from packages.quantum.nested_logging import _get_supabase_client
from packages.quantum.services.go_live_validation_service import GoLiveValidationService

JOB_NAME = "validation_eval"

logger = logging.getLogger(__name__)


def _eval_green_day_safe(service: GoLiveValidationService, user_id: str) -> Dict[str, Any]:
    """
    Attempt to call eval_paper_green_day if the service exposes it.

    Returns green-day fields on success, or null/default fields if the method
    is not yet available (separate PR) or if it raises.
    """
    if not hasattr(service, "eval_paper_green_day"):
        return {
            "evaluated_trading_date": None,
            "daily_realized_pnl": None,
            "green_day": None,
            "paper_green_days": None,
            "paper_last_green_day_date": None,
            "green_day_available": False,
        }
    try:
        gd = service.eval_paper_green_day(user_id)
        return {
            "evaluated_trading_date": gd.get("evaluated_trading_date"),
            "daily_realized_pnl": gd.get("daily_realized_pnl"),
            "green_day": gd.get("green_day"),
            "paper_green_days": gd.get("paper_green_days"),
            "paper_last_green_day_date": gd.get("paper_last_green_day_date"),
            "green_day_available": True,
        }
    except Exception as e:
        logger.warning(f"[validation_eval] Green day eval failed for {user_id[:8]}...: {e}")
        return {
            "evaluated_trading_date": None,
            "daily_realized_pnl": None,
            "green_day": None,
            "paper_green_days": None,
            "paper_last_green_day_date": None,
            "green_day_available": False,
            "green_day_error": str(e),
        }


def _build_paper_result(checkpoint: Dict[str, Any], green_day: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge checkpoint result and green-day result into a single audit-friendly payload.
    """
    return {
        # Readiness checkpoint fields (pass-through)
        "checkpoint_status": checkpoint.get("status"),
        "paper_consecutive_passes": checkpoint.get("paper_consecutive_passes"),
        "paper_ready": checkpoint.get("paper_ready"),
        "return_pct": checkpoint.get("return_pct"),
        "pnl_realized": checkpoint.get("pnl_realized"),
        "pnl_unrealized": checkpoint.get("pnl_unrealized"),
        "max_drawdown_pct": checkpoint.get("max_drawdown_pct"),
        "window_start": checkpoint.get("window_start"),
        "window_end": checkpoint.get("window_end"),
        "outcome_count": checkpoint.get("outcome_count"),
        # Green-day fields
        "evaluated_trading_date": green_day.get("evaluated_trading_date"),
        "daily_realized_pnl": green_day.get("daily_realized_pnl"),
        "green_day": green_day.get("green_day"),
        "paper_green_days": green_day.get("paper_green_days"),
        "paper_last_green_day_date": green_day.get("paper_last_green_day_date"),
        "green_day_available": green_day.get("green_day_available", False),
    }


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for Go-Live Validation evaluation.
    Payload:
      - mode: "paper" | "historical"
      - user_id: str (optional, but usually required)
      - config: dict (for historical)
    """
    logger.info(f"Starting validation_eval job with payload: {payload}")
    start_time = time.time()

    try:
        supabase = _get_supabase_client()
        if not supabase:
            return {"error": "Database unavailable"}

        service = GoLiveValidationService(supabase)

        mode = payload.get("mode", "paper")
        user_id = payload.get("user_id")

        if not user_id:
            # Batch mode: iterate all users with a go-live state entry
            res = supabase.table("v3_go_live_state").select("user_id").execute()
            users = [r["user_id"] for r in (res.data or [])]

            results = {}
            for uid in users:
                try:
                    if mode == "paper":
                        checkpoint = service.eval_paper_forward_checkpoint(uid)
                        green_day = _eval_green_day_safe(service, uid)
                        results[uid] = _build_paper_result(checkpoint, green_day)
                except Exception as ex:
                    logger.error(f"Error for user {uid}: {ex}")
                    results[uid] = {"checkpoint_status": "error", "error": str(ex)}

            timing_ms = (time.time() - start_time) * 1000
            return {
                "status": "batch_completed",
                "results": results,
                "timing_ms": timing_ms,
            }

        # Single User Mode
        if mode == "paper":
            # v4-L1: checkpoint-based evaluation + green-day tracking
            checkpoint = service.eval_paper_forward_checkpoint(user_id)
            green_day = _eval_green_day_safe(service, user_id)

            timing_ms = (time.time() - start_time) * 1000
            result = _build_paper_result(checkpoint, green_day)

            return {
                "status": "completed",
                "result": result,
                "timing_ms": timing_ms,
            }

        elif mode == "historical":
            config = payload.get("config", {})

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
        return {"status": "failed", "error": str(e)}
