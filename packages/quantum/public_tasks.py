from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
from datetime import datetime

from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from packages.quantum.policies.go_live_policy import evaluate_go_live_gate
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
    OpsHealthCheckPayload,
    DEFAULT_STRATEGY_NAME,
)

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    include_in_schema=True
)


# ---------------------------------------------------------------------------
# v4-L2: Go-Live Gate Helpers
# ---------------------------------------------------------------------------

# Jobs that require live execution privileges (order execution only)
# Note: broker_sync and other read-only broker jobs are NOT gated here -
# they only respect the pause gate, not the go-live readiness gate.
LIVE_EXEC_JOB_PREFIXES = ("live_",)
LIVE_EXEC_JOB_NAMES = {
    "live_order_submit",
    "live_order_cancel",
    "live_order_retry",
}


def _job_requires_live_privileges(job_name: str) -> bool:
    """
    Check if a job requires live execution privileges.

    Returns True if:
    - job_name starts with "live_" (order execution jobs)
    - job_name is in the explicit LIVE_EXEC_JOB_NAMES set

    Note: broker_sync and other read-only broker jobs do NOT require
    live privileges - they only respect the pause gate.
    """
    if any(job_name.startswith(prefix) for prefix in LIVE_EXEC_JOB_PREFIXES):
        return True
    return job_name in LIVE_EXEC_JOB_NAMES


