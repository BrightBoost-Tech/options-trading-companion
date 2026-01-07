import logging
import traceback
import platform
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.jobs.registry import discover_handlers

logger = logging.getLogger(__name__)

class RetryableJobError(Exception):
    """
    Raised when a job should be retried.
    """
    pass

class PermanentJobError(Exception):
    """
    Raised when a job should be dead-lettered immediately.
    """
    pass

def run_job_run(payload: Dict[str, Any], ctx: Optional[Any] = None) -> Dict[str, Any]:
    """
    Worker entry point.
    Executes a job run by ID.
    Accepts payload dict containing job_run_id to be compatible with rq_enqueue.enqueue_idempotent.
    """
    job_run_id = None
    if isinstance(payload, dict):
        job_run_id = payload.get("job_run_id")
    elif isinstance(payload, str):
        # Defensive fallback if called with string ID directly (e.g. manual invocation)
        job_run_id = payload

    if not job_run_id:
        logger.error(f"Missing job_run_id in payload: {payload}")
        return {"status": "error", "error": "missing_job_run_id"}

    store = JobRunStore()

    # 1. Load job run
    job = store.get_job(job_run_id)
    if not job:
        logger.error(f"Job run {job_run_id} not found.")
        return {"status": "error", "error": "job_not_found", "job_run_id": job_run_id}

    # If already succeeded or cancelled, skip
    if job["status"] in ("succeeded", "cancelled", "dead_lettered"):
        logger.info(f"Job {job_run_id} is already in terminal state: {job['status']}")
        return {"status": job["status"], "job_run_id": job_run_id, "skipped": True}

    worker_id = f"{platform.node()}-{os.getpid()}"

    # 2. Mark running
    try:
        store.mark_running(job_run_id, worker_id)
    except Exception as e:
        logger.error(f"Failed to mark job {job_run_id} as running: {e}")
        # We might continue, but state tracking is broken. Best to return?
        # If DB is down, we can't do much.
        return {"status": "error", "error": f"mark_running_failed: {str(e)}", "job_run_id": job_run_id}

    job_name = job["job_name"]
    # Payload from the DB record, not the one passed to this function
    job_payload = job.get("payload", {})

    # 3. Dispatch to handler
    handlers = discover_handlers()
    handler = handlers.get(job_name)

    if not handler:
        error_info = {"error": f"No handler found for job_name: {job_name}"}
        store.mark_dead_letter(job_run_id, error_info)
        return {"status": "dead_lettered", "error": error_info["error"], "job_run_id": job_run_id}

    try:
        # Execute handler
        # Safely dispatch to handler, supporting both new (payload-aware) and legacy (no-arg) signatures
        import inspect
        sig = inspect.signature(handler)

        if "payload" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            result = handler(payload=job_payload)
        else:
            # Legacy fallback: call without arguments
            logger.info(f"Handler {job_name} does not accept payload. Calling without arguments.")
            result = handler()

        # 4. Success or Partial Failure
        final_result = result if isinstance(result, dict) else {"result": str(result)}

        # Check for partial failures reported by the handler
        # e.g. {"users_failed": 5, "users_total": 10}
        if isinstance(final_result, dict) and final_result.get("users_failed", 0) > 0:
            logger.warning(f"Job {job_run_id} completed with partial failures: {final_result}")
            store.mark_partial_failure(job_run_id, final_result)
            return {"status": "partial_failure", "job_run_id": job_run_id, "result": final_result}
        else:
            store.mark_succeeded(job_run_id, final_result)
            return {"status": "succeeded", "job_run_id": job_run_id, "result": final_result}

    except RetryableJobError as e:
        # Handle manual retry request
        attempt = (job.get("attempt") or 1) + 1 # It was incremented in mark_running
        max_attempts = job.get("max_attempts") or 5

        if attempt < max_attempts:
            backoff_seconds = 2 ** attempt * 10 # Simple exponential backoff
            run_after = datetime.now() + timedelta(seconds=backoff_seconds)
            store.mark_retryable(job_run_id, {"error": str(e)}, run_after)
            return {"status": "retryable", "job_run_id": job_run_id, "error": str(e), "run_after": str(run_after)}
        else:
            store.mark_dead_letter(job_run_id, {"error": str(e), "detail": "Max attempts exceeded"})
            return {"status": "dead_lettered", "job_run_id": job_run_id, "error": str(e), "detail": "Max attempts exceeded"}

    except PermanentJobError as e:
        store.mark_dead_letter(job_run_id, {"error": str(e)})
        return {"status": "dead_lettered", "job_run_id": job_run_id, "error": str(e)}

    except Exception as e:
        # Generic exception -> Retry or Dead Letter?
        # Usually unexpected errors are retried up to max_attempts.
        logger.error(f"Job {job_run_id} failed: {e}")
        logger.error(traceback.format_exc())

        # We need current attempt count from DB or what we incremented?
        # We incremented it in `mark_running`.
        # But `job` variable holds OLD state.
        current_attempt = (job.get("attempt") or 0) + 1
        max_attempts = job.get("max_attempts") or 5

        if current_attempt < max_attempts:
            backoff_seconds = 2 ** current_attempt * 30 # Slower backoff for generic errors
            run_after = datetime.now() + timedelta(seconds=backoff_seconds)
            store.mark_retryable(job_run_id, {"error": str(e), "traceback": traceback.format_exc()}, run_after)
            return {"status": "retryable", "job_run_id": job_run_id, "error": str(e), "run_after": str(run_after)}
        else:
            store.mark_dead_letter(job_run_id, {"error": str(e), "traceback": traceback.format_exc(), "detail": "Max attempts exceeded"})
            return {"status": "dead_lettered", "job_run_id": job_run_id, "error": str(e), "detail": "Max attempts exceeded"}
