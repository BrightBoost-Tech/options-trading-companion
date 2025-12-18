from fastapi import APIRouter, Header, HTTPException, Request, Depends
from typing import Optional
import os
import secrets
from datetime import datetime

from packages.quantum.jobs.rq_enqueue import enqueue_idempotent

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

@router.post("/universe/sync", status_code=202)
async def task_universe_sync(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers the universe sync job via Redis/RQ.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "universe_sync"

    # Enqueue to 'otc' queue
    # Handler: packages.quantum.jobs.handlers.universe_sync.run
    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today},
        handler_path="packages.quantum.jobs.handlers.universe_sync.run",
        queue_name="otc"
    )

    return result

@router.post("/morning-brief", status_code=202)
async def task_morning_brief(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Stub for morning brief task. Enqueues job only.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "morning_brief"

    # Using a placeholder handler or the sync one for now since logic isn't ported
    # But prompt says "Stub endpoints (enqueue only, no handler yet)"
    # We'll use a dummy path or just enqueue it. RQ will fail if handler missing on worker side,
    # but the API response will be 202.

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today},
        handler_path="packages.quantum.jobs.handlers.morning_brief.run", # Does not exist yet
        queue_name="otc"
    )

    return result

@router.post("/midday-scan", status_code=202)
async def task_midday_scan(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Stub for midday scan task.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "midday_scan"

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=today,
        payload={"date": today},
        handler_path="packages.quantum.jobs.handlers.midday_scan.run",
        queue_name="otc"
    )

    return result

@router.post("/weekly-report", status_code=202)
async def task_weekly_report(
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Stub for weekly report task.
    """
    # Weekly bucket
    week = datetime.now().strftime("%Y-W%V")
    job_name = "weekly_report"

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=week,
        payload={"week": week},
        handler_path="packages.quantum.jobs.handlers.weekly_report.run",
        queue_name="otc"
    )

    return result