def _extract_user_id(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extract user_id from job payload.

    Returns None if not present or if value is "all" (batch jobs).
    """
    user_id = payload.get("user_id")
    if not user_id or user_id == "all":
        return None
    return user_id


def _validation_idempotency_key(mode: str, user_id: Optional[str] = None, cadence: str = "daily") -> str:
    """
    Generate idempotency key for validation_eval jobs.

    v4-L1: Supports configurable checkpoint bucket cadence.

    Args:
        mode: Validation mode ('paper' or 'historical')
        user_id: Optional user ID (defaults to 'all' for batch)
        cadence: 'daily' (default) or 'intraday' (hourly buckets)

    Returns:
        Idempotency key string:
        - daily:    '{YYYY-MM-DD}-{mode}-{user_id}'
        - intraday: '{YYYY-MM-DD}-{HH}-{mode}-{user_id}'
    """
    now = datetime.now()
    target = user_id or "all"

    if cadence == "intraday":
        return f"{now.strftime('%Y-%m-%d-%H')}-{mode}-{target}"
    return f"{now.strftime('%Y-%m-%d')}-{mode}-{target}"


def enqueue_job_run(job_name: str, idempotency_key: str, payload: Dict[str, Any], queue_name: str = "otc") -> Dict[str, Any]:
    """
    Helper to create a JobRun and enqueue the runner.

    v4-L5 Ops Console: Enforces pause gate - blocks enqueue when trading is paused.

    PR A (Pause Gate Auditability): When paused, instead of raising HTTP 503:
    - Creates a job_runs record with status='cancelled'
    - Includes cancelled_reason='global_ops_pause' and pause_reason in payload
    - Does NOT enqueue to RQ
    - Returns the cancelled JobRun record for auditability

    v4-L2 Go-Live Gate: For jobs requiring live execution privileges:
    - Checks go-live readiness gate (ops mode + user readiness)
    - If denied: creates cancelled record with cancelled_reason='go_live_gate'
    - If requires_manual_approval (micro_live): cancels auto-live jobs

    This ensures all attempted runs while paused are visible in the admin jobs page.
    """
    # v4-L5: PAUSE GATE - check if trading is paused before enqueue
    from packages.quantum.ops_endpoints import is_trading_paused, get_global_ops_control
    is_paused, pause_reason = is_trading_paused()

    store = JobRunStore()

    if is_paused:
        # PR A: Create auditable cancelled record instead of raising exception
        job_run = store.create_or_get_cancelled(
            job_name=job_name,
            idempotency_key=idempotency_key,
            payload=payload,
            cancelled_reason="global_ops_pause",
            cancelled_detail=pause_reason
        )

        return {
            "job_run_id": job_run["id"],
            "job_name": job_name,
            "idempotency_key": idempotency_key,
            "rq_job_id": None,  # No RQ job was created
            "status": job_run["status"],  # Should be 'cancelled'
            "cancelled_reason": "global_ops_pause",
            "cancelled_detail": pause_reason,
            "pause_reason": pause_reason,  # Backward compat: legacy field
        }

    # v4-L2: GO-LIVE GATE - for jobs requiring live execution privileges
    if _job_requires_live_privileges(job_name):
        target_user_id = _extract_user_id(payload)

        # Live-exec jobs require a specific user_id (not "all" or missing)
        if not target_user_id:
            job_run = store.create_or_get_cancelled(
                job_name=job_name,
                idempotency_key=idempotency_key,
                payload=payload,
                cancelled_reason="go_live_gate",
                cancelled_detail="missing_user_id_for_gate"
            )
            return {
                "job_run_id": job_run["id"],
                "job_name": job_name,
                "idempotency_key": idempotency_key,
                "rq_job_id": None,
                "status": job_run["status"],
                "cancelled_reason": "go_live_gate",
                "cancelled_detail": "missing_user_id_for_gate"
            }

        # Fetch ops state and user readiness
        ops_state = get_global_ops_control()

        # Use admin client (store.client) to avoid RLS issues
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        service = GoLiveValidationService(store.client)
        user_readiness = service.get_or_create_state(target_user_id)

        # Evaluate gate
        decision = evaluate_go_live_gate(ops_state, user_readiness)

        if not decision.allowed:
            job_run = store.create_or_get_cancelled(
                job_name=job_name,
                idempotency_key=idempotency_key,
                payload=payload,
                cancelled_reason="go_live_gate",
                cancelled_detail=decision.reason
            )
            return {
                "job_run_id": job_run["id"],
                "job_name": job_name,
                "idempotency_key": idempotency_key,
                "rq_job_id": None,
                "status": job_run["status"],
                "cancelled_reason": "go_live_gate",
                "cancelled_detail": decision.reason
            }

        # If allowed but requires manual approval (micro_live mode), block auto-live jobs
        if decision.requires_manual_approval:
            job_run = store.create_or_get_cancelled(
                job_name=job_name,
                idempotency_key=idempotency_key,
                payload=payload,
                cancelled_reason="manual_approval_required",
                cancelled_detail=decision.reason
            )
            return {
                "job_run_id": job_run["id"],
                "job_name": job_name,
                "idempotency_key": idempotency_key,
                "rq_job_id": None,
                "status": job_run["status"],
                "cancelled_reason": "manual_approval_required",
                "cancelled_detail": decision.reason
            }

    # Normal flow: create job run and enqueue
    job_run = store.create_or_get(job_name, idempotency_key, payload)

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload={"job_run_id": job_run["id"]},  # Pass ID to runner
        handler_path="packages.quantum.jobs.runner.run_job_run",  # New runner path
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

    v4-L1: Uses checkpoint-based evaluation with configurable cadence.

    Payload:
    - mode: 'paper' or 'historical' (default: 'paper')
    - user_id: Optional user UUID to run for specific user
    - cadence: 'daily' (default) or 'intraday' for hourly buckets
    """
    job_name = "validation_eval"

    # v4-L1: Generate idempotency key with cadence support
    key = _validation_idempotency_key(
        mode=payload.mode,
        user_id=payload.user_id,
        cadence=payload.cadence
    )

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


# =============================================================================
# Ops Tasks
# =============================================================================


@router.post("/ops/health_check", status_code=202)
async def task_ops_health_check(
    payload: OpsHealthCheckPayload = Body(default_factory=OpsHealthCheckPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:ops_health_check"))
):
    """
    Triggers ops health check job.

    Auth: Requires v4 HMAC signature with scope 'tasks:ops_health_check'.

    This task:
    1. Computes full ops health status (data freshness, job status)
    2. Sends alerts for any issues (data stale, job late, failures)
    3. Writes audit event with health snapshot

    Payload options:
    - force: Force run even if recently completed (default: false)
    """
    now = datetime.now()
    job_name = "ops_health_check"
    # Once per hour max (idempotency by hour)
    idempotency_key = now.strftime("%Y-%m-%d-%H")

    job_payload = {
        "timestamp": now.isoformat(),
        "force": payload.force,
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload
    )
