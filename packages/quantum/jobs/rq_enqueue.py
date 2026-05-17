import os
import hashlib
from redis import Redis
from rq import Queue
from fastapi import HTTPException
from typing import Any, Dict, Optional

# Queue names. The "otc" default is left inline in this file's other
# call sites (and across the codebase) — refactor to a DEFAULT_QUEUE
# constant is a separate cleanup. BACKGROUND_QUEUE is added so
# long-running jobs (e.g., iv_historical_backfill, ~8h Phase 1 run)
# can be routed to a separate Railway worker service and not starve
# the primary trading-day pipeline. See docs/backlog.md
# "[2026-05-15] TIER 1 CANDIDATE: worker-queue blocker" for the
# Phase 1 incident that motivated this split.
BACKGROUND_QUEUE = "background"


# Per-job-name RQ work-horse timeouts. The default below (10 minutes)
# is correct for trading-day pipeline jobs that complete in seconds —
# it preserves runaway-detection. Long-running batch operations
# (e.g., historical backfills across the full universe) need
# explicit larger budgets.
#
# Sized 2026-05-17 after Phase 3 attempt (job_run 22516c54-...)
# failed at the default 10m budget. Math from that incident:
# 4 symbols completed in 525s; the 5th was in-flight when the
# 600s ceiling fired. Full 67-symbol projection ~2.5h (avg
# ~131s/symbol); worst-case ~3.9h for deep-chain underlyings.
# 6h budget gives 50-60% headroom over the conservative projection.
DEFAULT_JOB_TIMEOUT = "10m"

JOB_TIMEOUTS: Dict[str, str] = {
    "iv_historical_backfill": "6h",
}


def get_redis() -> Redis:
    """
    Returns a Redis client instance.
    Defaults to localhost if REDIS_URL is not set.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        # Check connection implicitly when using it or we could ping here
        # But for 'get_redis' just returning the client is standard.
        # We'll use a ping to verify connectivity for 'unavailable' check.
        conn = Redis.from_url(redis_url)
        return conn
    except Exception as e:
        print(f"Error connecting to Redis: {e}")
        # We will let the caller handle exceptions or 503 if they try to use it
        raise HTTPException(status_code=503, detail="Redis unavailable")

def get_queue(name: str = "otc") -> Queue:
    """
    Returns an RQ Queue instance.
    """
    try:
        redis_conn = get_redis()
        # Verify connection
        redis_conn.ping()
        return Queue(name, connection=redis_conn)
    except Exception as e:
        print(f"Error getting RQ queue: {e}")
        raise HTTPException(
            status_code=503,
            detail="Task queue unavailable (Redis). Run /dev/run-midday for local debugging or start Redis/worker."
        )

def make_job_id(job_name: str, idempotency_key: str) -> str:
    """
    Creates a deterministic, safe job ID for RQ (no colons).
    Format: {job_name}__{hash}
    """
    raw = f"{job_name}|{idempotency_key}"
    job_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{job_name}__{job_hash}"

def enqueue_idempotent(
    job_name: str,
    idempotency_key: str,
    payload: Dict[str, Any],
    handler_path: str = "packages.quantum.jobs.handlers.universe_sync.run",
    queue_name: str = "otc"
) -> Dict[str, Any]:
    """
    Enqueues a job to RQ with a specific job_id for idempotency.

    Args:
        job_name: Name of the job type (e.g. "universe_sync")
        idempotency_key: Unique key component (e.g. "2023-10-27")
        payload: Dict of arguments to pass to the handler
        handler_path: Python import path string to the handler function
        queue_name: Name of the queue (default "otc")

    Returns:
        Dict with job_id and status
    """
    job_id = make_job_id(job_name, idempotency_key)

    try:
        q = get_queue(queue_name)

        # Enqueue the job
        # We use the string path to the function.
        # job_id ensures idempotency (RQ won't duplicate if job_id exists in registry/queue usually?
        # Actually RQ raises an error or overwrites depending on config, but standard behavior
        # is separate. However, we want to return existing if possible or just push.
        # Redis/RQ doesn't automatically dedupe by job_id if it's already in queue?
        # Actually, if we provide job_id, and it exists, what happens?
        # Let's just enqueue. RQ handles job_id uniqueness by overwriting or erroring?
        # RQ >= 1.0: enqueue(..., job_id=...)

        # Per-job-name timeout (default 10m for trading jobs; extended for
        # batch operations like iv_historical_backfill — see JOB_TIMEOUTS
        # at module top and AMGN timeout diagnostic 2026-05-17 for sizing).
        job_timeout = JOB_TIMEOUTS.get(job_name, DEFAULT_JOB_TIMEOUT)
        job = q.enqueue(
            handler_path,
            kwargs={"payload": payload},
            job_id=job_id,
            job_timeout=job_timeout
        )

        return {
            "status": "queued",
            "job_name": job_name,
            "job_id": job.id,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None
        }

    except HTTPException as e:
        # Pass through specific HTTP exceptions (like 503 from get_queue)
        raise e
    except Exception as e:
        # If it's a "job_id already exists" error or similar, we might want to handle it.
        # But RQ usually allows re-enqueueing or we can catch it.
        print(f"Error enqueueing job {job_id}: {e}")
        # If something else failed (e.g. serialization), we raise 500.
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")
