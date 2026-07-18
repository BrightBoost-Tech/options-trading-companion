"""
In-Process Job Scheduler

Replaces GitHub Actions cron for time-sensitive jobs. Uses APScheduler
to fire HTTP requests to our own /internal/tasks/ and /tasks/ endpoints
on a precise schedule (within seconds, not 60-90 minutes late).

Starts on FastAPI boot via start_scheduler(). All schedules use
America/Chicago timezone with automatic DST handling.

Feature flag: SCHEDULER_ENABLED (default "0")
When disabled, no jobs are scheduled (GitHub Actions remains primary).
"""

import logging
import os
from datetime import datetime

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Loud-Error Doctrine v1.0: alert() helper + shared admin Supabase
# singleton for risk_alerts writes from scheduler-side error paths
# (signing failures, HTTP errors, retry-scan errors).
# See docs/loud_error_doctrine.md.
from packages.quantum.observability.alerts import alert, _get_admin_supabase


SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "0") == "1"
CHICAGO_TZ = "America/Chicago"

# Self-referencing base URL (the scheduler calls our own API)
_BASE_URL = os.environ.get("SCHEDULER_BASE_URL", "http://127.0.0.1:8000")

_scheduler: BackgroundScheduler = None


# ── Job definitions ─────────────────────────────────────────────────
# Each entry: (job_id, cron_kwargs, task_endpoint, scope, description)
# cron_kwargs are passed to CronTrigger with timezone=Chicago

