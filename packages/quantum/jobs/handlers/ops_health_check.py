"""
Ops Health Check Job Handler

Scheduled task that:
1. Computes full ops health status
2. Sends alerts for issues (data stale, job late, failures)
3. Writes audit events for observability
4. Returns result summary in job_runs.result
"""

import time
from typing import Any, Dict
from datetime import datetime, timezone
import uuid
import logging

from packages.quantum.services.ops_health_service import (
    compute_data_freshness,
    get_expected_jobs,
    get_recent_failures,
    get_suggestions_stats,
    get_integrity_stats,
    send_ops_alert,
)
from packages.quantum.observability.audit_log_service import AuditLogService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError

logger = logging.getLogger(__name__)

JOB_NAME = "ops_health_check"

# System user ID for background jobs
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Run ops health check.

    1. Computes data freshness, job status, suggestions stats
    2. Identifies issues and sends alerts
    3. Writes audit event with health snapshot
    4. Returns result for job_runs.result

    Payload:
        - timestamp: str - Task trigger timestamp
        - force: bool - Force run even if recently completed

    Returns:
        Dict with ok, issues_found, alerts_sent, health_snapshot, timing_ms
    """
    start_time = time.time()
    alerts_sent = []
    alerts_failed = []
    issues_found = []

    try:
        client = get_admin_client()
        trace_id = str(uuid.uuid4())

        # 1. Compute data freshness
        logger.info("[OPS_HEALTH_CHECK] Computing data freshness...")
        freshness = compute_data_freshness(client)
        if freshness.is_stale:
            issues_found.append(f"Data stale: {freshness.reason}")
            alert_sent = send_ops_alert(
                "data_stale",
                f"Market data is stale. Last update: {freshness.as_of or 'unknown'}. "
                f"Age: {freshness.age_seconds or 'unknown'} seconds.",
                {"source": freshness.source, "age_seconds": freshness.age_seconds}
            )
            if alert_sent:
                alerts_sent.append("data_stale")
            else:
                alerts_failed.append("data_stale")

        # 2. Check job status
        logger.info("[OPS_HEALTH_CHECK] Checking expected jobs...")
        expected_jobs = get_expected_jobs(client)
        for job in expected_jobs:
            if job.status == "late":
                issues_found.append(f"Job late: {job.name}")
                alert_sent = send_ops_alert(
                    "job_late",
                    f"Job `{job.name}` ({job.cadence}) is late. "
                    f"Last success: {job.last_success_at or 'never'}",
                    {"job_name": job.name, "cadence": job.cadence}
                )
                if alert_sent:
                    alerts_sent.append(f"job_late:{job.name}")
                else:
                    alerts_failed.append(f"job_late:{job.name}")
            elif job.status == "never_run":
                issues_found.append(f"Job never run: {job.name}")
            elif job.status == "error":
                issues_found.append(f"Job check error: {job.name}")

        # 3. Check recent failures
        logger.info("[OPS_HEALTH_CHECK] Checking recent failures...")
        recent_failures = get_recent_failures(client)
        if recent_failures:
            failure_names = list(set(f["job_name"] for f in recent_failures[:5]))
            issues_found.append(f"Recent failures: {', '.join(failure_names)}")
            alert_sent = send_ops_alert(
                "job_failure",
                f"{len(recent_failures)} job failures in last 24h: {', '.join(failure_names)}",
                {"count": len(recent_failures), "jobs": failure_names}
            )
            if alert_sent:
                alerts_sent.append("job_failure")
            else:
                alerts_failed.append("job_failure")

        # 4. Get suggestions stats
        suggestions_stats = get_suggestions_stats(client)

        # 5. Get integrity stats
        integrity_stats = get_integrity_stats(client)

        # 6. Build health snapshot
        health_snapshot = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "data_freshness": {
                "is_stale": freshness.is_stale,
                "as_of": freshness.as_of.isoformat() if freshness.as_of else None,
                "age_seconds": freshness.age_seconds,
                "reason": freshness.reason,
                "source": freshness.source,
            },
            "jobs": {
                "expected": [
                    {"name": j.name, "status": j.status, "cadence": j.cadence,
                     "last_success_at": j.last_success_at.isoformat() if j.last_success_at else None}
                    for j in expected_jobs
                ],
                "failure_count_24h": len(recent_failures),
            },
            "suggestions": suggestions_stats,
            "integrity": integrity_stats,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
        }

        # 7. Write audit event
        logger.info("[OPS_HEALTH_CHECK] Writing audit event...")
        try:
            audit_service = AuditLogService(client)
            audit_service.log_audit_event(
                user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                event_name="ops.health_check.completed",
                payload=health_snapshot,
                suggestion_id=None,
                strategy=None,
                regime=None
            )
        except Exception as e:
            logger.warning(f"Failed to write health check audit event: {e}")

        timing_ms = (time.time() - start_time) * 1000
        is_healthy = len(issues_found) == 0

        logger.info(
            f"[OPS_HEALTH_CHECK] Complete. Healthy: {is_healthy}, "
            f"Issues: {len(issues_found)}, Alerts sent: {len(alerts_sent)}, "
            f"Timing: {timing_ms:.1f}ms"
        )

        return {
            "ok": is_healthy,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
            "health_snapshot": health_snapshot,
            "timing_ms": timing_ms,
        }

    except Exception as e:
        logger.error(f"[OPS_HEALTH_CHECK] Failed: {e}")
        raise RetryableJobError(f"Ops health check failed: {e}")
