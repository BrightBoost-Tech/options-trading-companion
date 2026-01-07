from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
from datetime import datetime

from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.security.cron_auth import verify_cron_secret

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    include_in_schema=True
)

def enqueue_job_run(job_name: str, idempotency_key: str, payload: Dict[str, Any], queue_name: str = "otc") -> Dict[str, Any]:
    """
    Helper to create a JobRun and enqueue the runner.
    """
    store = JobRunStore()

    # 1. Create or Get DB record
    job_run = store.create_or_get(job_name, idempotency_key, payload)

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

@router.post("/validation/eval", status_code=202)
async def task_validation_eval(
    payload: Optional[Dict[str, Any]] = Body(None),
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Triggers go-live validation evaluation (Paper/Historical).
    Payload can specify mode='paper' and optional user_id.
    """
    # Generate idempotency key based on date + params
    today = datetime.now().strftime("%Y-%m-%d")
    mode = payload.get("mode", "paper") if payload else "paper"
    user_id = payload.get("user_id", "all") if payload else "all"

    key = f"{today}-{mode}-{user_id}"
    job_name = "validation_eval"

    # Pass input payload to job
    job_payload = payload or {"mode": "paper"}

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=key,
        payload=job_payload
    )
