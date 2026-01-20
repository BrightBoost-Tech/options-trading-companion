"""
Ops Health Service

Shared logic for:
- compute_data_freshness() - Data freshness assessment
- get_expected_jobs() - Expected job status
- get_recent_failures() - Recent job failures
- get_suggestions_stats() - Suggestion generation stats
- send_ops_alert() - Webhook alerting with graceful failure

Used by:
- GET /ops/health endpoint
- ops_health_check job handler
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import os
import json
import logging

logger = logging.getLogger(__name__)

# Configuration
DATA_STALE_THRESHOLD_MINUTES = int(os.getenv("OPS_DATA_STALE_MINUTES", "30"))

# Expected jobs with their cadences
EXPECTED_JOBS = [
    ("suggestions_close", "daily"),
    ("suggestions_open", "daily"),
    ("learning_ingest", "daily"),
    ("strategy_autotune", "weekly"),
]


@dataclass
class DataFreshnessResult:
    """Result of data freshness check."""
    is_stale: bool
    as_of: Optional[datetime]
    age_seconds: Optional[float]
    reason: Optional[str]
    source: str  # "job_runs" | "trade_suggestions" | "none"


@dataclass
class ExpectedJob:
    """Expected job status."""
    name: str
    cadence: str  # "daily" | "weekly"
    last_success_at: Optional[datetime]
    status: str  # "ok" | "late" | "never_run" | "error"


def compute_data_freshness(
    client,
    stale_threshold_minutes: int = DATA_STALE_THRESHOLD_MINUTES
) -> DataFreshnessResult:
    """
    Compute data freshness status.

    Searches for best "as-of" source:
    1. Most recent successful job_run with market data (suggestions_close/open)
    2. Most recent trade_suggestion
    3. Falls back to "no data" if neither found

    Args:
        client: Supabase client
        stale_threshold_minutes: Threshold for staleness (default: 30)

    Returns:
        DataFreshnessResult with is_stale, as_of, age_seconds, reason, source.
    """
    now = datetime.now(timezone.utc)

    # Try 1: Most recent successful market-data job
    try:
        result = client.table("job_runs") \
            .select("finished_at, job_name") \
            .in_("job_name", ["suggestions_close", "suggestions_open"]) \
            .eq("status", "succeeded") \
            .order("finished_at", desc=True) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            finished_at_str = result.data[0].get("finished_at")
            if finished_at_str:
                # Parse ISO datetime
                if finished_at_str.endswith("Z"):
                    finished_at_str = finished_at_str.replace("Z", "+00:00")
                finished_at = datetime.fromisoformat(finished_at_str)

                # Ensure timezone aware
                if finished_at.tzinfo is None:
                    finished_at = finished_at.replace(tzinfo=timezone.utc)

                age = (now - finished_at).total_seconds()
                is_stale = age > (stale_threshold_minutes * 60)

                return DataFreshnessResult(
                    is_stale=is_stale,
                    as_of=finished_at,
                    age_seconds=age,
                    reason=f"Last successful job > {stale_threshold_minutes} min ago" if is_stale else None,
                    source="job_runs"
                )
    except Exception as e:
        logger.warning(f"Failed to check job_runs freshness: {e}")

    # Try 2: Most recent trade_suggestion
    try:
        result = client.table("trade_suggestions") \
            .select("created_at") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            created_at_str = result.data[0].get("created_at")
            if created_at_str:
                if created_at_str.endswith("Z"):
                    created_at_str = created_at_str.replace("Z", "+00:00")
                created_at = datetime.fromisoformat(created_at_str)

                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                age = (now - created_at).total_seconds()
                is_stale = age > (stale_threshold_minutes * 60)

                return DataFreshnessResult(
                    is_stale=is_stale,
                    as_of=created_at,
                    age_seconds=age,
                    reason=f"Last suggestion > {stale_threshold_minutes} min ago" if is_stale else None,
                    source="trade_suggestions"
                )
    except Exception as e:
        logger.warning(f"Failed to check trade_suggestions freshness: {e}")

    # Fallback: No data found
    return DataFreshnessResult(
        is_stale=True,
        as_of=None,
        age_seconds=None,
        reason="no_data_source_found",
        source="none"
    )


def get_expected_jobs(client) -> List[ExpectedJob]:
    """
    Get status of expected scheduled jobs.

    Args:
        client: Supabase client

    Returns:
        List of ExpectedJob with name, cadence, last_success_at, status.
    """
    results = []
    now = datetime.now(timezone.utc)

    for job_name, cadence in EXPECTED_JOBS:
        try:
            # Get most recent successful run
            result = client.table("job_runs") \
                .select("finished_at, status") \
                .eq("job_name", job_name) \
                .eq("status", "succeeded") \
                .order("finished_at", desc=True) \
                .limit(1) \
                .execute()

            if result.data and len(result.data) > 0:
                finished_at_str = result.data[0].get("finished_at")
                finished_at = None

                if finished_at_str:
                    if finished_at_str.endswith("Z"):
                        finished_at_str = finished_at_str.replace("Z", "+00:00")
                    finished_at = datetime.fromisoformat(finished_at_str)

                    if finished_at.tzinfo is None:
                        finished_at = finished_at.replace(tzinfo=timezone.utc)

                # Determine if late
                if cadence == "daily":
                    threshold = timedelta(hours=26)  # Allow some slack
                else:  # weekly
                    threshold = timedelta(days=8)

                if finished_at:
                    age = now - finished_at
                    is_late = age > threshold
                else:
                    is_late = True

                results.append(ExpectedJob(
                    name=job_name,
                    cadence=cadence,
                    last_success_at=finished_at,
                    status="late" if is_late else "ok"
                ))
            else:
                results.append(ExpectedJob(
                    name=job_name,
                    cadence=cadence,
                    last_success_at=None,
                    status="never_run"
                ))
        except Exception as e:
            logger.warning(f"Failed to check job {job_name}: {e}")
            results.append(ExpectedJob(
                name=job_name,
                cadence=cadence,
                last_success_at=None,
                status="error"
            ))

    return results


def get_recent_failures(client, hours: int = 24) -> List[Dict[str, Any]]:
    """
    Get recent job failures within specified hours.

    Args:
        client: Supabase client
        hours: Lookback window in hours (default: 24)

    Returns:
        List of failed job_run records
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = client.table("job_runs") \
            .select("id, job_name, status, finished_at, error") \
            .in_("status", ["failed_retryable", "dead_lettered"]) \
            .gte("finished_at", since) \
            .order("finished_at", desc=True) \
            .limit(10) \
            .execute()

        return result.data or []
    except Exception as e:
        logger.warning(f"Failed to get recent failures: {e}")
        return []


