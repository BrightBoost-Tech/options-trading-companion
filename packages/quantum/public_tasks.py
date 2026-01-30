from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

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
    PaperAutoExecutePayload,
    PaperAutoClosePayload,
    ValidationShadowEvalPayload,
    ValidationCohortEvalPayload,
    ValidationAutopromoteCohortPayload,
    ValidationPreflightPayload,
    ValidationInitWindowPayload,
    PaperSafetyCloseOnePayload,
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
    PR567: Uses UTC for consistent bucket boundaries across timezones.

    Args:
        mode: Validation mode ('paper' or 'historical')
        user_id: Optional user ID (defaults to 'all' for batch)
        cadence: 'daily' (default) or 'intraday' (hourly buckets)

    Returns:
        Idempotency key string (UTC-based):
        - daily:    '{YYYY-MM-DD}-{mode}-{user_id}'
        - intraday: '{YYYY-MM-DD}-{HH}-{mode}-{user_id}'
    """
    now = datetime.now(timezone.utc)
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


# =============================================================================
# Paper Autopilot Tasks (v4-L1C)
# =============================================================================


def _paper_autopilot_idempotency_key(task_type: str, user_id: str) -> str:
    """
    Generate UTC-based idempotency key for paper autopilot tasks.

    Format: {YYYY-MM-DD}-paper-auto-{task_type}-{user_id}
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date}-paper-auto-{task_type}-{user_id}"


