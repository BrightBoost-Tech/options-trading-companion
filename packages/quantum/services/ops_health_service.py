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
from typing import Dict, Any, Optional, List, Tuple
import os
import json
import hashlib
import logging

from packages.quantum.observability.canonical import compute_content_hash

logger = logging.getLogger(__name__)

# Configuration
DATA_STALE_THRESHOLD_MINUTES = int(os.getenv("OPS_DATA_STALE_MINUTES", "30"))
MARKET_DATA_STALE_THRESHOLD_MS = int(os.getenv("OPS_MARKET_DATA_STALE_MS", str(20 * 60 * 1000)))  # 20 minutes
MAX_FRESHNESS_UNIVERSE_SIZE = int(os.getenv("OPS_MAX_FRESHNESS_UNIVERSE", "25"))

# Alert configuration
OPS_ALERT_MIN_SEVERITY = os.getenv("OPS_ALERT_MIN_SEVERITY", "warning")
OPS_ALERT_COOLDOWN_MINUTES = int(os.getenv("OPS_ALERT_COOLDOWN_MINUTES", "30"))

# Alert severity mapping
ALERT_SEVERITY = {
    "data_stale": "error",
    "job_failure": "error",
    "health_unhealthy": "error",
    "job_late": "warning",
    "health_degraded": "warning",
}

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


@dataclass
class MarketDataFreshnessResult:
    """Result of expanded market data freshness check."""
    is_stale: bool
    as_of: Optional[datetime]
    age_seconds: Optional[float]
    universe_size: int
    stale_symbols: List[str]
    source: str  # "MarketDataTruthLayer" | "fallback" | "missing_api_key" | "exception"
    reason: str  # "ok" | "stale_symbols" | "no_data" | "missing_api_key" | "exception:..."


@dataclass
class MarketFreshnessBlock:
    """
    Unified market freshness response for UI and alerts.

    Phase 1.1.1: Canonical response used by both /ops/dashboard_state and ops_health_check
    to ensure UI and alerts show consistent stale symbol information.
    """
    status: str  # "OK" | "WARN" | "STALE" | "ERROR"
    as_of: Optional[str]  # ISO timestamp string
    age_seconds: Optional[float]
    universe_size: int
    symbols_checked: List[str]  # Capped to max_display_symbols for UI
    stale_symbols: List[str]  # Capped to max_display_symbols for UI
    issues: List[str]


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


