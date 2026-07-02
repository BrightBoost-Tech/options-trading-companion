"""
Scheduler Heartbeat Handler

Minimal no-op handler that proves the scheduler is alive.
Creates a successful job_run entry every 30 minutes during market hours
so ops_health_check can detect if the scheduler has stopped firing.

If HEARTBEAT_PING_URL is set, each run also fires one best-effort GET at
the external dead-man's-switch (healthchecks.io-style). Silence at the
provider means one of APScheduler/BE/RQ/worker died — end-of-chain
semantics; diagnose job_runs vs Railway. A provider outage can NEVER
fail the heartbeat job: the entire ping is try/except, the job result is
byte-identical whether the ping succeeds, times out, or the var is unset.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_NAME = "scheduler_heartbeat"

PING_TIMEOUT_SECONDS = 5


def _ping_external(url: str) -> None:
    """One best-effort GET at the dead-man's-switch. Never raises.

    Logs only the exception class on failure — the URL embeds the
    provider check token and must never reach the logs.
    """
    try:
        import requests

        requests.get(url, timeout=PING_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning(
            f"[HEARTBEAT] external ping failed ({type(exc).__name__}); job unaffected"
        )


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    logger.info(f"[HEARTBEAT] Scheduler alive at {now}")
    ping_url = (os.getenv("HEARTBEAT_PING_URL") or "").strip()
    if ping_url:
        _ping_external(ping_url)
    return {"ok": True, "timestamp": now}
