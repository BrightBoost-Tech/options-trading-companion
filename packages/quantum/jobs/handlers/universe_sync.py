import time
from typing import Any, Dict
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "universe_sync"

def run(payload: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Executes the universe sync job.
    """
    start_time = time.time()
    notes = []

    try:
        client = get_admin_client()
        service = UniverseService(client)

        service.sync_universe()
        notes.append("Universe synced")

        service.update_metrics()
        notes.append("Metrics updated")

        timing_ms = (time.time() - start_time) * 1000
        return {
            "ok": True,
            "counts": {"synced": 1}, # Exact count difficult without service return val
            "timing_ms": timing_ms,
            "notes": notes
        }

    except ValueError as e:
        # Config errors
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        # Network or other transient errors
        raise RetryableJobError(f"Universe sync failed: {e}")
