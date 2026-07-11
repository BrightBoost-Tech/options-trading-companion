from fastapi import APIRouter, Depends, Body
from typing import Optional, Dict
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from datetime import datetime
import os

# Job Enqueue Dependency.
# Pre-2026-05-10, this module also imported `enqueue_idempotent` from
# `packages.quantum.jobs.enqueue` (DB-only legacy path) for 4 dormant
# duplicate endpoints (/morning-brief, /midday-scan, /weekly-report,
# /universe/sync). #71 Tier 2 deleted those endpoints + the legacy
# import. The only remaining legacy importer in the repo is the
# operator smoke script `packages/quantum/scripts/rq_smoke_morning_brief.py`,
# which is out of #71 scope.
from packages.quantum.public_tasks import enqueue_job_run  # DB + RQ (canonical)
from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE

router = APIRouter(
    prefix="/internal/tasks",
    tags=["internal-tasks"],
    include_in_schema=False, # Hidden from public OpenAPI docs
)

APP_VERSION = os.getenv("APP_VERSION", "v2-dev")


@router.post("/alpaca/order-sync", status_code=202)
async def alpaca_order_sync_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:alpaca_order_sync"))
):
    """#71 Tier 1 fix (2026-05-10). Pre-fix the endpoint signature
    dropped the request body, so the CLI's
    ``payload={"force_rerun": true}`` (set by --force-rerun /
    --force) was silently discarded by FastAPI before reaching
    ``enqueue_job_run``. Re-fires within the same minute-block
    hit terminal-state dedup and never executed. Same shape as
    PR #905's iv_daily_refresh / daily_progression_eval fix.
    """
    now = datetime.now()
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="alpaca_order_sync",
        idempotency_key=f"alpaca_order_sync-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": now.isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/risk/intraday-monitor", status_code=202)
async def intraday_risk_monitor_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:intraday_risk_monitor"))
):
    now = datetime.now()
    # 15-min block key: e.g. intraday_risk_monitor-2026-04-09-10-30
    minute_block = (now.minute // 15) * 15
    return enqueue_job_run(
        job_name="intraday_risk_monitor",
        idempotency_key=f"intraday_risk_monitor-{now.strftime('%Y-%m-%d-%H')}-{minute_block:02d}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/learning/post-trade", status_code=202)
async def post_trade_learning_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:post_trade_learning")),
    trade_ids: list = Body(None, embed=True),
):
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "app_version": APP_VERSION,
        "trigger_ts": datetime.now().isoformat(),
    }
    if trade_ids:
        payload["trade_ids"] = trade_ids
    user_id = os.environ.get("USER_ID") or os.environ.get("TASK_USER_ID")
    if user_id:
        payload["user_id"] = user_id
    return enqueue_job_run(
        job_name="post_trade_learning",
        idempotency_key=f"post_trade_learning-{today}",
        payload=payload,
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
    )


@router.post("/orchestrator/start-day", status_code=202)
async def day_orchestrator_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:day_orchestrator"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="day_orchestrator",
        idempotency_key=f"day_orchestrator-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
        },
    )


@router.post("/progression/daily-eval", status_code=202)
async def daily_progression_eval_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:daily_progression_eval"))
):
    """#115 PR-A Layer 5 fix (2026-05-09). Pre-fix the endpoint
    signature dropped the request body, so the CLI's
    ``payload={"force_rerun": true}`` was silently discarded by
    FastAPI before reaching ``enqueue_job_run``. Re-fires within
    the same UTC day hit terminal-state dedup and never executed.
    Same shape exists in 9 other internal_tasks endpoints — see PR
    description for follow-up scope.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="daily_progression_eval",
        idempotency_key=f"daily_progression_eval-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
        force_rerun=force_rerun,
    )


@router.post("/calibration/update", status_code=202)
async def calibration_update_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:calibration_update"))
):
    """#71 Tier 1 fix (2026-05-10). Pre-fix the endpoint accepted
    only ``window_days`` via ``Body(..., embed=True)`` and silently
    dropped any other JSON keys — including the CLI's
    ``force_rerun`` flag set by --force-rerun / --force. Migrated
    to the dict-body shape used by PR #905's iv_daily_refresh /
    daily_progression_eval; default window_days=30 preserved so
    SCHEDULES + body-less callers keep working.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    payload_in = body or {}
    window_days = int(payload_in.get("window_days", 30))
    force_rerun = bool(payload_in.get("force_rerun", False))
    return enqueue_job_run(
        job_name="calibration_update",
        idempotency_key=f"calibration_update-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "window_days": window_days,
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/promotion/check", status_code=202)
async def promotion_check_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:promotion_check"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="promotion_check",
        idempotency_key=f"promotion_check-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
        },
        queue_name=BACKGROUND_QUEUE,  # A5: learning chain -> background (off otc)
    )