SCHEDULES = [
    # Morning
    ("suggestions_close",           dict(hour=8,  minute=0),  "/tasks/suggestions/close",        "tasks:suggestions_close",        "Generate exit suggestions"),
    # 8:35 CT = 9:35 ET — 5 min AFTER the open. Was 8:15 CT (9:15 ET,
    # pre-open): the mark refresh fetched stale/closing quotes, so every
    # price-based exit condition was a structural no-op each morning
    # (2026-06-05 detection diagnostic). DTE/expiry work is unaffected by
    # the 20-min move; dependency order (after suggestions_close) preserved.
    ("paper_exit_evaluate_morning",  dict(hour=8,  minute=35), "/tasks/paper/exit-evaluate",      "tasks:paper_exit_evaluate",      "Morning exit evaluation"),

    # Midday
    ("suggestions_open",            dict(hour=11, minute=0),  "/tasks/suggestions/open",          "tasks:suggestions_open",         "Generate entry suggestions"),
    ("paper_auto_execute",          dict(hour=11, minute=30), "/tasks/paper/auto-execute",        "tasks:paper_auto_execute",       "Execute top suggestions"),

    # Afternoon
    # 14:45 CT = 15:45 ET — 15 min BEFORE the close. Was 15:00 CT (16:00 ET,
    # exactly AT the closing bell): a staged DAY-limit exit had zero time to
    # fill. Still precedes paper_mark_to_market (15:30 CT dependency).
    ("paper_exit_evaluate_afternoon", dict(hour=14, minute=45), "/tasks/paper/exit-evaluate",      "tasks:paper_exit_evaluate",      "Afternoon exit evaluation"),
    ("paper_mark_to_market",        dict(hour=15, minute=30), "/tasks/paper/mark-to-market",      "tasks:paper_mark_to_market",     "Refresh position marks"),

    # End of day
    ("daily_progression_eval",      dict(hour=16, minute=0),  "/internal/tasks/progression/daily-eval", "tasks:daily_progression_eval", "Green day evaluation"),
    ("learning_ingest_eod",         dict(hour=16, minute=10), "/tasks/learning/ingest",            "tasks:learning_ingest",          "EOD learning ingest"),
    ("paper_learning_ingest",       dict(hour=16, minute=20), "/tasks/paper/learning-ingest",      "tasks:paper_learning_ingest",    "Paper outcomes → learning"),
    ("policy_lab_eval",             dict(hour=16, minute=30), "/tasks/policy-lab/eval",             "tasks:policy_lab_eval",          "Evaluate cohort performance"),
    ("post_trade_learning",         dict(hour=16, minute=45), "/internal/tasks/learning/post-trade", "tasks:post_trade_learning",     "Post-trade learning agent"),
    # Thesis tracker runs AFTER the learning chain so post-#1162 close_reason is
    # ingested. OBSERVE-ONLY: scores each closed position's entry thesis to its
    # original expiry (position_thesis_outcomes). Background queue.
    ("thesis_tracker",              dict(hour=17, minute=0),  "/internal/tasks/thesis/score",       "tasks:thesis_tracker",           "Shadow-to-expiry thesis scoring"),

    # Pre-dawn calibration + orchestrator
    # iv_daily_refresh runs first (4:30) so iv_30d points are available
    # for any consumer that batches them in later. #115 PR-A landed this
    # entry — until then, the producer was wired but never triggered, so
    # `underlying_iv_points` stayed empty since 2026-04-01 and iv_rank
    # silently fell back to 50.0 across every scan.
    ("iv_daily_refresh",            dict(hour=4,  minute=30), "/internal/tasks/iv/daily-refresh",   "tasks:iv_daily_refresh",         "Daily IV point refresh"),
    ("calibration_update",          dict(hour=5,  minute=0),  "/internal/tasks/calibration/update", "tasks:calibration_update",       "Compute calibration adjustments"),
    # vol_signal_snapshot runs AFTER iv_daily_refresh (4:30) so today's IV30
    # points exist in underlying_iv_points when it reads them. OBSERVE-ONLY
    # (research layer): no-ops unless VOL_SIGNAL_OBSERVE_ENABLED; writes raw
    # vol_signal_observations components + forward-outcome backfill; touches
    # no scanner / trading / regime path.
    ("vol_signal_snapshot",         dict(hour=5,  minute=15), "/internal/tasks/vol-signal/snapshot", "tasks:vol_signal_snapshot",     "Vol-signal observe snapshot"),
    ("day_orchestrator",            dict(hour=7,  minute=30), "/internal/tasks/orchestrator/start-day", "tasks:day_orchestrator",    "Day orchestrator boot check"),

    # Frequent.
    # hour="8-15" CT covers the REAL session (8:30 CT / 9:30 ET open →
    # 15:00 CT / 16:00 ET close) with small harmless tails on both sides.
    # Was "9-16" CT — the ET session transcribed as CT numbers, so the first
    # cron fire was 9:00 CT (14:00Z), an hour into the session: combined
    # with the monitor's old CT in-handler window, the monitor was blind
    # 13:30-14:30Z every day (the 2026-06-05 −$202 excursion happened there,
    # unseen) and ran a phantom post-close hour. The monitor's broker-clock
    # gate (_is_market_open) short-circuits any out-of-session fires.
    ("alpaca_order_sync",           dict(minute="*/5", hour="8-15"), "/internal/tasks/alpaca/order-sync", "tasks:alpaca_order_sync", "Poll Alpaca for fills"),
    ("intraday_risk_monitor",       dict(minute="*/15", hour="8-15"), "/internal/tasks/risk/intraday-monitor", "tasks:intraday_risk_monitor", "Intraday risk envelope monitor"),

    # Health
    ("ops_health_check",            dict(minute="7,37", hour="8-17"), "/tasks/ops/health_check",  "tasks:ops_health_check",         "System health monitoring"),

    # Promotion readiness (after market close, after progression eval)
    ("promotion_check",             dict(hour=17, minute=0),  "/internal/tasks/promotion/check",  "tasks:promotion_check",          "Check for stuck phase transitions"),

    # IPO watch (SPCX 2026-06-12; IPO_WATCH_SYMBOLS env). 11:45 CT = after the
    # 11:00 scan + 11:30 executor, so the day's full gate verdicts exist.
    # OBSERVE-ONLY — logs readiness transitions; loosens nothing.
    ("ipo_readiness_monitor",       dict(hour=11, minute=45), "/internal/tasks/ipo/readiness-monitor", "tasks:ipo_readiness_monitor", "IPO-watch readiness transitions"),

    # Scheduler liveness heartbeat — writes a scheduler_heartbeat job_run each
    # cadence so the in-process scheduler's own silence becomes detectable.
    # CONSUMER: ops_health_service.EXPECTED_JOBS ("scheduler_heartbeat",
    # "rth_30min") — if the scheduler goes silent no heartbeat rows appear and
    # get_expected_jobs flags it through the existing job_late / job_never_run
    # ops-health alert path (DETECTION ONLY — no auto-restart). SPOF caveat: a
    # consumer fired by the same dead scheduler can't run, so this catches
    # job-level / partial stalls while ops_health_check itself still fires.
    ("scheduler_heartbeat",         dict(minute="*/30", hour="8-17"), "/internal/tasks/heartbeat", "tasks:heartbeat", "Scheduler liveness heartbeat"),

    # PR #6 Phase 2 observation-window verification. Runs every 6 hours
    # for 48 hours post-deploy; self-expires after the window. Reads
    # PR6_DEPLOY_TIMESTAMP env var (set on deploy) to bound the
    # verification query search. See docs/pr6_close_path_consolidation.md
    # §5. Leaving this entry in place after Phase 2 ships is harmless —
    # the handler returns no-op once hours_since_deploy > 48.
    ("phase2_precheck",             dict(minute=0, hour="*/6"), "/internal/tasks/phase2-precheck", "tasks:phase2_precheck", "PR #6 Phase 2 precheck verification"),
]


