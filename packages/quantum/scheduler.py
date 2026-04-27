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
    ("paper_exit_evaluate_morning",  dict(hour=8,  minute=15), "/tasks/paper/exit-evaluate",      "tasks:paper_exit_evaluate",      "Morning exit evaluation"),

    # Midday
    ("suggestions_open",            dict(hour=11, minute=0),  "/tasks/suggestions/open",          "tasks:suggestions_open",         "Generate entry suggestions"),
    ("paper_auto_execute",          dict(hour=11, minute=30), "/tasks/paper/auto-execute",        "tasks:paper_auto_execute",       "Execute top suggestions"),

    # Afternoon
    ("paper_exit_evaluate_afternoon", dict(hour=15, minute=0), "/tasks/paper/exit-evaluate",      "tasks:paper_exit_evaluate",      "Afternoon exit evaluation"),
    ("paper_mark_to_market",        dict(hour=15, minute=30), "/tasks/paper/mark-to-market",      "tasks:paper_mark_to_market",     "Refresh position marks"),

    # End of day
    ("daily_progression_eval",      dict(hour=16, minute=0),  "/internal/tasks/progression/daily-eval", "tasks:daily_progression_eval", "Green day evaluation"),
    ("learning_ingest_eod",         dict(hour=16, minute=10), "/tasks/learning/ingest",            "tasks:learning_ingest",          "EOD learning ingest"),
    ("paper_learning_ingest",       dict(hour=16, minute=20), "/tasks/paper/learning-ingest",      "tasks:paper_learning_ingest",    "Paper outcomes → learning"),
    ("policy_lab_eval",             dict(hour=16, minute=30), "/tasks/policy-lab/eval",             "tasks:policy_lab_eval",          "Evaluate cohort performance"),
    ("post_trade_learning",         dict(hour=16, minute=45), "/internal/tasks/learning/post-trade", "tasks:post_trade_learning",     "Post-trade learning agent"),

    # Pre-dawn calibration + orchestrator
    ("calibration_update",          dict(hour=5,  minute=0),  "/internal/tasks/calibration/update", "tasks:calibration_update",       "Compute calibration adjustments"),
    ("day_orchestrator",            dict(hour=7,  minute=30), "/internal/tasks/orchestrator/start-day", "tasks:day_orchestrator",    "Day orchestrator boot check"),

    # Frequent
    ("alpaca_order_sync",           dict(minute="*/5", hour="9-16"), "/internal/tasks/alpaca/order-sync", "tasks:alpaca_order_sync", "Poll Alpaca for fills"),
    ("intraday_risk_monitor",       dict(minute="*/15", hour="9-16"), "/internal/tasks/risk/intraday-monitor", "tasks:intraday_risk_monitor", "Intraday risk envelope monitor"),

    # Health
    ("ops_health_check",            dict(minute="7,37", hour="8-17"), "/tasks/ops/health_check",  "tasks:ops_health_check",         "System health monitoring"),

    # Promotion readiness (after market close, after progression eval)
    ("promotion_check",             dict(hour=17, minute=0),  "/internal/tasks/promotion/check",  "tasks:promotion_check",          "Check for stuck phase transitions"),

    # Scheduler liveness heartbeat — creates a job_run so ops_health_check can detect scheduler death
    ("scheduler_heartbeat",         dict(minute="*/30", hour="8-17"), "/internal/tasks/heartbeat", "tasks:heartbeat", "Scheduler liveness heartbeat"),

    # PR #6 Phase 2 observation-window verification. Runs every 6 hours
    # for 48 hours post-deploy; self-expires after the window. Reads
    # PR6_DEPLOY_TIMESTAMP env var (set on deploy) to bound the
    # verification query search. See docs/pr6_close_path_consolidation.md
    # §5. Leaving this entry in place after Phase 2 ships is harmless —
    # the handler returns no-op once hours_since_deploy > 48.
    ("phase2_precheck",             dict(minute=0, hour="*/6"), "/internal/tasks/phase2-precheck", "tasks:phase2_precheck", "PR #6 Phase 2 precheck verification"),
]


def _fire_task(endpoint: str, scope: str, job_id: str, user_id: str = None):
    """
    Fire a signed HTTP request to the given task endpoint.

    Uses the same sign_task_request() function as run_signed_task.py
    so the HMAC signature matches exactly.
    """
    import json

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
            args=[endpoint, scope, job_id, job_user_id],
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
        rows = (
            client.table("job_runs")
            .select("id, job_name, attempt")
            .eq("status", "failed_retryable")
            .gte("finished_at", cutoff)
            .lt("attempt", 2)
            .limit(5)
            .execute()
        ).data or []

        for row in rows:
            job_id = row["id"]
            try:
                client.table("job_runs").update({
                    "status": "queued",
                    "attempt": (row.get("attempt") or 0) + 1,
                    "locked_by": None,
                    "locked_at": None,
                }).eq("id", job_id).execute()

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