@router.post("/heartbeat", status_code=202)
async def heartbeat_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:heartbeat"))
):
    """Scheduler liveness heartbeat — proves the scheduler is firing jobs."""
    now = datetime.now()
    return enqueue_job_run(
        job_name="scheduler_heartbeat",
        idempotency_key=f"heartbeat-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/phase2-precheck", status_code=202)
async def phase2_precheck_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:phase2_precheck"))
):
    """PR #6 Phase 2 observation-window verification.

    Runs every 6 hours for 48h post-deploy. Self-expires when
    PR6_DEPLOY_TIMESTAMP + 48h is past. See
    docs/pr6_close_path_consolidation.md §5 for the 4 verification
    queries this exercises."""
    now = datetime.now()
    return enqueue_job_run(
        job_name="phase2_precheck",
        idempotency_key=f"phase2-precheck-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/autotune/walk-forward", status_code=202)
async def walk_forward_autotune_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:walk_forward_autotune"))
):
    """#71 Tier 1 fix (2026-05-10). Pre-fix the endpoint accepted
    only ``lookback_days`` and ``cohort_name`` via ``Body(...,
    embed=True)`` and silently dropped any other JSON keys —
    including the CLI's ``force_rerun`` flag set by --force-rerun
    / --force. Migrated to the dict-body shape used by PR #905's
    iv_daily_refresh / daily_progression_eval; defaults
    (lookback_days=60, cohort_name=None) preserved so SCHEDULES +
    body-less callers keep working.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    payload_in = body or {}
    lookback_days = int(payload_in.get("lookback_days", 60))
    cohort_name = payload_in.get("cohort_name")  # default None preserved
    force_rerun = bool(payload_in.get("force_rerun", False))
    return enqueue_job_run(
        job_name="walk_forward_autotune",
        idempotency_key=f"walk_forward_autotune-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "lookback_days": lookback_days,
            "cohort_name": cohort_name,
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/iv/daily-refresh", status_code=202)
async def iv_daily_refresh_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:iv_daily_refresh"))
):
    """Refreshes IV points for universe.

    Migrated 2026-05-08 from the legacy DB-only ``enqueue_idempotent``
    path to the canonical ``enqueue_job_run`` (DB + RQ push) per
    commit d4bba93's discipline. The carve-out at d4bba93 time was an
    undocumented oversight; PR-A (#115) activating the SCHEDULES
    entry surfaced the gap when the first scheduled fire wrote a
    ``status='queued'`` row that no RQ worker ever consumed.

    Job name standardised to underscored ``iv_daily_refresh`` to
    match d4bba93's pattern across sibling endpoints. The handler's
    ``JOB_NAME`` constant is updated in tandem so dispatch via
    ``discover_handlers()`` continues to resolve.

    #115 PR-A Layer 5 fix (2026-05-09): endpoint now accepts a
    request body and forwards ``force_rerun`` to ``enqueue_job_run``.
    Pre-fix the body was silently dropped at the FastAPI signature
    layer, so re-fires within the same UTC day hit terminal-state
    dedup and never executed.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="iv_daily_refresh",
        idempotency_key=f"iv_daily_refresh-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/vol-signal/snapshot", status_code=202)
async def vol_signal_snapshot_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:vol_signal_snapshot"))
):
    """Stage 1 vol-signal OBSERVE snapshot (research only).

    Logs raw synthetic vol-expansion components (SPY/QQQ/IWM IV30,
    skew/term, VIX-ETP proxies, cross-asset returns) to
    vol_signal_observations + backfills forward outcomes. Observation
    only — no scanner / trading / regime coupling; the handler no-ops
    when VOL_SIGNAL_OBSERVE_ENABLED is off. Dict-body shape with
    force_rerun forwarding per the iv_daily_refresh pattern.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="vol_signal_snapshot",
        idempotency_key=f"vol_signal_snapshot-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/thesis/score", status_code=202)
async def thesis_score_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:thesis_tracker"))
):
    """Shadow-to-expiry THESIS TRACKER (I5) — OBSERVE-ONLY daily job.

    Scores every tracked closed position's ENTRY THESIS against the underlying
    at its ORIGINAL expiry (hit/miss/unknown/in_progress) into
    position_thesis_outcomes — independent of fills / P&L. Modulates nothing.
    Background queue (learning-chain-adjacent, off the trading queue).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="thesis_tracker",
        idempotency_key=f"thesis_tracker-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        queue_name=BACKGROUND_QUEUE,  # A5: learning-chain-adjacent -> background
        force_rerun=force_rerun,
    )