def _format_schedule_slot(cron_kwargs: dict) -> str:
    """Deterministic slot string for origin provenance, from the SCHEDULES
    cron kwargs (e.g. 'cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri').
    Attribution metadata only — never parsed back into a trigger."""
    fields = ",".join(f"{k}={v}" for k, v in sorted(cron_kwargs.items()))
    return f"cron:{fields};tz={CHICAGO_TZ};days=mon-fri"


def _fire_task(endpoint: str, scope: str, job_id: str, user_id: str = None,
               schedule_slot: str = None):
    """
    Fire a signed HTTP request to the given task endpoint.

    Uses the same sign_task_request() function as run_signed_task.py
    so the HMAC signature matches exactly.

    A5-2 origin provenance: asserts X-Task-Origin: scheduler (+ schedule
    id/slot + a per-fire request id) so the enqueue seam can attribute the
    row. The origin headers are OUTSIDE the HMAC canonical string
    (v4:{ts}:{nonce}:{method}:{path}:{body_hash}:{scope}) — adding them
    changes neither the signature nor any schedule/trigger behavior.
    """
    import json
    import uuid

    base_url = _BASE_URL.rstrip("/")
    url = f"{base_url}{endpoint}"

    # Build payload — same serialization as run_signed_task.py
    payload = {}
    if user_id:
        payload["user_id"] = user_id
    body = json.dumps(payload).encode("utf-8") if payload else b"{}"

    # Sign using the canonical signing function (handles TASK_SIGNING_KEYS + key_id)
    from packages.quantum.security.task_signing_v4 import sign_task_request
    try:
        headers = sign_task_request(
            method="POST",
            path=endpoint,
            body=body,
            scope=scope,
        )
    except ValueError as e:
        logger.error(f"[SCHEDULER] {job_id} signing failed: {e}")
        alert(
            _get_admin_supabase(),
            alert_type="scheduler_task_signing_failed",
            severity="warning",
            message=f"HMAC signing failed for {job_id}: {e}",
            metadata={
                "job_name": job_id,
                "endpoint_url": url,
                "scope": scope,
                "error_class": type(e).__name__,
                "error_message": str(e)[:500],
            },
        )
        return

    headers["Content-Type"] = "application/json"

    # A5-2 origin provenance assertion (read by resolve_request_origin AFTER
    # the endpoint's signature verification passes).
    from packages.quantum.jobs.origin import (
        ORIGIN_HEADER,
        ORIGIN_SCHEDULER,
        ACTOR_CLASS_HEADER,
        REQUEST_ID_HEADER,
        SCHEDULE_ID_HEADER,
        SCHEDULE_SLOT_HEADER,
    )
    headers[ORIGIN_HEADER] = ORIGIN_SCHEDULER
    headers[ACTOR_CLASS_HEADER] = "apscheduler_in_process"
    headers[REQUEST_ID_HEADER] = str(uuid.uuid4())
    headers[SCHEDULE_ID_HEADER] = job_id
    if schedule_slot:
        headers[SCHEDULE_SLOT_HEADER] = schedule_slot

    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=30.0)
        logger.info(
            f"[SCHEDULER] {job_id} → {endpoint} "
            f"status={resp.status_code} "
            f"({datetime.now().strftime('%H:%M:%S')} Chicago)"
        )
        if resp.status_code >= 400:
            logger.warning(
                f"[SCHEDULER] {job_id} failed: {resp.status_code} {resp.text[:200]}"
            )
            alert(
                _get_admin_supabase(),
                alert_type="scheduler_task_http_status_error",
                severity="warning",
                message=f"{job_id} returned HTTP {resp.status_code}",
                metadata={
                    "job_name": job_id,
                    "endpoint_url": url,
                    "scope": scope,
                    "status_code": resp.status_code,
                    "response_body": resp.text[:2000],
                },
            )
    except Exception as e:
        logger.error(f"[SCHEDULER] {job_id} error: {e}")
        alert(
            _get_admin_supabase(),
            alert_type="scheduler_task_http_error",
            severity="warning",
            message=f"HTTP request failed for {job_id}: {e}",
            metadata={
                "job_name": job_id,
                "endpoint_url": url,
                "scope": scope,
                "error_class": type(e).__name__,
                "error_message": str(e)[:500],
            },
        )