def _check_paper_autopilot_gates(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Check paper autopilot gating conditions.

    Returns None if all gates pass, otherwise returns error response dict.

    Gates checked:
    1. PAPER_AUTOPILOT_ENABLED must be "1"
    2. ops_state.mode must be "paper"
    3. Pause gate (handled by enqueue_job_run, but we check mode first)
    """
    import os
    from packages.quantum.ops_endpoints import get_global_ops_control

    # Gate 1: Autopilot enabled
    if os.environ.get("PAPER_AUTOPILOT_ENABLED", "0") != "1":
        return {
            "status": "skipped",
            "reason": "autopilot_disabled",
            "detail": "PAPER_AUTOPILOT_ENABLED is not set to '1'"
        }

    # Gate 2: Paper mode only
    ops_state = get_global_ops_control()
    mode = ops_state.get("mode", "paper")

    if mode != "paper":
        return {
            "status": "cancelled",
            "reason": "mode_is_paper_only",
            "detail": f"Paper autopilot requires mode='paper', current mode='{mode}'"
        }

    return None


@router.post("/paper/auto-execute", status_code=202)
async def task_paper_auto_execute(
    payload: PaperAutoExecutePayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_auto_execute"))
):
    """
    Automatically execute top executable suggestions for paper trading.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_auto_execute'.

    v4-L1C: Part of Phase-3 streak automation.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires PAPER_AUTOPILOT_ENABLED=1

    Behavior:
    1. Fetches today's executable suggestions
    2. Selects top N (PAPER_AUTOPILOT_MAX_TRADES_PER_DAY, default 3)
    3. Filters by min score (PAPER_AUTOPILOT_MIN_SCORE, default 0.0)
    4. Deduplicates against already-executed today
    5. Stages and executes via paper trading service
    """
    user_id = payload.user_id

    # Check autopilot gates (enabled, paper mode)
    gate_error = _check_paper_autopilot_gates(user_id)
    if gate_error:
        return gate_error

    job_name = "paper_auto_execute"
    idempotency_key = _paper_autopilot_idempotency_key("execute", user_id)

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # enqueue_job_run handles pause gate
    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload
    )


@router.post("/paper/auto-close", status_code=202)
async def task_paper_auto_close(
    payload: PaperAutoClosePayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_auto_close"))
):
    """
    Automatically close paper positions before checkpoint.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_auto_close'.

    v4-L1C: Part of Phase-3 streak automation.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires PAPER_AUTOPILOT_ENABLED=1

    Behavior:
    1. Fetches open paper positions
    2. Checks positions already closed today (for deduplication)
    3. Closes up to PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY (default 1)
    4. Uses oldest-first ordering for determinism
    5. Creates learning outcomes for checkpoint validation
    """
    user_id = payload.user_id

    # Check autopilot gates (enabled, paper mode)
    gate_error = _check_paper_autopilot_gates(user_id)
    if gate_error:
        return gate_error

    job_name = "paper_auto_close"
    idempotency_key = _paper_autopilot_idempotency_key("close", user_id)

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # enqueue_job_run handles pause gate
    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload
    )


# =============================================================================
# Shadow Checkpoint Tasks (v4-L1D)
# =============================================================================


# Default cohorts if SHADOW_COHORTS_JSON is not set
DEFAULT_SHADOW_COHORTS = [
    {
        "name": "baseline_21d_10pct",
        "paper_window_days": 21,
        "target_return_pct": 0.10,
        "fail_fast_drawdown_pct": -0.03,
        "fail_fast_return_pct": -0.02
    },
    {
        "name": "conservative_21d_8pct",
        "paper_window_days": 21,
        "target_return_pct": 0.08,
        "fail_fast_drawdown_pct": -0.025,
        "fail_fast_return_pct": -0.015
    },
    {
        "name": "aggressive_14d_10pct",
        "paper_window_days": 14,
        "target_return_pct": 0.10,
        "fail_fast_drawdown_pct": -0.03,
        "fail_fast_return_pct": -0.02
    }
]


def _validation_shadow_idempotency_key(
    user_id: str,
    cadence: str,
    cohort_name: Optional[str] = None
) -> str:
    """
    Generate UTC-based idempotency key for shadow checkpoint tasks.

    Format depends on cadence:
    - intraday: {YYYY-MM-DD-HH}-shadow-{cohort_or_single}-{user_id}
    - daily:    {YYYY-MM-DD}-shadow-{cohort_or_single}-{user_id}

    Must include "shadow" to avoid collision with official validation_eval keys.
    """
    now = datetime.now(timezone.utc)
    cohort_part = cohort_name or "single"

    if cadence == "intraday":
        return f"{now.strftime('%Y-%m-%d-%H')}-shadow-{cohort_part}-{user_id}"
    return f"{now.strftime('%Y-%m-%d')}-shadow-{cohort_part}-{user_id}"


def _check_shadow_checkpoint_gates(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Check shadow checkpoint gating conditions.

    Returns None if all gates pass, otherwise returns error response dict.

    Gates checked:
    1. SHADOW_CHECKPOINT_ENABLED must be "1"
    2. ops_state.mode must be "paper"
    3. Pause gate (handled by enqueue_job_run, but we check mode first)
    """
    from packages.quantum.ops_endpoints import get_global_ops_control

    # Gate 1: Shadow enabled
    if os.environ.get("SHADOW_CHECKPOINT_ENABLED", "0") != "1":
        return {
            "status": "skipped",
            "reason": "shadow_disabled",
            "detail": "SHADOW_CHECKPOINT_ENABLED is not set to '1'"
        }

    # Gate 2: Paper mode only
    ops_state = get_global_ops_control()
    mode = ops_state.get("mode", "paper")

    if mode != "paper":
        return {
            "status": "cancelled",
            "reason": "mode_is_paper_only",
            "detail": f"Shadow checkpoint requires mode='paper', current mode='{mode}'"
        }

    return None


def _get_shadow_cohorts() -> list:
    """
    Get shadow cohort configurations from environment or use defaults.

    Reads SHADOW_COHORTS_JSON env var as JSON list, falls back to DEFAULT_SHADOW_COHORTS.
    """
    import json

    cohorts_json = os.environ.get("SHADOW_COHORTS_JSON", "")
    if cohorts_json:
        try:
            cohorts = json.loads(cohorts_json)
            if isinstance(cohorts, list) and len(cohorts) > 0:
                return cohorts
        except (json.JSONDecodeError, TypeError):
            pass  # Fall back to defaults

    return DEFAULT_SHADOW_COHORTS


@router.post("/validation/shadow-eval", status_code=200)
async def task_validation_shadow_eval(
    payload: ValidationShadowEvalPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_shadow_eval"))
):
    """
    Run a shadow checkpoint evaluation (side-effect free).

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_shadow_eval'.

    v4-L1D: Computes checkpoint metrics WITHOUT mutating go-live streak state.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires SHADOW_CHECKPOINT_ENABLED=1

    Returns:
    - return_pct, max_drawdown_pct, progress, target_return_now
    - would_pass, would_fail_fast, reason
    - shadow=True (always)
    """
    user_id = payload.user_id
    cadence = payload.cadence

    # Check shadow gates (enabled, paper mode)
    gate_error = _check_shadow_checkpoint_gates(user_id)
    if gate_error:
        return gate_error

    # Get cadence from env (can be overridden)
    effective_cadence = os.environ.get("SHADOW_CHECKPOINT_CADENCE", cadence)

    # Run shadow evaluation directly (synchronous, no job queue needed)
    # Shadow eval is fast and side-effect free, so we can run it inline
    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        supabase = get_admin_client()
        service = GoLiveValidationService(supabase)

        result = service.eval_paper_forward_checkpoint_shadow(
            user_id=user_id,
            cadence=effective_cadence,
            cohort_name=None
        )

        return {
            "status": result.get("status", "ok"),
            "user_id": user_id,
            "as_of": datetime.now(timezone.utc).isoformat(),
            **result
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
            "shadow": True
        }


# =============================================================================
# Auto-Promote Guardrail Task (v4-L1E)
# =============================================================================


def _check_autopromote_gates(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Check autopromote gating conditions.

    Returns None if all gates pass, otherwise returns error response dict.

    Gates checked:
    1. AUTOPROMOTE_ENABLED must be "1"
    2. ops_state.mode must be "paper"
    3. ops_state.paused must be false
    """
    from packages.quantum.ops_endpoints import get_global_ops_control

    # Gate 1: Autopromote enabled
    if os.environ.get("AUTOPROMOTE_ENABLED", "0") != "1":
        return {
            "status": "skipped",
            "reason": "autopromote_disabled",
            "detail": "AUTOPROMOTE_ENABLED is not set to '1'"
        }

    # Gate 2: Paper mode only
    ops_state = get_global_ops_control()
    mode = ops_state.get("mode", "paper")

    if mode != "paper":
        return {
            "status": "cancelled",
            "reason": "mode_is_paper_only",
            "detail": f"Autopromote requires mode='paper', current mode='{mode}'"
        }

    # Gate 3: Not paused
    if ops_state.get("paused", False):
        return {
            "status": "cancelled",
            "reason": "paused_globally",
            "detail": "Trading is paused globally"
        }

    return None


def _get_cohort_overrides_by_name(cohort_name: str) -> Optional[Dict[str, Any]]:
    """
    Look up cohort configuration by name from SHADOW_COHORTS_JSON or defaults.

    Returns the override dict (paper_window_days, target_return_pct, etc.)
    or None if cohort not found.
    """
    cohorts = _get_shadow_cohorts()
    for cohort in cohorts:
        if cohort.get("name") == cohort_name:
            # Build overrides dict (exclude paper_checkpoint_target per spec)
            overrides = {}
            if "paper_window_days" in cohort:
                overrides["paper_window_days"] = cohort["paper_window_days"]
            if "target_return_pct" in cohort:
                overrides["target_return_pct"] = cohort["target_return_pct"]
            if "fail_fast_drawdown_pct" in cohort:
                overrides["fail_fast_drawdown_pct"] = cohort["fail_fast_drawdown_pct"]
            if "fail_fast_return_pct" in cohort:
                overrides["fail_fast_return_pct"] = cohort["fail_fast_return_pct"]
            return overrides
    return None


@router.post("/validation/autopromote-cohort", status_code=200)
async def task_validation_autopromote_cohort(
    payload: ValidationAutopromoteCohortPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_autopromote_cohort"))
):
    """
    Evaluate and potentially auto-promote a cohort's parameters.

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_autopromote_cohort'.

    v4-L1E: Auto-promote guardrail - adopt best cohort policy after 3-day proof.

    Promotion criteria:
    - Same winner cohort for 3 consecutive trading-day buckets
    - No fail-fast on any of those days
    - Non-decreasing return_pct across the 3 days (today >= yesterday >= day-2)

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires AUTOPROMOTE_ENABLED=1

    Returns:
    - promoted: Boolean indicating if promotion occurred
    - cohort: Name of promoted cohort (if promoted)
    - overrides: The override dict applied (if promoted)
    - reason: Explanation of decision
    """
    import json

    user_id = payload.user_id

    # Check autopromote gates
    gate_error = _check_autopromote_gates(user_id)
    if gate_error:
        return gate_error

    # Idempotency key
    bucket_date = datetime.now(timezone.utc).date().isoformat()
    idempotency_key = f"{bucket_date}-autopromote-{user_id}"

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        supabase = get_admin_client()

        # Get required days from env (default 3)
        required_days = int(os.environ.get("AUTOPROMOTE_REQUIRED_DAYS", "3"))
        require_nondecreasing = os.environ.get("AUTOPROMOTE_REQUIRE_NONDECREASING_PROFIT", "1") == "1"

        # 1. Read last N records from shadow_cohort_daily
        history_res = supabase.table("shadow_cohort_daily") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("bucket_date", desc=True) \
            .limit(required_days) \
            .execute()

        history = history_res.data or []

        if len(history) < required_days:
            return {
                "status": "ok",
                "promoted": False,
                "reason": "insufficient_history",
                "history_count": len(history),
                "required_days": required_days,
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

        # 2. Check promotion criteria
        # All must have same winner_cohort
        winner_cohorts = [h["winner_cohort"] for h in history]
        if len(set(winner_cohorts)) != 1:
            return {
                "status": "ok",
                "promoted": False,
                "reason": "winners_differ",
                "winners": winner_cohorts,
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

        cohort_name = winner_cohorts[0]

        # All must have would_fail_fast == False
        fail_fast_flags = [h["winner_would_fail_fast"] for h in history]
        if any(fail_fast_flags):
            return {
                "status": "ok",
                "promoted": False,
                "reason": "fail_fast_triggered",
                "cohort": cohort_name,
                "fail_fast_days": [h["bucket_date"] for h in history if h["winner_would_fail_fast"]],
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

        # Check non-decreasing profit (oldest to newest)
        # History is DESC order, so reverse for chronological
        chronological = list(reversed(history))
        returns = [h["winner_return_pct"] for h in chronological]

        if require_nondecreasing:
            is_nondecreasing = all(returns[i] <= returns[i+1] for i in range(len(returns)-1))
            if not is_nondecreasing:
                return {
                    "status": "ok",
                    "promoted": False,
                    "reason": "profit_not_nondecreasing",
                    "cohort": cohort_name,
                    "returns": returns,
                    "user_id": user_id,
                    "idempotency_key": idempotency_key
                }

        # 3. Check current policy (anti-churn)
        service = GoLiveValidationService(supabase)
        state = service.get_or_create_state(user_id)
        current_cohort = state.get("paper_forward_policy_cohort")

        if current_cohort == cohort_name:
            return {
                "status": "ok",
                "promoted": False,
                "reason": "already_promoted",
                "cohort": cohort_name,
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

        # 4. Look up cohort overrides
        overrides = _get_cohort_overrides_by_name(cohort_name)
        if not overrides:
            return {
                "status": "ok",
                "promoted": False,
                "reason": "cohort_not_found",
                "cohort": cohort_name,
                "user_id": user_id,
                "idempotency_key": idempotency_key
            }

        # 5. Promote: Update v3_go_live_state
        now = datetime.now(timezone.utc)
        supabase.table("v3_go_live_state").update({
            "paper_forward_policy": json.dumps(overrides),
            "paper_forward_policy_source": "auto_promote",
            "paper_forward_policy_set_at": now.isoformat(),
            "paper_forward_policy_cohort": cohort_name,
            "updated_at": now.isoformat()
        }).eq("user_id", user_id).execute()

        logger.info(f"Auto-promoted cohort '{cohort_name}' for user {user_id}: {overrides}")

        return {
            "status": "ok",
            "promoted": True,
            "cohort": cohort_name,
            "overrides": overrides,
            "proof_days": required_days,
            "returns": returns,
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "promoted_at": now.isoformat()
        }

    except Exception as e:
        logger.error(f"Autopromote failed for user {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id
        }


# =============================================================================
# 10-Day Readiness Hardening Tasks (v4-L1F)
# =============================================================================


def _check_readiness_hardening_gates(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Check readiness hardening gating conditions.

    Returns None if all gates pass, otherwise returns error response dict.

    Gates checked:
    1. ops_state.mode must be "paper"
    2. ops_state.paused must be false
    """
    from packages.quantum.ops_endpoints import get_global_ops_control

    # Gate 1: Paper mode only
    ops_state = get_global_ops_control()
    mode = ops_state.get("mode", "paper")

    if mode != "paper":
        return {
            "status": "cancelled",
            "reason": "mode_is_paper_only",
            "detail": f"Readiness hardening requires mode='paper', current mode='{mode}'"
        }

    # Gate 2: Not paused
    if ops_state.get("paused", False):
        return {
            "status": "cancelled",
            "reason": "paused_globally",
            "detail": "Trading is paused globally"
        }

    return None


def _readiness_hardening_idempotency_key(task_type: str, user_id: str) -> str:
    """
    Generate UTC-based idempotency key for readiness hardening tasks.

    Format: {YYYY-MM-DD}-{task_type}-{user_id}
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date}-{task_type}-{user_id}"


@router.post("/validation/preflight", status_code=200)
async def task_validation_preflight(
    payload: ValidationPreflightPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_preflight"))
):
    """
    v4-L1F: Compute and return preflight summary for daily checkpoint.

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_preflight'.

    Returns a layman-friendly summary showing:
    - outcomes_today_count, open_positions_count
    - return_pct, target_return_now, margin_to_target
    - max_drawdown_pct, fail_fast threshold
    - on_track boolean and reason
    - time until official checkpoint

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode
    - Respects pause gate
    - Read-only (no state mutation)
    """
    user_id = payload.user_id

    # Check gates
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        supabase = get_admin_client()
        service = GoLiveValidationService(supabase)

        snapshot = service.compute_forward_checkpoint_snapshot(user_id)

        return {
            "status": snapshot.get("status", "ok"),
            "user_id": user_id,
            "as_of": datetime.now(timezone.utc).isoformat(),
            **snapshot
        }

    except Exception as e:
        logger.error(f"Preflight failed for user {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id
        }


@router.post("/validation/init-window", status_code=200)
async def task_validation_init_window(
    payload: ValidationInitWindowPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_init_window"))
):
    """
    v4-L1F: Ensure forward checkpoint window is initialized.

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_init_window'.

    Validates/repairs paper_window_start and paper_window_end BEFORE Day 1
    of the test. Does NOT affect streak or readiness.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode
    - Respects pause gate
    - Idempotent once per day (UTC bucket)
    """
    user_id = payload.user_id

    # Check gates
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    # Idempotency check
    bucket_date = datetime.now(timezone.utc).date().isoformat()
    idempotency_key = _readiness_hardening_idempotency_key("init-window", user_id)

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        supabase = get_admin_client()
        service = GoLiveValidationService(supabase)

        result = service.ensure_forward_window_initialized(user_id)

        return {
            **result,
            "idempotency_key": idempotency_key,
            "bucket_date": bucket_date,
            "as_of": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Init window failed for user {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
            "idempotency_key": idempotency_key
        }


@router.post("/paper/safety-close-one", status_code=200)
async def task_paper_safety_close_one(
    payload: PaperSafetyCloseOnePayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_safety_close_one"))
):
    """
    v4-L1F: Safety net to guarantee at least one paper close outcome before checkpoint.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_safety_close_one'.

    Behavior:
    - If there is at least one open paper position, closes exactly one
      (deterministically: oldest opened_at, then position_id asc)
    - If no open positions exist, no-ops without error
    - Idempotent once per day (UTC bucket)

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode
    - Respects pause gate
    """
    user_id = payload.user_id

    # Check gates
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    # Idempotency: check if already closed today
    bucket_date = datetime.now(timezone.utc).date().isoformat()
    idempotency_key = _readiness_hardening_idempotency_key("safety-close", user_id)

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client

        supabase = get_admin_client()

        # Check if we already ran today by looking for a safety close outcome
        # We'll check learning_trade_outcomes_v3 for a close with safety_close tag
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        existing_safety_close = supabase.table("learning_trade_outcomes_v3") \
            .select("closed_at") \
            .eq("user_id", user_id) \
            .eq("is_paper", True) \
            .gte("closed_at", today_start.isoformat()) \
            .lt("closed_at", today_end.isoformat()) \
            .limit(1) \
            .execute()

        # For strict idempotency, we'll track via a job_runs check
        # But for simplicity, we'll just check if there's at least one outcome today
        outcomes_today = existing_safety_close.data or []
        if len(outcomes_today) > 0:
            return {
                "status": "skipped",
                "reason": "outcome_exists_today",
                "outcomes_today_count": len(outcomes_today),
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "closed": 0
            }

        # 1. Get user's paper portfolios
        p_res = supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
        portfolio_ids = [p["id"] for p in (p_res.data or [])]

        if not portfolio_ids:
            return {
                "status": "ok",
                "reason": "no_portfolio",
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "closed": 0
            }

        # 2. Fetch open paper positions - deterministic sort: created_at asc, id asc
        pos_res = supabase.table("paper_positions") \
            .select("*") \
            .in_("portfolio_id", portfolio_ids) \
            .order("created_at", desc=False) \
            .order("id", desc=False) \
            .limit(1) \
            .execute()

        positions = pos_res.data or []

        if not positions:
            return {
                "status": "ok",
                "reason": "no_open_positions",
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "closed": 0
            }

        # 3. Close the oldest position
        position_to_close = positions[0]
        position_id = position_to_close["id"]

        logger.info(f"Safety close: closing position {position_id} for user {user_id}")

        # Use the paper close endpoint logic
        from packages.quantum.paper_endpoints import (
            get_supabase,
            get_analytics_service,
            _process_orders_for_user,
            _stage_order_internal,
        )
        from packages.quantum.models import TradeTicket

        analytics = get_analytics_service()

        # Construct closing ticket
        qty = float(position_to_close["quantity"])
        side = "sell" if qty > 0 else "buy"

        ticket = TradeTicket(
            symbol=position_to_close["symbol"],
            quantity=abs(qty),
            order_type="market",
            strategy_type=position_to_close.get("strategy_key", "").split("_")[-1] if position_to_close.get("strategy_key") else "safety_close",
            source_engine="safety_close",
            legs=[
                {"symbol": position_to_close["symbol"], "action": side, "quantity": abs(qty)}
            ]
        )

        # Set source_ref_id for context
        if position_to_close.get("suggestion_id"):
            ticket.source_ref_id = position_to_close.get("suggestion_id")

        # Stage and execute
        order_id = _stage_order_internal(
            supabase,
            analytics,
            user_id,
            ticket,
            position_to_close["portfolio_id"],
            position_id=position_id,
            trace_id_override=position_to_close.get("trace_id")
        )

        _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

        # Verify closure
        order_res = supabase.table("paper_orders").select("status").eq("id", order_id).single().execute()
        order_status = order_res.data.get("status") if order_res.data else "unknown"

        return {
            "status": "ok",
            "closed": 1,
            "position_id": position_id,
            "order_id": order_id,
            "order_status": order_status,
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "bucket_date": bucket_date
        }

    except Exception as e:
        logger.error(f"Safety close failed for user {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "closed": 0
        }


@router.post("/validation/cohort-eval", status_code=200)
async def task_validation_cohort_eval(
    payload: ValidationCohortEvalPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_cohort_eval"))
):
    """
    Run multiple shadow evaluations with different cohort configurations.

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_cohort_eval'.

    v4-L1D: Extracts more learning per day by testing multiple threshold configs.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires SHADOW_CHECKPOINT_ENABLED=1

    Cohorts are read from SHADOW_COHORTS_JSON env var, or use defaults if not set.

    Returns:
    - results: Array of cohort results sorted by (would_pass desc, margin_to_target desc)
    - best: Top-performing cohort
    """
    user_id = payload.user_id
    cadence = payload.cadence

    # Check shadow gates (enabled, paper mode)
    gate_error = _check_shadow_checkpoint_gates(user_id)
    if gate_error:
        return gate_error

    # Get cadence from env (can be overridden)
    effective_cadence = os.environ.get("SHADOW_CHECKPOINT_CADENCE", cadence)

    # Get cohort configurations
    cohorts = _get_shadow_cohorts()

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        supabase = get_admin_client()
        service = GoLiveValidationService(supabase)

        results = []

        for cohort in cohorts:
            cohort_name = cohort.get("name", "unnamed")

            # Build overrides from cohort config
            overrides = {
                "paper_window_days": cohort.get("paper_window_days"),
                "target_return_pct": cohort.get("target_return_pct"),
                "fail_fast_drawdown_pct": cohort.get("fail_fast_drawdown_pct"),
                "fail_fast_return_pct": cohort.get("fail_fast_return_pct"),
            }
            # Remove None values
            overrides = {k: v for k, v in overrides.items() if v is not None}

            result = service.eval_paper_forward_checkpoint_shadow(
                user_id=user_id,
                cadence=effective_cadence,
                cohort_name=cohort_name,
                overrides=overrides
            )

            # Calculate margin_to_target
            return_pct = result.get("return_pct", 0.0)
            target_now = result.get("target_return_now", 0.0)
            margin = return_pct - target_now

            results.append({
                "cohort": cohort_name,
                "would_pass": result.get("would_pass", False),
                "would_fail_fast": result.get("would_fail_fast", False),
                "margin_to_target": margin,
                "return_pct": return_pct,
                "target_return_now": target_now,
                "max_drawdown_pct": result.get("max_drawdown_pct", 0.0),
                "progress": result.get("progress", 0.0),
                "reason": result.get("reason"),
                "thresholds": result.get("thresholds"),
            })

        # Sort results: would_pass desc, margin_to_target desc, max_drawdown_pct desc (less negative), cohort_name asc
        results.sort(key=lambda r: (
            -int(r["would_pass"]),  # True first
            -r["margin_to_target"],  # Higher margin first
            -r["max_drawdown_pct"],  # Less negative (closer to 0) first
            r["cohort"]  # Alphabetical tiebreaker
        ))

        best = results[0] if results else None

        # v4-L1E: Determine winner and persist to shadow_cohort_daily
        # Winner is the cohort with highest return_pct among those with would_fail_fast=False
        winner = None
        non_fail_fast_results = [r for r in results if not r["would_fail_fast"]]
        if non_fail_fast_results:
            # Sort by return_pct desc, then margin_to_target desc, then max_drawdown_pct desc, then name asc
            non_fail_fast_results.sort(key=lambda r: (
                -r["return_pct"],
                -r["margin_to_target"],
                -r["max_drawdown_pct"],
                r["cohort"]
            ))
            winner = non_fail_fast_results[0]
        elif results:
            # All failed fast - still pick the "best" (first sorted result) but mark it
            winner = results[0]

        winner_persisted = False
        if winner:
            try:
                bucket_date = datetime.now(timezone.utc).date().isoformat()
                # Upsert winner to shadow_cohort_daily
                supabase.table("shadow_cohort_daily").upsert(
                    {
                        "user_id": user_id,
                        "bucket_date": bucket_date,
                        "winner_cohort": winner["cohort"],
                        "winner_return_pct": winner["return_pct"],
                        "winner_margin_to_target": winner["margin_to_target"],
                        "winner_max_drawdown_pct": winner["max_drawdown_pct"],
                        "winner_would_fail_fast": winner["would_fail_fast"],
                        "winner_reason": winner.get("reason"),
                    },
                    on_conflict="user_id,bucket_date"
                ).execute()
                winner_persisted = True
            except Exception as persist_err:
                logger.warning(f"Failed to persist cohort winner: {persist_err}")
                # Fail-open: continue with results

        return {
            "status": "ok",
            "user_id": user_id,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "cadence": effective_cadence,
            "results": results,
            "best": best,
            "winner": winner,
            "winner_persisted": winner_persisted,
            "cohort_count": len(results),
            "shadow": True
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
            "shadow": True
        }