def get_suggestions_stats(client) -> Dict[str, Any]:
    """
    Get suggestion generation statistics for today.

    Args:
        client: Supabase client

    Returns:
        Dict with last_cycle_date and count_last_cycle
    """
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_start = f"{today}T00:00:00+00:00"

        result = client.table("trade_suggestions") \
            .select("id", count="exact") \
            .gte("created_at", today_start) \
            .execute()

        count = result.count if hasattr(result, 'count') and result.count is not None else 0

        return {
            "last_cycle_date": today,
            "count_last_cycle": count
        }
    except Exception as e:
        logger.warning(f"Failed to get suggestion stats: {e}")
        return {"last_cycle_date": None, "count_last_cycle": 0}


def get_integrity_stats(client) -> Dict[str, Any]:
    """
    Get integrity incident statistics.

    Placeholder for future integrity monitoring.
    Currently returns empty results.

    Args:
        client: Supabase client

    Returns:
        Dict with recent_incidents count and last_incident_at
    """
    # Future: Query for integrity violations/incidents
    # For now, return placeholder
    return {
        "recent_incidents": 0,
        "last_incident_at": None
    }


def send_ops_alert(
    alert_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    webhook_url: Optional[str] = None
) -> bool:
    """
    Send ops alert via webhook (Slack-compatible).

    Gracefully handles missing webhook URL or failures.

    Args:
        alert_type: Type of alert (data_stale, job_late, job_failure, health_degraded)
        message: Human-readable alert message
        details: Optional additional context
        webhook_url: Override webhook URL (defaults to OPS_ALERT_WEBHOOK_URL env)

    Returns:
        True if sent successfully, False otherwise
    """
    import requests

    url = webhook_url or os.getenv("OPS_ALERT_WEBHOOK_URL")

    if not url:
        logger.info(f"[OPS_ALERT] No webhook configured, skipping alert: {alert_type}")
        return False

    # Build Slack-compatible payload
    emoji_map = {
        "data_stale": ":warning:",
        "job_late": ":clock1:",
        "job_failure": ":x:",
        "health_degraded": ":yellow_circle:",
    }

    emoji = emoji_map.get(alert_type, ":bell:")

    payload = {
        "text": f"{emoji} *OPS ALERT: {alert_type}*\n{message}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *OPS ALERT: {alert_type}*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
        ]
    }

    if details:
        payload["blocks"].append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"```{json.dumps(details, indent=2, default=str)}```"}
            ]
        })

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"[OPS_ALERT] Sent {alert_type} alert successfully")
            return True
        else:
            logger.warning(f"[OPS_ALERT] Webhook returned {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"[OPS_ALERT] Failed to send alert: {e}")
        return False