def get_integrity_stats(client, hours: int = 24) -> Dict[str, Any]:
    """
    Get integrity incident statistics from decision_audit_events.

    Phase 1.1.1: Queries the immutable audit stream for integrity incidents.

    Integrity incidents are events matching:
    - "integrity_incident" - detected missing fingerprint
    - "integrity_incident_linked" - linked to existing suggestion

    Args:
        client: Supabase client
        hours: Lookback window in hours (default: 24)

    Returns:
        Dict with:
        - recent_incidents_24h: count of incidents
        - last_incident_at: ISO timestamp of most recent
        - top_incident_types_24h: breakdown by type [{event_name, count}]
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Query for integrity events from decision_audit_events
        result = client.table("decision_audit_events") \
            .select("id, event_name, created_at, payload") \
            .in_("event_name", ["integrity_incident", "integrity_incident_linked"]) \
            .gte("created_at", since) \
            .order("created_at", desc=True) \
            .limit(100) \
            .execute()

        incidents = result.data or []

        # Count by incident type (from payload.type)
        type_counts: Dict[str, int] = {}
        for incident in incidents:
            payload = incident.get("payload") or {}
            incident_type = payload.get("type", "unknown")
            type_counts[incident_type] = type_counts.get(incident_type, 0) + 1

        # Build top types list (sorted by count descending)
        top_types = [
            {"event_name": t, "count": c}
            for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
        ][:5]  # Top 5

        return {
            "recent_incidents_24h": len(incidents),
            "last_incident_at": incidents[0]["created_at"] if incidents else None,
            "top_incident_types_24h": top_types,
        }

    except Exception as e:
        logger.warning(f"[INTEGRITY] Failed to get integrity stats: {e}")
        return {
            "recent_incidents_24h": 0,
            "last_incident_at": None,
            "top_incident_types_24h": [],
            "diagnostic": f"Query failed: {str(e)[:50]}"
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


# =============================================================================
# Phase 1.1: Expanded Freshness Universe
# =============================================================================


def build_freshness_universe(
    client,
    user_id: Optional[str] = None,
    max_symbols: int = MAX_FRESHNESS_UNIVERSE_SIZE
) -> List[str]:
    """
    Build expanded freshness universe from multiple sources.

    Sources (in order):
    1. Baseline: SPY, QQQ (always included)
    2. Holdings tickers from positions table
    3. Underlyings from recent trade suggestions (last 7 days)

    Args:
        client: Supabase client
        user_id: Optional user filter
        max_symbols: Maximum universe size (default: 25)

    Returns:
        List of ticker symbols (uppercase, deduplicated, capped)
    """
    universe = {"SPY", "QQQ"}  # Baseline always included

    # Add holdings tickers
    try:
        query = client.table("positions").select("symbol")
        if user_id:
            query = query.eq("user_id", user_id)
        result = query.limit(50).execute()
        for row in result.data or []:
            symbol = row.get("symbol")
            if symbol and isinstance(symbol, str):
                universe.add(symbol.upper())
    except Exception as e:
        logger.warning(f"[FRESHNESS] Failed to fetch holdings: {e}")

    # Add suggestion underlyings (last 7 days)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query = client.table("trade_suggestions").select("ticker").gte("created_at", since)
        if user_id:
            query = query.eq("user_id", user_id)
        result = query.limit(50).execute()
        for row in result.data or []:
            ticker = row.get("ticker")
            if ticker and isinstance(ticker, str):
                universe.add(ticker.upper())
    except Exception as e:
        logger.warning(f"[FRESHNESS] Failed to fetch suggestions: {e}")

    # Cap and return as sorted list
    return sorted(list(universe))[:max_symbols]


def compute_market_data_freshness(
    universe: List[str],
    stale_threshold_ms: int = MARKET_DATA_STALE_THRESHOLD_MS
) -> MarketDataFreshnessResult:
    """
    Check actual market data freshness for symbols in universe.

    Uses MarketDataTruthLayer.snapshot_many_v4() for real-time freshness.
    Stale if ANY core symbol (SPY/QQQ) stale OR >50% universe stale.

    Args:
        universe: List of ticker symbols to check
        stale_threshold_ms: Staleness threshold in milliseconds (default: 20 min)

    Returns:
        MarketDataFreshnessResult with detailed freshness status
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        return MarketDataFreshnessResult(
            is_stale=True,
            as_of=None,
            age_seconds=None,
            universe_size=len(universe),
            stale_symbols=[],
            source="missing_api_key",
            reason="missing_api_key"
        )

    try:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        layer = MarketDataTruthLayer(api_key)

        # Get raw snapshots first, then process with v4
        raw_snapshots = layer.snapshot_many(universe)
        snapshots = layer.snapshot_many_v4(universe, raw_snapshots)

        stale_symbols = []
        worst_age_ms = 0

        for symbol, snap in snapshots.items():
            freshness_ms = snap.quality.freshness_ms
            is_symbol_stale = snap.quality.is_stale or (
                freshness_ms is not None and freshness_ms > stale_threshold_ms
            )
            if is_symbol_stale:
                stale_symbols.append(symbol)
            if freshness_ms is not None and freshness_ms > worst_age_ms:
                worst_age_ms = freshness_ms

        # Compute overall staleness
        core_stale = any(s in stale_symbols for s in ["SPY", "QQQ"])
        majority_stale = len(stale_symbols) > len(universe) * 0.5
        is_stale = core_stale or majority_stale

        # Derive as_of from worst_age_ms
        as_of = None
        if worst_age_ms > 0:
            as_of = datetime.now(timezone.utc) - timedelta(milliseconds=worst_age_ms)

        return MarketDataFreshnessResult(
            is_stale=is_stale,
            as_of=as_of,
            age_seconds=worst_age_ms / 1000 if worst_age_ms else None,
            universe_size=len(universe),
            stale_symbols=sorted(stale_symbols),
            source="MarketDataTruthLayer",
            reason="stale_symbols" if stale_symbols else "ok"
        )

    except Exception as e:
        logger.error(f"[FRESHNESS] Market data freshness check failed: {e}")
        return MarketDataFreshnessResult(
            is_stale=True,
            as_of=None,
            age_seconds=None,
            universe_size=len(universe),
            stale_symbols=[],
            source="exception",
            reason=f"exception:{str(e)[:50]}"
        )


def compute_market_freshness_block(
    client,
    universe: Optional[List[str]] = None,
    max_display_symbols: int = 10
) -> MarketFreshnessBlock:
    """
    Canonical function for computing market freshness.

    Phase 1.1.1: Used by both /ops/dashboard_state and ops_health_check to ensure
    UI and alerts show consistent stale symbol information.

    Args:
        client: Supabase client (used for building universe if not provided)
        universe: Optional pre-built universe. If None, builds expanded universe.
        max_display_symbols: Max symbols to include in response (default: 10)

    Returns:
        MarketFreshnessBlock with status badge, symbols checked, and stale symbols
    """
    # Build universe if not provided
    if universe is None:
        universe = build_freshness_universe(client)

    # Use existing compute_market_data_freshness
    result = compute_market_data_freshness(universe)

    # Map to status badge
    if result.source == "missing_api_key":
        status = "ERROR"
    elif result.source == "exception":
        status = "ERROR"
    elif result.is_stale:
        status = "STALE"
    elif result.stale_symbols:
        # Some stale but not critical (not SPY/QQQ, not majority)
        status = "WARN"
    else:
        status = "OK"

    # Build issues list
    issues = []
    if result.source == "missing_api_key":
        issues.append("POLYGON_API_KEY not configured")
    elif result.source == "exception":
        issues.append(f"Market data check failed: {result.reason}")
    elif result.stale_symbols:
        issues.append(f"{len(result.stale_symbols)} symbol(s) stale")

    return MarketFreshnessBlock(
        status=status,
        as_of=result.as_of.isoformat() if result.as_of else None,
        age_seconds=result.age_seconds,
        universe_size=result.universe_size,
        symbols_checked=universe[:max_display_symbols],
        stale_symbols=result.stale_symbols[:max_display_symbols],
        issues=issues
    )