@router.post("/ipo/readiness-monitor", status_code=202)
async def ipo_readiness_monitor_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:ipo_readiness_monitor"))
):
    """Daily IPO-watch readiness check (SPCX first; IPO_WATCH_SYMBOLS env).

    OBSERVE-ONLY: probes equity quote + options chain availability, reads the
    system's own gate verdicts for the day (selection log, rejections,
    suggestions), and logs first-seen transitions as info alerts. Loosens no
    gate; trades nothing. State carried in its own job_runs.result.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    force_rerun = bool((body or {}).get("force_rerun", False))
    return enqueue_job_run(
        job_name="ipo_readiness_monitor",
        idempotency_key=f"ipo_readiness_monitor-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            **({"force_rerun": True} if force_rerun else {}),
        },
        force_rerun=force_rerun,
    )


@router.post("/iv/historical-backfill", status_code=202)
async def iv_historical_backfill_task(
    body: Optional[Dict] = Body(default=None),
    auth: TaskSignatureResult = Depends(
        verify_task_signature("tasks:iv_historical_backfill")
    )
):
    """One-shot historical IV backfill via Polygon BS inversion.

    Wires α PR #935's ``iv_historical_backfill`` handler to the
    canonical operator-trigger path. Pre-2026-05-14 evening, the
    handler shipped without this route or a ``run_signed_task.py``
    registry entry — the α PR's test plan referenced this trigger
    command but the plumbing was never added. Surfaced during the
    Phase 1 trigger verification that followed PR #940's iv test
    hygiene fix.

    Payload schema (all optional — handler uses env-defaults if
    absent; see ``packages/quantum/jobs/handlers/iv_historical_backfill.py``):

    - ``days`` (int): historical window. Default 60 (or
      ``BACKFILL_DAYS`` env).
    - ``symbols`` (list[str]): symbols to backfill. Default
      ``["SPY", "AAPL", "AMD"]`` (or ``BACKFILL_REFERENCE_SYMBOLS``
      env). Omit for reference-only Phase 1.
    - ``risk_free_rate`` (float): BS inversion rate. Default 0.045
      (or ``BACKFILL_RISK_FREE_RATE`` env).
    - ``force_rerun`` (bool): bypass idempotency dedup for re-fires.

    Idempotency: keyed by ``date + symbols + days``, so different
    windows or symbol sets enqueue as distinct runs; identical
    operator triggers dedup. ``force_rerun=true`` overrides.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    payload_in = body or {}
    force_rerun = bool(payload_in.get("force_rerun", False))

    days = int(payload_in.get("days") or 60)
    symbols_in = payload_in.get("symbols") or ["SPY", "AAPL", "AMD"]
    symbols_key = ",".join(sorted(s.strip().upper() for s in symbols_in))

    handler_payload: Dict = {
        "app_version": APP_VERSION,
        "trigger_ts": datetime.now().isoformat(),
        "days": days,
        "symbols": [s.strip().upper() for s in symbols_in],
    }
    if "risk_free_rate" in payload_in:
        handler_payload["risk_free_rate"] = float(payload_in["risk_free_rate"])
    if force_rerun:
        handler_payload["force_rerun"] = True

    # Route to BACKGROUND_QUEUE so the multi-hour run does not starve
    # the primary "otc" worker queue. See docs/backlog.md
    # "[2026-05-15] TIER 1 CANDIDATE: worker-queue blocker" for the
    # Phase 1 incident (job_run 9627c667-...) that motivated this.
    return enqueue_job_run(
        job_name="iv_historical_backfill",
        idempotency_key=(
            f"iv_historical_backfill-{today}-{symbols_key}-{days}d"
        ),
        payload=handler_payload,
        queue_name=BACKGROUND_QUEUE,
        force_rerun=force_rerun,
    )

