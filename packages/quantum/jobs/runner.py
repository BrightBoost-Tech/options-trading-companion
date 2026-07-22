import logging
import traceback
import platform
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.jobs.registry import discover_handlers
from packages.quantum.logging_setup import setup_logging

# PR-0 (F-LOG-INFO-DROP): the workers start as a bare `rq worker` CLI, so this
# module import — every job routes through run_job_run — is the earliest hook
# our code gets in a worker process. Idempotent; the canary INFO line lands on
# the first job after each recycle.
setup_logging()

# Startup effective-flag echo (P2 §3): same both-workers hook as the logging
# canary above (covers otc + worker-background; the block lands on the first
# job after a recycle). Fail-soft — never blocks the worker. The BE/uvicorn
# hook is in packages.quantum.api.
from packages.quantum.observability.flag_echo import echo_effective_flags
echo_effective_flags(process="worker")

logger = logging.getLogger(__name__)


def _fold_alert_write_failures(final_result: Dict[str, Any], before: int) -> Dict[str, Any]:
    """A9-F8 (2026-07-07): fold alert-insert losses that occurred DURING this
    handler into the job's result counts, so a run that silently lost alerts
    is visible to the A4 detector (``counts.errors``). Zero-delta runs return
    the result byte-identical. Never raises — a fold bug must not fail a job
    that succeeded."""
    try:
        from packages.quantum.observability.alerts import (
            get_alert_write_failure_count,
        )
        delta = get_alert_write_failure_count() - before
        if delta > 0 and isinstance(final_result, dict):
            counts = final_result.setdefault("counts", {})
            if isinstance(counts, dict):
                counts["alert_write_failures"] = (
                    int(counts.get("alert_write_failures") or 0) + delta
                )
                counts["errors"] = int(counts.get("errors") or 0) + delta
    except Exception:
        logger.warning("alert-write-failure fold failed (non-fatal)", exc_info=True)
    return final_result


def _classify_handler_return(result: Any) -> str:
    """F-A4-1 typed outcome contract (2026-07-11). Classify a handler's RETURN
    (non-raising path) into a terminal job status. Fatals RAISE and are owned by
    run_job_run's except paths — this only sees returns. Returns 'partial' iff
    the handler reports failed units: users_failed>0 OR counts.errors>0 OR a
    truthy top-level 'error' key (a swallowed-fatal RETURN — the 3 known monitors
    now RAISE, so this future-proofs a new one). Designed-false handlers
    (ops_health_check ok:False→now True, paper_auto_execute status:'partial',
    policy_lab_eval status:'error') carry NONE of these → 'succeeded'. 'partial'
    is a REAL terminal status (was mislabeled 'failed_retryable')."""
    if not isinstance(result, dict):
        return "succeeded"
    try:
        if int(result.get("users_failed") or 0) > 0:
            return "partial"
    except (TypeError, ValueError):
        pass
    counts = result.get("counts")
    if isinstance(counts, dict):
        try:
            if int(counts.get("errors") or 0) > 0:
                return "partial"
        except (TypeError, ValueError):
            pass
    if result.get("error"):
        return "partial"
    return "succeeded"


def _build_handler_payload(job: Dict[str, Any], job_run_id: str) -> Dict[str, Any]:
    """Return an isolated handler payload carrying runner-owned provenance.

    ``job_runs.payload`` remains immutable. Only ``suggestions_open`` receives
    the hidden ``_job_run_id`` field required for its attributable experiment
    child. Every other handler receives a byte-identical shallow copy.
    """

    raw = job.get("payload")
    payload = dict(raw) if isinstance(raw, dict) else {}
    if str(job.get("job_name") or "") == "suggestions_open":
        payload.setdefault("_job_run_id", str(job_run_id))
        payload.setdefault("_job_name", "suggestions_open")
    return payload


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
    if job["status"] in ("succeeded", "partial", "cancelled", "dead_lettered"):
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
    # Payload from the DB record, copied and augmented with runner-owned metadata.
    job_payload = _build_handler_payload(job, str(job_run_id))

    # 3. Dispatch to handler
    handlers = discover_handlers()
    handler = handlers.get(job_name)

    if not handler:
        error_info = {"error": f"No handler found for job_name: {job_name}"}
        store.mark_dead_letter(job_run_id, error_info)
        return {"status": "dead_lettered", "error": error_info["error"], "job_run_id": job_run_id}

    # A9-F8: snapshot the process-wide lost-alert counter around the handler
    # so losses DURING this run surface in its result counts.
    try:
        from packages.quantum.observability.alerts import (
            get_alert_write_failure_count,
        )
        _alert_failures_before = get_alert_write_failure_count()
    except Exception:
        _alert_failures_before = None

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
        if _alert_failures_before is not None:
            final_result = _fold_alert_write_failures(
                final_result, _alert_failures_before
            )

        # F-A4-1 typed outcome contract (2026-07-11): derive the terminal status
        # from the handler's return via _classify_handler_return. Fatals RAISE
        # (owned by the except paths below); 'partial' is a REAL terminal status
        # (was mislabeled 'failed_retryable', which the scheduler wrongly retried
        # and the dependency filter missed via a phantom enum).
        _outcome = _classify_handler_return(final_result)
        if _outcome == "partial":
            logger.warning(f"Job {job_run_id} PARTIAL (units failed): {final_result}")
            store.mark_partial_failure(job_run_id, final_result)
            return {"status": "partial", "job_run_id": job_run_id, "result": final_result}
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
