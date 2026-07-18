from fastapi import APIRouter, Header, HTTPException, Request, Depends, Body
from typing import Optional, Dict, Any
import os
import secrets
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from packages.quantum.observability.canonical import canonical_json_bytes
from packages.quantum.jobs.rq_enqueue import enqueue_idempotent, BACKGROUND_QUEUE
from packages.quantum.jobs.job_runs import JobRunStore
from packages.quantum.jobs.origin import resolve_request_origin
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from packages.quantum.policies.go_live_policy import evaluate_go_live_gate
from packages.quantum.core.rate_limiter import limiter
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
    PaperProcessOrdersPayload,
    ValidationShadowEvalPayload,
    ValidationPreflightPayload,
    ValidationInitWindowPayload,
    PaperExitEvaluatePayload,
    PaperMarkToMarketPayload,
    PaperLearningIngestPayload,
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


def _suggestions_idempotency_key(
    task_type: str,
    user_id: Optional[str] = None,
    skip_sync: bool = False,
    strategy_name: str = DEFAULT_STRATEGY_NAME,
    force_rerun: bool = False,
    force_nonce: Optional[str] = None,
) -> str:
    """
    Generate idempotency key for suggestions_open/close tasks.

    Includes user_id, skip_sync, and strategy in the key so that changing
    these inputs produces a new JobRun instead of returning the existing one.

    Args:
        task_type: 'open' or 'close'
        user_id: Optional user ID (defaults to 'all' for batch)
        skip_sync: Whether to skip holdings sync
        strategy_name: Strategy config name
        force_rerun: If True, append a nonce to guarantee a fresh run
        force_nonce: Optional deterministic nonce (auto-generated if not provided)

    Returns:
        Idempotency key string:
        - Normal: '{YYYY-MM-DD}-{type}-{user}-ss{0|1}-{strategy}'
        - Force:  '{YYYY-MM-DD}-{type}-{user}-ss{0|1}-{strategy}-force-{nonce}'
    """
    today = datetime.now().strftime("%Y-%m-%d")
    user_part = user_id or "all"
    ss_part = f"ss{int(skip_sync)}"

    # Shorten strategy name if it's the default (most common case)
    if strategy_name == DEFAULT_STRATEGY_NAME:
        strat_part = "default"
    else:
        # Use first 16 chars to keep key manageable
        strat_part = strategy_name[:16]

    base_key = f"{today}-{task_type}-{user_part}-{ss_part}-{strat_part}"

    if force_rerun:
        # Use provided nonce or generate one
        nonce = force_nonce if force_nonce else secrets.token_hex(4)
        return f"{base_key}-force-{nonce}"

    return base_key


