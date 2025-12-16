import time
from typing import Any, Dict
from packages.quantum.services.plaid_history_service import PlaidHistoryService
from packages.quantum import plaid_service
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "plaid_backfill_history"

def run(payload: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    start_time = time.time()
    notes = []
    counts = {}

    # Extract payload parameters
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    if not start_date or not end_date:
        raise PermanentJobError("Missing start_date or end_date in payload")

    try:
        client = get_admin_client()
        active_users = get_active_user_ids(client)

        # Instantiate service using existing plaid_service client
        service = PlaidHistoryService(plaid_service.client, client)

        async def process_users():
            user_counts = {}
            for uid in active_users:
                try:
                    count = await service.backfill_snapshots(uid, start_date, end_date)
                    user_counts[uid] = count
                except Exception as e:
                    notes.append(f"Failed for user {uid}: {str(e)}")
                    user_counts[uid] = -1
            return user_counts

        counts = run_async(process_users())

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
        raise RetryableJobError(f"Plaid backfill job failed: {e}")
