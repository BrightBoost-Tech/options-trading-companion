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

SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "0") == "1"
CHICAGO_TZ = "America/Chicago"

# Self-referencing base URL (the scheduler calls our own API)
_BASE_URL = os.environ.get("SCHEDULER_BASE_URL", "http://127.0.0.1:8000")

# Signing configuration
_SIGNING_SECRET = os.environ.get("TASK_SIGNING_SECRET", "")

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

    # Frequent
    ("alpaca_order_sync",           dict(minute="*/5", hour="9-16"), "/internal/tasks/alpaca/order-sync", "tasks:alpaca_order_sync", "Poll Alpaca for fills"),

    # Health
    ("ops_health_check",            dict(minute="7,37", hour="8-17"), "/tasks/ops/health_check",  "tasks:ops_health_check",         "System health monitoring"),
]


def _fire_task(endpoint: str, scope: str, job_id: str, user_id: str = None):
    """
    Fire a signed HTTP request to the given task endpoint.

    This runs inside APScheduler's thread pool, so it must be
    synchronous (httpx sync client, not async).
    """
    import json
    import time
    import hashlib
    import hmac
    import uuid

    base_url = _BASE_URL.rstrip("/")
    url = f"{base_url}{endpoint}"

    # Build payload
    payload = {}
    if user_id:
        payload["user_id"] = user_id

    # Sign the request (v4 HMAC)
    timestamp = int(time.time())
    nonce = str(uuid.uuid4())
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    sig_payload = f"v4:{timestamp}:{nonce}:POST:{endpoint}:{body_hash}:{scope}"
    signature = hmac.new(
        _SIGNING_SECRET.encode(),
        sig_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Task-Ts": str(timestamp),
        "X-Task-Nonce": nonce,
        "X-Task-Scope": scope,
        "X-Task-Signature": signature,
    }

    try:
        resp = httpx.post(url, content=body_bytes, headers=headers, timeout=30.0)
        logger.info(
            f"[SCHEDULER] {job_id} → {endpoint} "
            f"status={resp.status_code} "
            f"({datetime.now().strftime('%H:%M:%S')} Chicago)"
        )
        if resp.status_code >= 400:
            logger.warning(
                f"[SCHEDULER] {job_id} failed: {resp.status_code} {resp.text[:200]}"
            )
    except Exception as e:
        logger.error(f"[SCHEDULER] {job_id} error: {e}")


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

    if not _SIGNING_SECRET:
        logger.warning("[SCHEDULER] No TASK_SIGNING_SECRET — jobs will fail auth")

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

    _scheduler.start()
    logger.info(f"[SCHEDULER] Started with {len(SCHEDULES)} jobs (Chicago timezone)")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
        _scheduler = None
