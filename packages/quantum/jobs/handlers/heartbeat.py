"""
Scheduler Heartbeat Handler

Minimal no-op handler that proves the scheduler is alive.
Creates a successful job_run entry every 30 minutes during market hours
so ops_health_check can detect if the scheduler has stopped firing.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_NAME = "scheduler_heartbeat"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    logger.info(f"[HEARTBEAT] Scheduler alive at {now}")
    return {"ok": True, "timestamp": now}