# =============================================================================
# Phase 1.1: Alert Cooldown & Severity
# =============================================================================


def get_alert_fingerprint(alert_type: str, key_details: Dict[str, Any]) -> str:
    """
    Create unique fingerprint for alert deduplication.

    Fingerprint is based on alert_type + sorted key details.

    Args:
        alert_type: Type of alert (e.g., "data_stale", "job_late")
        key_details: Dict of key identifying details (e.g., {"symbols": ["SPY"]})

    Returns:
        16-character hex fingerprint
    """
    # Use canonical serialization to ensure determinism for floats and sets
    payload = {"alert_type": alert_type, "details": key_details}
    return compute_content_hash(payload)[:16]


def should_suppress_alert(
    client,
    fingerprint: str,
    cooldown_minutes: int = OPS_ALERT_COOLDOWN_MINUTES
) -> Tuple[bool, Optional[str]]:
    """
    Check if alert should be suppressed due to cooldown.

    Uses job_runs.result to track last alert times by checking
    recently completed ops_health_check jobs for sent fingerprints.

    Args:
        client: Supabase client
        fingerprint: Alert fingerprint to check
        cooldown_minutes: Cooldown window in minutes (default: 30)

    Returns:
        Tuple of (should_suppress, last_sent_at_iso)
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
        result = client.table("job_runs") \
            .select("result, finished_at") \
            .eq("job_name", "ops_health_check") \
            .eq("status", "succeeded") \
            .gte("finished_at", since) \
            .order("finished_at", desc=True) \
            .limit(5) \
            .execute()

        for row in result.data or []:
            result_json = row.get("result") or {}
            sent_fingerprints = result_json.get("alert_fingerprints", [])
            if fingerprint in sent_fingerprints:
                return True, row.get("finished_at")

        return False, None
    except Exception as e:
        logger.warning(f"[ALERT] Cooldown check failed: {e}")
        return False, None  # Don't suppress on error - fail open


def send_ops_alert_v2(
    alert_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    severity: Optional[str] = None,
    webhook_url: Optional[str] = None,
    min_severity: str = OPS_ALERT_MIN_SEVERITY
) -> Dict[str, Any]:
    """
    Enhanced alert sender with severity filtering.

    Args:
        alert_type: Type of alert
        message: Human-readable alert message
        details: Optional additional context
        severity: Override severity (defaults to ALERT_SEVERITY mapping)
        webhook_url: Override webhook URL
        min_severity: Minimum severity to send (default from env)

    Returns:
        Dict with: sent, suppressed_reason, fingerprint, severity
    """
    import requests

    # Determine severity
    severity = severity or ALERT_SEVERITY.get(alert_type, "warning")

    # Build fingerprint for tracking
    fingerprint = get_alert_fingerprint(alert_type, details or {})

    result = {
        "sent": False,
        "suppressed_reason": None,
        "fingerprint": fingerprint,
        "severity": severity,
    }

    # Check severity threshold
    severity_order = {"error": 2, "warning": 1}
    if severity_order.get(severity, 0) < severity_order.get(min_severity, 0):
        result["suppressed_reason"] = "below_min_severity"
        logger.info(f"[OPS_ALERT] Suppressed {alert_type} (severity {severity} < min {min_severity})")
        return result

    # Get webhook URL
    url = webhook_url or os.getenv("OPS_ALERT_WEBHOOK_URL")
    if not url:
        result["suppressed_reason"] = "no_webhook"
        logger.info(f"[OPS_ALERT] No webhook configured, skipping: {alert_type}")
        return result

    # Build Slack-compatible payload with severity
    emoji_map = {
        "data_stale": ":warning:",
        "job_late": ":clock1:",
        "job_failure": ":x:",
        "health_degraded": ":yellow_circle:",
        "health_unhealthy": ":red_circle:",
    }
    severity_emoji = {
        "error": ":rotating_light:",
        "warning": ":warning:",
    }

    emoji = emoji_map.get(alert_type, severity_emoji.get(severity, ":bell:"))

    payload = {
        "text": f"{emoji} *OPS ALERT [{severity.upper()}]: {alert_type}*\n{message}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *OPS ALERT [{severity.upper()}]: {alert_type}*"
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
            logger.info(f"[OPS_ALERT] Sent {alert_type} ({severity}) alert successfully")
            result["sent"] = True
        else:
            logger.warning(f"[OPS_ALERT] Webhook returned {response.status_code}")
            result["suppressed_reason"] = f"webhook_error:{response.status_code}"
    except Exception as e:
        logger.warning(f"[OPS_ALERT] Failed to send alert: {e}")
        result["suppressed_reason"] = f"exception:{str(e)[:30]}"

    return result