def _get_user_id() -> str:
    """Get the configured user ID for jobs that require one."""
    return os.environ.get("USER_ID", os.environ.get("TASK_USER_ID", ""))


def start_scheduler():
    """
    Start the background scheduler. Called once on FastAPI boot.
    """
    global _scheduler

    if not SCHEDULER_ENABLED:
        logger.info("[SCHEDULER] Disabled (SCHEDULER_ENABLED != 1)")
        return

    _scheduler = BackgroundScheduler(daemon=True)

    user_id = _get_user_id()

    # Jobs that need user_id
    USER_ID_REQUIRED = {
        "paper_exit_evaluate",
        "paper_auto_execute",
        "paper_mark_to_market",
        "paper_learning_ingest",
    }

    for job_id, cron_kwargs, endpoint, scope, description in SCHEDULES:
        trigger = CronTrigger(
            timezone=CHICAGO_TZ,
            day_of_week="mon-fri",
            **cron_kwargs,
        )

        # Determine if this job needs user_id
        needs_user = any(base in job_id for base in USER_ID_REQUIRED)
        job_user_id = user_id if needs_user else None

        _scheduler.add_job(
            _fire_task,
            trigger=trigger,
            args=[endpoint, scope, job_id, job_user_id,
                  _format_schedule_slot(cron_kwargs)],
            id=job_id,
            name=description,
            replace_existing=True,
            misfire_grace_time=300,  # Allow up to 5 min late
        )

        logger.info(f"[SCHEDULER] Registered: {job_id} ({description})")

    # Auto-retry job: scans for failed_retryable jobs and re-enqueues (max 1 retry)
    _scheduler.add_job(
        _retry_failed_jobs,
        trigger=CronTrigger(
            timezone=CHICAGO_TZ,
            day_of_week="mon-fri",
            minute="*/10",
            hour="8-17",
        ),
        id="auto_retry_failed",
        name="Auto-retry failed jobs",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    logger.info(f"[SCHEDULER] Started with {len(SCHEDULES) + 1} jobs (Chicago timezone)")


def _retry_failed_jobs():
    """
    Scan for failed_retryable jobs and either retry or dead-letter them.
    - attempt < 2: re-queue for retry
    - attempt >= 2: promote to dead_lettered + create risk_alert
    """
    from datetime import timezone, timedelta

    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        client = get_admin_client()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()

        # --- Retry eligible jobs (attempt < 2) ---
        # (payload selected for the A5-2 internal_retry provenance stamp)
        rows = (
            client.table("job_runs")
            .select("id, job_name, attempt, payload")
            .eq("status", "failed_retryable")
            .gte("finished_at", cutoff)
            .lt("attempt", 2)
            .limit(5)
            .execute()
        ).data or []

        for row in rows:
            job_id = row["id"]
            try:
                update_fields = {
                    "status": "queued",
                    "attempt": (row.get("attempt") or 0) + 1,
                    "locked_by": None,
                    "locked_at": None,
                }
                # A5-2 origin provenance: the auto-retry re-queues the SAME
                # row, so the retry event is APPENDED to
                # payload.origin_retries (payload.origin — the creator —
                # stays immutable; parent_job_run_id is the row's own id by
                # construction). A stamp failure must never block the retry.
                try:
                    from packages.quantum.jobs.origin import (
                        ORIGIN_INTERNAL_RETRY,
                        append_retry_origin,
                    )
                    update_fields["payload"] = append_retry_origin(
                        row.get("payload"),
                        origin=ORIGIN_INTERNAL_RETRY,
                        trigger_actor_class="scheduler_auto_retry",
                        parent_job_run_id=job_id,
                    )
                except Exception as stamp_err:
                    logger.warning(
                        f"[AUTO_RETRY] origin stamp failed (non-fatal) "
                        f"for {job_id}: {stamp_err}"
                    )
                client.table("job_runs").update(update_fields).eq("id", job_id).execute()

                logger.info(
                    f"[AUTO_RETRY] Re-queued {row['job_name']} "
                    f"run={job_id} attempt={row.get('attempt', 0) + 1}"
                )
            except Exception as e:
                logger.error(f"[AUTO_RETRY] Failed to re-queue {job_id}: {e}")

        # --- Dead-letter exhausted jobs (attempt >= 2, still failed_retryable) ---
        exhausted = (
            client.table("job_runs")
            .select("id, job_name, attempt, result, finished_at")
            .eq("status", "failed_retryable")
            .gte("attempt", 2)
            .limit(10)
            .execute()
        ).data or []

        for row in exhausted:
            job_id = row["id"]
            job_name = row.get("job_name", "unknown")
            try:
                client.table("job_runs").update({
                    "status": "dead_lettered",
                }).eq("id", job_id).execute()

                # Create risk alert for visibility
                client.table("risk_alerts").insert({
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "alert_type": "job_dead_lettered",
                    "severity": "critical",
                    "symbol": None,
                    "message": (
                        f"Job '{job_name}' exhausted retries (attempt={row.get('attempt')}) "
                        f"and was dead-lettered. Last failure: "
                        f"{str(row.get('result', {}))[:200]}"
                    ),
                    "metadata": {
                        "job_run_id": job_id,
                        "job_name": job_name,
                        "attempt": row.get("attempt"),
                        "finished_at": row.get("finished_at"),
                    },
                }).execute()

                logger.critical(
                    f"[DEAD_LETTER] {job_name} run={job_id} "
                    f"attempt={row.get('attempt')} → dead_lettered + alert created"
                )
            except Exception as e:
                logger.error(f"[DEAD_LETTER] Failed to process {job_id}: {e}")

    except Exception as e:
        logger.error(f"[AUTO_RETRY] Scan failed: {e}")
        alert(
            _get_admin_supabase(),
            alert_type="auto_retry_scan_failed",
            severity="warning",
            message=f"_retry_failed_jobs scan failed: {e}",
            metadata={
                "error_class": type(e).__name__,
                "error_message": str(e)[:500],
                "function": "_retry_failed_jobs",
            },
        )


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
        _scheduler = None