def enqueue_job_run(
    job_name: str, idempotency_key: str, payload: Dict[str, Any],
    queue_name: str = "otc", force_rerun: bool = False,
    origin: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Helper to create a JobRun and enqueue the runner.

    A5-2 origin provenance: ``origin`` (built via
    ``packages.quantum.jobs.origin``) is stamped into the row's
    ``payload.origin`` at create time — including the cancelled-at-gate
    paths — so every attempted run is attributable. ``None`` coerces to
    ``unknown_legacy`` at the store seam (for callers not yet threaded).

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
            cancelled_detail=pause_reason,
            origin=origin,
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
                cancelled_detail="missing_user_id_for_gate",
                origin=origin,
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
                cancelled_detail=decision.reason,
                origin=origin,
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
                cancelled_detail=decision.reason,
                origin=origin,
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

    # Force rerun: append nonce to idempotency_key to bypass all dedup layers
    # (DB unique constraint, terminal state check, and RQ job_id hash).
    # Triggered by --force or --force-rerun from run_signed_task.py.
    _force = force_rerun or payload.get("force_rerun")
    print(f"[DISPATCH_DEBUG] {job_name}: force_rerun_param={force_rerun}, payload_force={payload.get('force_rerun')}, resolved={_force}")
    if _force:
        nonce = payload.get("_force_nonce") or payload.get("force_nonce") or str(uuid_mod.uuid4())
        idempotency_key = f"{idempotency_key}-force-{nonce}"
        print(f"[DISPATCH_DEBUG] {job_name}: force nonce applied, new key={idempotency_key}")

    print(f"[DISPATCH_DEBUG] {job_name}: idempotency_key={idempotency_key}")

    # Normal flow: create job run and enqueue
    # A5-2: origin stamped at create time (payload.origin) — provenance
    # exists even if no worker ever claims the row (queued-orphan lesson).
    job_run = store.create_or_get(job_name, idempotency_key, payload, origin=origin)
    print(f"[DISPATCH_DEBUG] {job_name}: create_or_get returned id={job_run.get('id', '?')[:12]} status={job_run.get('status')}")

    # Skip RQ enqueue if job is already in a terminal state (idempotency guard)
    # Belt-and-suspenders: check status regardless of completed_at, so stale
    # jobs with completed_at=NULL never block fresh runs from being recognized.
    TERMINAL_STATES = ("succeeded", "partial", "failed", "failed_retryable", "dead_lettered", "cancelled")
    if job_run["status"] in TERMINAL_STATES:
        print(f"[DISPATCH_DEBUG] {job_name}: SKIPPED — terminal status={job_run['status']}")
        return {
            "job_run_id": job_run["id"],
            "job_name": job_name,
            "idempotency_key": idempotency_key,
            "rq_job_id": None,
            "status": job_run["status"],
            "skipped": True,
        }

    result = enqueue_idempotent(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload={"job_run_id": job_run["id"]},  # Pass ID to runner
        handler_path="packages.quantum.jobs.runner.run_job_run",  # New runner path
        queue_name=queue_name
    )
    print(f"[DISPATCH_DEBUG] {job_name}: RQ enqueue result={result}")

    return {
        "job_run_id": job_run["id"],
        "job_name": job_name,
        "idempotency_key": idempotency_key,
        "rq_job_id": result.get("job_id"),
        "status": job_run["status"]
    }


@router.post("/universe/sync", status_code=202)
@limiter.limit("20/minute")
async def task_universe_sync(
    request: Request,
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
        payload={"date": today},
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )

@router.post("/morning-brief", status_code=202)
@limiter.limit("20/minute")
async def task_morning_brief(
    request: Request,
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
        payload={"date": today},
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )

@router.post("/midday-scan", status_code=202)
@limiter.limit("20/minute")
async def task_midday_scan(
    request: Request,
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
        payload={"date": today},
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )

@router.post("/weekly-report", status_code=202)
@limiter.limit("20/minute")
async def task_weekly_report(
    request: Request,
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
        payload={"week": week},
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )

@router.post("/validation/eval", status_code=202)
@limiter.limit("20/minute")
async def task_validation_eval(
    request: Request,
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
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


# =============================================================================
# Suggestion Generation Tasks (8 AM / 11 AM Chicago)
# =============================================================================


@router.post("/suggestions/close", status_code=202)
@limiter.limit("20/minute")
async def task_suggestions_close(
    request: Request,
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

    idempotency_key = _suggestions_idempotency_key(
        task_type="close",
        user_id=payload.user_id,
        skip_sync=payload.skip_sync,
        strategy_name=payload.strategy_name,
        force_rerun=payload.force_rerun,
        force_nonce=payload.force_nonce,
    )

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/suggestions/open", status_code=202)
@limiter.limit("20/minute")
async def task_suggestions_open(
    request: Request,
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

    idempotency_key = _suggestions_idempotency_key(
        task_type="open",
        user_id=payload.user_id,
        skip_sync=payload.skip_sync,
        strategy_name=payload.strategy_name,
        force_rerun=payload.force_rerun,
        force_nonce=payload.force_nonce,
    )

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/learning/ingest", status_code=202)
@limiter.limit("20/minute")
async def task_learning_ingest(
    request: Request,
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
        payload=job_payload,
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/policy-lab/eval", status_code=202)
@limiter.limit("10/minute")
async def task_policy_lab_eval(
    request: Request,
    payload: PaperLearningIngestPayload = Body(default_factory=PaperLearningIngestPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:policy_lab_eval")),
):
    """
    Triggers Policy Lab daily cohort evaluation job.

    Auth: Requires v4 HMAC signature with scope 'tasks:policy_lab_eval'.
    Gated behind POLICY_LAB_ENABLED (gate enforced inside the job handler).

    Migrated 2026-05-04 from inline sync execution to canonical async
    dispatch (#71 PR-2). The handler at
    `packages/quantum/jobs/handlers/policy_lab_eval.py` runs:
    - evaluate_cohorts
    - check_promotion
    - compute_decision_accuracy (was silently dropped by the prior
      inline endpoint — this PR restores it as a side effect of
      switching to the canonical handler dispatch)

    Multi-user fan-out: when payload.user_id is omitted, the handler
    iterates all active users (was unsupported by the prior inline
    endpoint, which returned an error if user_id was missing).

    Failure observability: per-stage `risk_alerts` writes from the prior
    sync handler are replaced by the standard `job_runs.status='failed'`
    record produced when the handler propagates an exception. Net
    observability improves — pre-migration there were zero `job_runs`
    rows for `policy_lab_eval`; post-migration each fire produces one.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_payload: Dict[str, Any] = {"date": today}
    if payload.user_id:
        job_payload["user_id"] = payload.user_id

    return enqueue_job_run(
        job_name="policy_lab_eval",
        idempotency_key=today,
        payload=job_payload,
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/paper/learning-ingest", status_code=202)
@limiter.limit("20/minute")
async def task_paper_learning_ingest(
    request: Request,
    payload: PaperLearningIngestPayload = Body(default_factory=PaperLearningIngestPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_learning_ingest"))
):
    """
    Paper trading outcome ingestion - Maps paper fills to learning_feedback_loops.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_learning_ingest'.

    This task:
    1. Reads closed paper_positions within lookback window
    2. Builds trade_closed outcome records with is_paper: true
    3. Inserts into learning_feedback_loops with idempotency via (user_id, order_id)
    4. Enables validation/streak progression for paper trading

    Payload options:
    - user_id: Run for specific user only (default: all users)
    - lookback_days: How far back to look for paper fills (default: 7)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "paper_learning_ingest"

    job_payload = {
        "date": today,
        "user_id": payload.user_id,
        "lookback_days": payload.lookback_days,
    }

    # Idempotency key includes user_id for per-user runs
    user_part = payload.user_id or "all"
    idempotency_key = f"{today}-paper-learning-{user_part}"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/strategy/autotune", status_code=202)
@limiter.limit("20/minute")
async def task_strategy_autotune(
    request: Request,
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
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


# =============================================================================
# Ops Tasks
# =============================================================================


def _ops_health_idempotency_key(now: datetime) -> str:
    """Half-hour idempotency bucket for ops_health_check.

    Owner decision 2026-07-02: cadence intent is q30min REAL. The prior
    hour-granular key ("%Y-%m-%d-%H") deduped the :37 scheduled fire against
    the :07 run every hour (observed 99/100 runs at :07, zero at :37), which
    silently halved the health-check AND the A3 alert-relay cadence — a
    direct-insert force_close waited up to ~60min for egress instead of ~30.
    Buckets :00-:29 → "00", :30-:59 → "30", so both scheduled fires execute
    while same-half-hour retries still dedup.
    """
    half = "00" if now.minute < 30 else "30"
    return f"{now.strftime('%Y-%m-%d-%H')}-{half}"


@router.post("/ops/health_check", status_code=202)
@limiter.limit("20/minute")
async def task_ops_health_check(
    request: Request,
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
    # Once per half-hour max — matches the :07/:37 schedule (q30min real).
    idempotency_key = _ops_health_idempotency_key(now)

    job_payload = {
        "timestamp": now.isoformat(),
        "force": payload.force,
    }
    if payload.synthetic_delivery_test:
        # v5-A4 delivery proof: forward the flag (the endpoint rebuilds
        # job_payload, so without this line the handler never sees it) and
        # suffix the idempotency key so the proof doesn't collide with the
        # hour's scheduled run.
        job_payload["synthetic_delivery_test"] = True
        idempotency_key = f"{idempotency_key}-synthetic"

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


# =============================================================================
# Paper Autopilot Tasks (v4-L1C)
# =============================================================================


def _paper_autopilot_idempotency_key(
    task_type: str,
    user_id: str,
    force_rerun: bool = False,
    force_nonce: Optional[str] = None,
) -> str:
    """
    Generate UTC-based idempotency key for paper autopilot tasks.

    Format: {YYYY-MM-DD}-paper-auto-{task_type}-{user_id}[-force-{nonce}]
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_key = f"{date}-paper-auto-{task_type}-{user_id}"

    if force_rerun:
        nonce = force_nonce if force_nonce else secrets.token_hex(4)
        return f"{base_key}-force-{nonce}"

    return base_key


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
@limiter.limit("20/minute")
async def task_paper_auto_execute(
    request: Request,
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
    idempotency_key = _paper_autopilot_idempotency_key(
        "execute", user_id,
        force_rerun=payload.force_rerun,
        force_nonce=payload.force_nonce,
    )

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # enqueue_job_run handles pause gate
    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/paper/auto-close", status_code=202)
@limiter.limit("20/minute")
async def task_paper_auto_close(
    request: Request,
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
    3. Closes up to PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY (default 99)
    4. Uses oldest-first ordering for determinism
    5. Creates learning outcomes for checkpoint validation
    """
    user_id = payload.user_id

    # Check autopilot gates (enabled, paper mode)
    gate_error = _check_paper_autopilot_gates(user_id)
    if gate_error:
        return gate_error

    job_name = "paper_auto_close"
    idempotency_key = _paper_autopilot_idempotency_key(
        "close", user_id,
        force_rerun=payload.force_rerun,
        force_nonce=getattr(payload, 'force_nonce', None),
    )

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # enqueue_job_run handles pause gate
    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/paper/process-orders", status_code=200)
@limiter.limit("20/minute")
async def task_paper_process_orders(
    request: Request,
    payload: PaperProcessOrdersPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_process_orders"))
):
    """
    Process staged paper orders for a user.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_process_orders'.

    This endpoint directly processes paper orders (staged/working/partial)
    and returns detailed observability info about each order's outcome.
    Unlike auto-execute/auto-close, this does NOT enqueue a background job -
    it runs synchronously for immediate feedback.

    Use cases:
    - Manual re-processing of stuck staged orders
    - Debugging order fill simulation
    - Observability into paper order lifecycle

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    """
    user_id = payload.user_id

    # Check paper mode gate (reuse autopilot gate but skip autopilot-enabled check)
    from packages.quantum.ops_endpoints import get_global_ops_control
    ops_state = get_global_ops_control()
    mode = ops_state.get("mode", "paper")

    if mode != "paper":
        return {
            "status": "cancelled",
            "reason": "mode_is_paper_only",
            "detail": f"Paper process-orders requires mode='paper', current mode='{mode}'"
        }

    # Import and run _process_orders_for_user directly
    from packages.quantum.paper_endpoints import (
        _process_orders_for_user,
        get_supabase,
        get_analytics_service,
    )

    supabase = get_supabase()
    analytics = get_analytics_service()

    result = _process_orders_for_user(supabase, analytics, user_id)

    return {
        "status": "ok" if not result.get("errors") else "partial",
        "user_id": user_id,
        "processed": result.get("processed", 0),
        "total_orders": result.get("total_orders", 0),
        "errors": result.get("errors") or None,
    }


# =============================================================================
# Shadow Checkpoint Tasks (v4-L1D)
# =============================================================================


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


@router.post("/validation/shadow-eval", status_code=200)
@limiter.limit("20/minute")
async def task_validation_shadow_eval(
    request: Request,
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

    Format: {YYYY-MM-DD}-{HH}-{task_type}-{user_id}

    Includes hour so the same task (e.g. exit-evaluate) can run at both
    8:15 AM and 3:00 PM without the morning run's key blocking the afternoon.
    """
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%d-%H')}-{task_type}-{user_id}"


@router.post("/validation/preflight", status_code=200)
@limiter.limit("20/minute")
async def task_validation_preflight(
    request: Request,
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


@router.post("/validation/init-window", status_code=202)
@limiter.limit("20/minute")
async def task_validation_init_window(
    request: Request,
    payload: ValidationInitWindowPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:validation_init_window"))
):
    """
    Triggers v4-L1F forward-window initialization job.

    Auth: Requires v4 HMAC signature with scope 'tasks:validation_init_window'.

    Validates/repairs paper_window_start and paper_window_end BEFORE Day 1
    of the test. Does NOT affect streak or readiness.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (gate enforced before enqueue)
    - Respects pause gate (gate enforced before enqueue)
    - Idempotent once per UTC hour bucket

    Migrated 2026-05-04 from inline sync execution (#71 PR-3). The mode +
    pause gates remain at the endpoint to reject before enqueue and avoid
    producing noisy "queued then failed" job_runs rows. The work itself
    runs in the queued handler at
    `packages/quantum/jobs/handlers/validation_init_window.py`.

    Failure observability via job_runs.status='failed' replaces the
    pre-migration custom error envelope.
    """
    user_id = payload.user_id

    # Check gates BEFORE enqueue — paper-mode + paused. Rejects early so
    # operator gets immediate response (not "queued, then failed"), and
    # job_runs isn't polluted with rows that were never going to run.
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    bucket_date = datetime.now(timezone.utc).date().isoformat()
    idempotency_key = _readiness_hardening_idempotency_key("init-window", user_id)
    job_payload: Dict[str, Any] = {
        "user_id": user_id,
        "date": bucket_date,
    }
    return enqueue_job_run(
        job_name="validation_init_window",
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/paper/exit-evaluate", status_code=202)
@limiter.limit("20/minute")
async def task_paper_exit_evaluate(
    request: Request,
    payload: PaperExitEvaluatePayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_exit_evaluate"))
):
    """
    Evaluate exit conditions on open paper positions and close triggered ones.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_exit_evaluate'.

    Exit conditions (checked in order — first match triggers close):
    1. target_profit: Captured >= 50% of max credit
    2. stop_loss: Loss exceeds 2x the credit received
    3. dte_threshold: 7 DTE or less (gamma risk)
    4. expiration_day: Expires today — must close

    Schedule: 3:00 PM CDT (before mark-to-market at 3:30 PM).

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    """
    user_id = payload.user_id

    # Check gates (paper mode, not paused)
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    job_name = "paper_exit_evaluate"
    idempotency_key = _readiness_hardening_idempotency_key("exit-evaluate", user_id)

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )


@router.post("/paper/mark-to-market", status_code=202)
@limiter.limit("20/minute")
async def task_paper_mark_to_market(
    request: Request,
    payload: PaperMarkToMarketPayload = Body(...),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:paper_mark_to_market"))
):
    """
    Refresh position marks and save EOD snapshots.

    Auth: Requires v4 HMAC signature with scope 'tasks:paper_mark_to_market'.

    Schedule: 3:30 PM CDT (after exit evaluator at 3:00 PM).

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    """
    user_id = payload.user_id

    # Check gates (paper mode, not paused)
    gate_error = _check_readiness_hardening_gates(user_id)
    if gate_error:
        return gate_error

    job_name = "paper_mark_to_market"
    idempotency_key = _readiness_hardening_idempotency_key("mark-to-market", user_id)

    job_payload = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return enqueue_job_run(
        job_name=job_name,
        idempotency_key=idempotency_key,
        payload=job_payload,
        force_rerun=payload.force_rerun,
        origin=resolve_request_origin(request),
    )

