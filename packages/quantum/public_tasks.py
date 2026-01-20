from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
from datetime import datetime

from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from packages.quantum.public_tasks_models import (
    UniverseSyncPayload,
    MorningBriefPayload,
    MiddayScanPayload,
    WeeklyReportPayload,
    ValidationEvalPayload,
    SuggestionsClosePayload,
    SuggestionsOpenPayload,
    LearningIngestPayload,
    StrategyAutotunePayload,
    DEFAULT_STRATEGY_NAME,
)

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    include_in_schema=True
)

def enqueue_job_run(job_name: str, idempotency_key: str, payload: Dict[str, Any], queue_name: str = "otc") -> Dict[str, Any]:
    """
    Helper to create a JobRun and enqueue the runner.

    v4-L5 Ops Console: Enforces pause gate - blocks enqueue when trading is paused.
    """
    # v4-L5: PAUSE GATE - check if trading is paused before enqueue
    from packages.quantum.ops_endpoints import is_trading_paused
    is_paused, pause_reason = is_trading_paused()
    if is_paused:
        raise HTTPException(
            status_code=503,
            detail=f"Trading is paused: {pause_reason or 'No reason provided'}. "
                   f"Job '{job_name}' was not enqueued. Resume trading via /ops/pause."
        )

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
    payload: UniverseSyncPayload = Body(default_factory=UniverseSyncPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:universe_sync"))
):
    """
    Triggers the universe sync job via JobRun system.

    Auth: Requires v4 HMAC signature with scope 'tasks:universe_sync'.
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
    payload: MorningBriefPayload = Body(default_factory=MorningBriefPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:morning_brief"))
):
    """
    Triggers morning brief job.

    Auth: Requires v4 HMAC signature with scope 'tasks:morning_brief'.
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
    payload: MiddayScanPayload = Body(default_factory=MiddayScanPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:midday_scan"))
):
    """
    Triggers midday scan job.

    Auth: Requires v4 HMAC signature with scope 'tasks:midday_scan'.
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
    payload: WeeklyReportPayload = Body(default_factory=WeeklyReportPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:weekly_report"))
):
    """
    Triggers weekly report job.

    Auth: Requires v4 HMAC signature with scope 'tasks:weekly_report'.
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
    payload: ValidationEvalPayload = Body(default_factory=ValidationEvalPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_eval"))
):
    """
    Triggers go-live validation evaluation (Paper/Historical).

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_eval'.

    Payload:
    - mode: 'paper' or 'historical' (default: 'paper')
    - user_id: Optional user UUID to run for specific user
    """
    # Generate idempotency key based on date + params
    today = datetime.now().strftime("%Y-%m-%d")
    mode = payload.mode
    user_id = payload.user_id or "all"

    key = f"{today}-{mode}-{user_id}"
    job_name = "validation_eval"

    # Pass input payload to job
    job_payload = payload.model_dump()

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=key,
        payload=job_payload
    )


# =============================================================================
# Suggestion Generation Tasks (8 AM / 11 AM Chicago)
# =============================================================================


@router.post("/suggestions/close", status_code=202)
async def task_suggestions_close(
    payload: SuggestionsClosePayload = Body(default_factory=SuggestionsClosePayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:suggestions_close"))
):
    """
    8:00 AM Chicago - Generate CLOSE/manage existing positions suggestions.

    Auth: Requires v4 HMAC signature with scope 'tasks:suggestions_close'.

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
        "strategy_name": payload.strategy_name,
        "user_id": payload.user_id,
        "skip_sync": payload.skip_sync,
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{today}-close",
        payload=job_payload
    )


@router.post("/suggestions/open", status_code=202)
async def task_suggestions_open(
    payload: SuggestionsOpenPayload = Body(default_factory=SuggestionsOpenPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:suggestions_open"))
):
    """
    11:00 AM Chicago - Generate OPEN/new positions suggestions.

    Auth: Requires v4 HMAC signature with scope 'tasks:suggestions_open'.

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
        "strategy_name": payload.strategy_name,
        "user_id": payload.user_id,
        "skip_sync": payload.skip_sync,
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{today}-open",
        payload=job_payload
    )


@router.post("/learning/ingest", status_code=202)
async def task_learning_ingest(
    payload: LearningIngestPayload = Body(default_factory=LearningIngestPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:learning_ingest"))
):
    """
    Daily outcome ingestion - Maps executed trades to suggestions for learning.

    Auth: Requires v4 HMAC signature with scope 'tasks:learning_ingest'.

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
        "user_id": payload.user_id,
        "lookback_days": payload.lookback_days,
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=today,
        payload=job_payload
    )


@router.post("/strategy/autotune", status_code=202)
async def task_strategy_autotune(
    payload: StrategyAutotunePayload = Body(default_factory=StrategyAutotunePayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:strategy_autotune"))
):
    """
    Weekly strategy auto-tuning based on live outcomes.

    Auth: Requires v4 HMAC signature with scope 'tasks:strategy_autotune'.

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
        "user_id": payload.user_id,
        "strategy_name": payload.strategy_name,
        "min_samples": payload.min_samples,
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=f"{week}-autotune",
        payload=job_payload
    )
