"""
Ops Health Check Job Handler

Phase 1.1 Enhanced:
1. Computes full ops health status with expanded market data freshness
2. Sends alerts with severity levels and cooldown suppression
3. Writes audit events for observability
4. Returns result summary in job_runs.result with fingerprints for cooldown tracking
"""

import os
import time
from typing import Any, Dict, List
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
    # Phase 1.1 additions
    build_freshness_universe,
    compute_market_data_freshness,
    get_alert_fingerprint,
    should_suppress_alert,
    send_ops_alert_v2,
    OPS_ALERT_MIN_SEVERITY,
    OPS_ALERT_COOLDOWN_MINUTES,
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
    Run ops health check with Phase 1.1 enhancements.

    1. Builds expanded freshness universe (SPY/QQQ + holdings + suggestions)
    2. Computes market data freshness + job status + suggestions stats
    3. Sends alerts with severity filtering and cooldown suppression
    4. Writes audit event with health snapshot
    5. Returns result with alert fingerprints for future cooldown checks

    Payload:
        - timestamp: str - Task trigger timestamp
        - force: bool - Force run even if recently completed

    Returns:
        Dict with ok, issues_found, alerts_sent, alerts_suppressed,
        alert_fingerprints, market_freshness, health_snapshot, timing_ms
    """
    start_time = time.time()
    alerts_sent: List[str] = []
    alerts_failed: List[str] = []
    alerts_suppressed: List[Dict[str, Any]] = []
    alert_fingerprints: List[str] = []
    issues_found: List[str] = []

    # Get config from env
    min_severity = os.getenv("OPS_ALERT_MIN_SEVERITY", OPS_ALERT_MIN_SEVERITY)
    cooldown_minutes = int(os.getenv("OPS_ALERT_COOLDOWN_MINUTES", str(OPS_ALERT_COOLDOWN_MINUTES)))

    try:
        client = get_admin_client()
        trace_id = str(uuid.uuid4())

        # ==============================================================
        # 1. Build expanded freshness universe and check market data
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Building freshness universe...")
        universe = build_freshness_universe(client)
        logger.info(f"[OPS_HEALTH_CHECK] Universe: {len(universe)} symbols: {universe[:5]}...")

        logger.info("[OPS_HEALTH_CHECK] Computing market data freshness...")
        market_freshness = compute_market_data_freshness(universe)

        # Also compute job-based freshness for backwards compatibility
        job_freshness = compute_data_freshness(client)

        # Determine overall staleness: stale if either source indicates stale
        is_data_stale = market_freshness.is_stale or job_freshness.is_stale

        if is_data_stale:
            stale_reason = market_freshness.reason if market_freshness.is_stale else job_freshness.reason
            issues_found.append(f"Data stale: {stale_reason}")

            # Build fingerprint based on stale symbols
            fingerprint_details = {
                "symbols": sorted(market_freshness.stale_symbols[:5]) if market_freshness.stale_symbols else [],
                "source": market_freshness.source,
            }
            fingerprint = get_alert_fingerprint("data_stale", fingerprint_details)

            # Check cooldown
            suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

            if not suppressed:
                alert_result = send_ops_alert_v2(
                    "data_stale",
                    f"Market data is stale. Universe: {market_freshness.universe_size} symbols. "
                    f"Stale: {len(market_freshness.stale_symbols)} ({', '.join(market_freshness.stale_symbols[:3])}). "
                    f"Source: {market_freshness.source}. Reason: {market_freshness.reason}",
                    details={
                        "universe_size": market_freshness.universe_size,
                        "stale_symbols": market_freshness.stale_symbols,
                        "source": market_freshness.source,
                        "age_seconds": market_freshness.age_seconds,
                    },
                    severity="error",
                    min_severity=min_severity,
                )
                if alert_result["sent"]:
                    alerts_sent.append("data_stale")
                    alert_fingerprints.append(fingerprint)
                elif alert_result["suppressed_reason"]:
                    alerts_suppressed.append({
                        "type": "data_stale",
                        "reason": alert_result["suppressed_reason"],
                    })
            else:
                alerts_suppressed.append({
                    "type": "data_stale",
                    "reason": "cooldown",
                    "last_sent": last_sent,
                })

        # ==============================================================
        # 2. Check expected job status
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking expected jobs...")
        expected_jobs = get_expected_jobs(client)

        for job in expected_jobs:
            if job.status == "late":
                issues_found.append(f"Job late: {job.name}")

                fingerprint = get_alert_fingerprint("job_late", {"job_name": job.name})
                suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

                if not suppressed:
                    alert_result = send_ops_alert_v2(
                        "job_late",
                        f"Job `{job.name}` ({job.cadence}) is late. "
                        f"Last success: {job.last_success_at or 'never'}",
                        details={"job_name": job.name, "cadence": job.cadence},
                        severity="warning",
                        min_severity=min_severity,
                    )
                    if alert_result["sent"]:
                        alerts_sent.append(f"job_late:{job.name}")
                        alert_fingerprints.append(fingerprint)
                    elif alert_result["suppressed_reason"]:
                        alerts_suppressed.append({
                            "type": f"job_late:{job.name}",
                            "reason": alert_result["suppressed_reason"],
                        })
                else:
                    alerts_suppressed.append({
                        "type": f"job_late:{job.name}",
                        "reason": "cooldown",
                        "last_sent": last_sent,
                    })

            elif job.status == "never_run":
                issues_found.append(f"Job never run: {job.name}")
            elif job.status == "error":
                issues_found.append(f"Job check error: {job.name}")

        # ==============================================================
        # 3. Check recent failures
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking recent failures...")
        recent_failures = get_recent_failures(client)

        if recent_failures:
            failure_names = sorted(set(f["job_name"] for f in recent_failures[:5]))
            issues_found.append(f"Recent failures: {', '.join(failure_names)}")

            fingerprint = get_alert_fingerprint("job_failure", {"jobs": failure_names})
            suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

            if not suppressed:
                alert_result = send_ops_alert_v2(
                    "job_failure",
                    f"{len(recent_failures)} job failures in last 24h: {', '.join(failure_names)}",
                    details={"count": len(recent_failures), "jobs": failure_names},
                    severity="error",
                    min_severity=min_severity,
                )
                if alert_result["sent"]:
                    alerts_sent.append("job_failure")
                    alert_fingerprints.append(fingerprint)
                elif alert_result["suppressed_reason"]:
                    alerts_suppressed.append({
                        "type": "job_failure",
                        "reason": alert_result["suppressed_reason"],
                    })
            else:
                alerts_suppressed.append({
                    "type": "job_failure",
                    "reason": "cooldown",
                    "last_sent": last_sent,
                })

        # ==============================================================
        # 4. Get suggestions stats
        # ==============================================================
        suggestions_stats = get_suggestions_stats(client)

        # ==============================================================
        # 5. Get integrity stats
        # ==============================================================
        integrity_stats = get_integrity_stats(client)

        # ==============================================================
        # 6. Build health snapshot
        # ==============================================================
        health_snapshot = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "market_freshness": {
                "is_stale": market_freshness.is_stale,
                "as_of": market_freshness.as_of.isoformat() if market_freshness.as_of else None,
                "age_seconds": market_freshness.age_seconds,
                "universe_size": market_freshness.universe_size,
                "stale_symbols": market_freshness.stale_symbols,
                "source": market_freshness.source,
                "reason": market_freshness.reason,
            },
            "job_freshness": {
                "is_stale": job_freshness.is_stale,
                "as_of": job_freshness.as_of.isoformat() if job_freshness.as_of else None,
                "age_seconds": job_freshness.age_seconds,
                "reason": job_freshness.reason,
                "source": job_freshness.source,
            },
            "jobs": {
                "expected": [
                    {
                        "name": j.name,
                        "status": j.status,
                        "cadence": j.cadence,
                        "last_success_at": j.last_success_at.isoformat() if j.last_success_at else None,
                    }
                    for j in expected_jobs
                ],
                "failure_count_24h": len(recent_failures),
            },
            "suggestions": suggestions_stats,
            "integrity": integrity_stats,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
            "alerts_suppressed": alerts_suppressed,
        }

        # ==============================================================
        # 7. Write audit event
        # ==============================================================
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
                regime=None,
            )
        except Exception as e:
            logger.warning(f"Failed to write health check audit event: {e}")

        timing_ms = (time.time() - start_time) * 1000
        is_healthy = len(issues_found) == 0

        logger.info(
            f"[OPS_HEALTH_CHECK] Complete. Healthy: {is_healthy}, "
            f"Issues: {len(issues_found)}, Alerts sent: {len(alerts_sent)}, "
            f"Alerts suppressed: {len(alerts_suppressed)}, "
            f"Timing: {timing_ms:.1f}ms"
        )

        return {
            "ok": is_healthy,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
            "alerts_suppressed": alerts_suppressed,
            "alert_fingerprints": alert_fingerprints,  # For cooldown tracking
            "market_freshness": {
                "is_stale": market_freshness.is_stale,
                "universe_size": market_freshness.universe_size,
                "stale_symbols": market_freshness.stale_symbols,
                "source": market_freshness.source,
                "reason": market_freshness.reason,
            },
            "health_snapshot": health_snapshot,
            "timing_ms": timing_ms,
        }

    except Exception as e:
        logger.error(f"[OPS_HEALTH_CHECK] Failed: {e}")
        raise RetryableJobError(f"Ops health check failed: {e}")
