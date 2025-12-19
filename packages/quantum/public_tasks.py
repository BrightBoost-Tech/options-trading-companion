from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
from datetime import datetime

from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from packages.quantum.jobs.job_runs import JobRunStore

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    include_in_schema=True
)

async def verify_cron_secret(x_cron_secret: Optional[str] = Header(None)):
    """
    Verifies that the X-Cron-Secret header matches the CRON_SECRET env var.
    Uses constant-time comparison to prevent timing attacks.
    """
    expected_secret = os.getenv("CRON_SECRET")

    if not expected_secret:
        # Configuration error: CRON_SECRET not set on server
        print("Error: CRON_SECRET environment variable not set.")
        raise HTTPException(status_code=500, detail="Server misconfiguration: CRON_SECRET missing")

    if x_cron_secret is None or not secrets.compare_digest(x_cron_secret, expected_secret):
        # Auth failure
        raise HTTPException(status_code=401, detail="Invalid Cron Secret")

    return True

def enqueue_job_run(job_name: str, idempotency_key: str, payload: Dict[str, Any], queue_name: str = "otc") -> Dict[str, Any]:
    """
    Helper to create a JobRun and enqueue the runner.
    """
    store = JobRunStore()

    # 1. Create or Get DB record
    job_run = store.create_or_get(job_name, idempotency_key, payload)

    # 2. Enqueue the runner via RQ
    # We use the same idempotency key for RQ to prevent double enqueueing in Redis if possible,
    # or just rely on DB state.
    # But `enqueue_idempotent` uses job_name + idempotency_key to generate RQ job_id.
    # We should stick to that.

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload={"job_run_id": job_run["id"]}, # Pass ID to runner
        handler_path="packages.quantum.jobs.runner.run_job_run", # New runner path
        queue_name=queue_name
    )

    return {
        "job_run_id": job_run["id"],
        "job_name": job_name,
        "idempotency_key": idempotency_key,
        "rq_job_id": result.get("job_id"),
        "status": job_run["status"]
    }


@router.post("/universe/sync", status_code=202)
async def task_universe_sync(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers the universe sync job via JobRun system.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "universe_sync"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today}
    )

@router.post("/morning-brief", status_code=202)
async def task_morning_brief(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers morning brief job.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "morning_brief"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today}
    )

@router.post("/midday-scan", status_code=202)
async def task_midday_scan(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers midday scan job.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "midday_scan"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today}
    )

@router.post("/weekly-report", status_code=202)
async def task_weekly_report(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers weekly report job.
    """
    # Weekly bucket
    week = datetime.now().strftime("%Y-W%V")
    job_name = "weekly_report"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=week,
        payload={"week": week}
    )

# --- Visibility Endpoints ---

@router.get("/runs", tags=["jobs"])
async def list_job_runs(
    status: Optional[str] = None,
    job_name: Optional[str] = None,
    limit: int = 50,
    authorized: bool = Depends(verify_cron_secret)
):
    """
    List job runs with optional filtering.
    """
    store = JobRunStore()
    query = store.client.table("job_runs").select("*").order("created_at", desc=True).limit(limit)

    if status:
        query = query.eq("status", status)
    if job_name:
        query = query.eq("job_name", job_name)

    res = query.execute()
    return res.data

@router.get("/runs/{job_run_id}", tags=["jobs"])
async def get_job_run(
    job_run_id: str,
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Get details of a specific job run.
    """
    store = JobRunStore()
    job = store.get_job(job_run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job run not found")
    return job

@router.post("/runs/{job_run_id}/retry", tags=["jobs"])
async def retry_job_run(
    job_run_id: str,
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Manually retry a failed or dead-lettered job.
    """
    store = JobRunStore()
    job = store.get_job(job_run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job run not found")

    # Only allow retry if terminal state? Or anytime?
    # Ideally from failed/dead_lettered.
    if job["status"] not in ("failed_retryable", "dead_lettered", "cancelled", "succeeded"):
        # If it's queued or running, we shouldn't intervene?
        # Maybe force retry if stuck?
        # Let's allow it but warn or reset.
        pass

    # Reset state to queued?
    # Or use requeue RPC?
    # RPC `requeue_job_run` sets it to `failed_retryable` with a run_after.
    # We want to run it NOW.
    # So we can update status to 'queued' and run_after to now, and attempt to 0 (or keep incrementing?).
    # If we reset attempt, we risk infinite loops if it keeps failing.
    # But manual retry implies user intervention.
    # Let's just update to 'queued' and clear error.

    store.client.table("job_runs").update({
        "status": "queued",
        "run_after": datetime.now().isoformat(),
        "error": None,
        "result": None,
        "locked_by": None,
        "locked_at": None,
        # Reset attempts? Or keep history?
        # If we keep attempts, it might hit max_attempts again immediately.
        # Manual retry usually resets the counter or ignores it.
        # But our runner checks attempt < max_attempts.
        # So we must increase max_attempts or reset attempt count.
        # Let's reset attempt to 0 to give it a fresh start.
        "attempt": 0
    }).eq("id", job_run_id).execute()

    # Also need to kick the runner via RQ again!
    # Because `claim_job_run` is poll based, but we rely on RQ pushing.
    # So we must enqueue the runner again.

    payload = {"job_run_id": job_run_id}

    # We need a new RQ ID? Or reuse?
    # `enqueue_idempotent` uses job_name+key.
    # If we use same key, RQ might dedupe if still in queue?
    # If it's finished in RQ, we can re-enqueue.

    result = enqueue_idempotent(
        job_name=job["job_name"],
        idempotency_key=job["idempotency_key"], # Reuse same key
        payload=payload,
        handler_path="packages.quantum.jobs.runner.run_job_run"
    )

    return {"status": "retried", "rq_job_id": result.get("job_id")}
