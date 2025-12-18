import time
from typing import Any, Dict
from packages.quantum.services.workflow_orchestrator import run_weekly_report
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "weekly_report"

# RQ calls run(payload); ctx must be optional.
def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    start_time = time.time()
    notes = []
    counts = {"processed": 0, "failed": 0}

    try:
        client = get_admin_client()
        active_users = get_active_user_ids(client)

        async def process_users():
            processed = 0
            failed = 0
            for uid in active_users:
                try:
                    await run_weekly_report(client, uid)
                    processed += 1
                except Exception as e:
                    # Log but continue for other users
                    notes.append(f"Failed for user {uid}: {str(e)}")
                    failed += 1
            return processed, failed

        processed, failed = run_async(process_users())
        counts["processed"] = processed
        counts["failed"] = failed

        timing_ms = (time.time() - start_time) * 1000
        return {
            "ok": True,
            "counts": counts,
            "timing_ms": timing_ms,
            "notes": notes
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Weekly report job failed: {e}")
