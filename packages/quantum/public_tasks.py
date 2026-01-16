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


# =============================================================================
# Suggestion Generation Tasks (8 AM / 11 AM Chicago)
# =============================================================================

DEFAULT_STRATEGY_NAME = "spy_opt_autolearn_v6"


@router.post("/suggestions/close", status_code=202)
async def task_suggestions_close(
    payload: Optional[Dict[str, Any]] = Body(None),
    authorized: bool = Depends(verify_cron_secret)
):
    """
    8:00 AM Chicago - Generate CLOSE/manage existing positions suggestions.

    This task:
    1. Ensures holdings are up to date (syncs Plaid if connected)
    2. Loads strategy config by name (default: spy_opt_autolearn_v6)
    3. Generates exit suggestions for existing positions
    4. Persists suggestions to trade_suggestions table with window='morning_limit'

    Payload options:
    - strategy_name: Override strategy config name (default: spy_opt_autolearn_v6)
    - user_id: Run for specific user only (default: all users)
    - skip_sync: Skip holdings sync (default: false)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "suggestions_close"

    job_payload = {
        "date": today,
        "type": "close",
        "strategy_name": (payload or {}).get("strategy_name", DEFAULT_STRATEGY_NAME),
        "user_id": (payload or {}).get("user_id"),
        "skip_sync": (payload or {}).get("skip_sync", False),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{today}-close",
        payload=job_payload
    )


@router.post("/suggestions/open", status_code=202)
async def task_suggestions_open(
    payload: Optional[Dict[str, Any]] = Body(None),
    authorized: bool = Depends(verify_cron_secret)
):
    """
    11:00 AM Chicago - Generate OPEN/new positions suggestions.

    This task:
    1. Ensures holdings are up to date (syncs Plaid if connected)
    2. Loads strategy config by name (default: spy_opt_autolearn_v6)
    3. Scans for new entry opportunities
    4. Persists suggestions to trade_suggestions table with window='midday_entry'

    Payload options:
    - strategy_name: Override strategy config name (default: spy_opt_autolearn_v6)
    - user_id: Run for specific user only (default: all users)
    - skip_sync: Skip holdings sync (default: false)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "suggestions_open"

    job_payload = {
        "date": today,
        "type": "open",
        "strategy_name": (payload or {}).get("strategy_name", DEFAULT_STRATEGY_NAME),
        "user_id": (payload or {}).get("user_id"),
        "skip_sync": (payload or {}).get("skip_sync", False),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{today}-open",
        payload=job_payload
    )


@router.post("/learning/ingest", status_code=202)
async def task_learning_ingest(
    payload: Optional[Dict[str, Any]] = Body(None),
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Daily outcome ingestion - Maps executed trades to suggestions for learning.

    This task:
    1. Reads Plaid investment transactions since last run
    2. Matches transactions to trade_suggestions by symbol/direction/time
    3. Inserts outcomes into learning_feedback_loops table
    4. Computes win/loss, slippage proxy, holding time

    Payload options:
    - user_id: Run for specific user only (default: all users)
    - lookback_days: How far back to look for transactions (default: 7)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "learning_ingest"

    job_payload = {
        "date": today,
        "user_id": (payload or {}).get("user_id"),
        "lookback_days": (payload or {}).get("lookback_days", 7),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=today,
        payload=job_payload
    )


@router.post("/strategy/autotune", status_code=202)
async def task_strategy_autotune(
    payload: Optional[Dict[str, Any]] = Body(None),
    authorized: bool = Depends(verify_cron_secret)
):
    """
    Weekly strategy auto-tuning based on live outcomes.

    This task:
    1. Reads learning_feedback_loops for past 30 days
    2. Computes win_rate, avg_pnl per strategy
    3. If performance below threshold, mutates strategy config
    4. Persists new version to strategy_configs table

    Payload options:
    - user_id: Run for specific user only (default: all users)
    - strategy_name: Strategy to tune (default: spy_opt_autolearn_v6)
    - min_samples: Minimum trades required to trigger update (default: 10)
    """
    week = datetime.now().strftime("%Y-W%V")
    job_name = "strategy_autotune"

    job_payload = {
        "week": week,
        "user_id": (payload or {}).get("user_id"),
        "strategy_name": (payload or {}).get("strategy_name", DEFAULT_STRATEGY_NAME),
        "min_samples": (payload or {}).get("min_samples", 10),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{week}-autotune",
        payload=job_payload
    )
