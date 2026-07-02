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
# Default retuned 30→360 (owner-approved 2026-07-02, P1-B). The job-freshness
# arm measures the age of two 1×/day jobs (suggestions_close 13:00Z /
# suggestions_open 16:00Z); against a 30-min threshold every inter-scan gap
# read as stale — 39 of 39 job-arm firings in 14d were false HIGHs. Max
# healthy in-gate age observed over 10/10 trading days: 187 min (19:07Z check
# vs the 16:00Z run). 360 ≈ 2× worst-healthy, and a genuinely dead
# suggestions_open still alerts SAME-DAY at the 19:07Z check (367 min).
# Env `OPS_DATA_STALE_MINUTES` overrides (unchanged wiring).
DATA_STALE_THRESHOLD_MINUTES = int(os.getenv("OPS_DATA_STALE_MINUTES", "360"))
MARKET_DATA_STALE_THRESHOLD_MS = int(os.getenv("OPS_MARKET_DATA_STALE_MS", str(20 * 60 * 1000)))  # 20 minutes
MAX_FRESHNESS_UNIVERSE_SIZE = int(os.getenv("OPS_MAX_FRESHNESS_UNIVERSE", "25"))


def is_us_market_hours(now: Optional[datetime] = None) -> bool:
    """Approximate US equity market hours in UTC: Mon–Fri 13:30–20:00.

    v5-A4: gates the data_stale ALERT only. Market snapshots age past any
    threshold every evening by construction — alerting on that nightly via
    the new risk_alerts channel would be steady-state noise (worse than the
    webhook void it replaces). Holidays read as market hours → at most one
    benign data_stale alert per holiday, capped by the cooldown. The health
    SNAPSHOT still records staleness regardless; only the alert is gated.
    """
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (13 * 60 + 30) <= minutes < (20 * 60)

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
    "output_stale": "error",
}

# Intraday RTH-only job cadences (loss-protection monitors + the scheduler
# liveness heartbeat). Value = nominal fire interval in minutes, keyed by the
# cadence label used in EXPECTED_JOBS. Staleness for these is gated on market
# hours + a session-open warm-up so weekend / overnight / pre-open silence
# (BY DESIGN) is never flagged. See _rth_job_status().
_RTH_CADENCE_MINUTES = {
    "rth_5min": 5,
    "rth_15min": 15,
    "rth_30min": 30,
}

# Extra slack added to the nominal interval before an intraday job is called
# late — absorbs cycle jitter + execution time so a single slow cycle doesn't
# flap. Defaults: order_sync 5+15=20m, monitor 15+15=30m, heartbeat
# 30+15=45m. One env knob tunes all three.
OPS_INTRADAY_STALENESS_MARGIN_MIN = int(
    os.getenv("OPS_INTRADAY_STALENESS_MARGIN_MIN", "15")
)

# Conservative regular-session open (UTC) used ONLY for the start-of-session
# warm-up anchor. is_us_market_hours()'s 13:30 lower bound is the EDT
# (summer) open; the EST (winter) open is 14:30Z. Anchoring the warm-up to
# the later 14:30 means the 13:30–14:30 band — where is_us_market_hours() can
# read True before the session has actually opened in winter — never yields a
# false 'late'. Mid-session detection is unaffected (anchor = last_success
# once the job starts writing).
_RTH_WARMUP_OPEN_UTC = (14, 30)

# Expected jobs with their cadences
EXPECTED_JOBS = [
    ("suggestions_close", "daily"),
    ("suggestions_open", "daily"),
    ("learning_ingest", "daily"),
    ("daily_progression_eval", "daily"),
    # Intraday loss-protection jobs + the scheduler liveness heartbeat.
    # A monitor / order_sync that simply STOPS being scheduled writes no
    # job_runs and was previously UNDETECTED — a single in-process scheduler
    # runs the monitor, the exits, AND its own watchdog (a SPOF). The
    # heartbeat is PRODUCED by scheduler.py but was never CONSUMED; registering
    # it here IS the consumer — a silent scheduler stops writing heartbeats and
    # surfaces through the existing job_late / job_never_run alert path. All
    # three are RTH-cadence + market-hours gated (see _RTH_CADENCE_MINUTES /
    # _rth_job_status); closed-market silence is by design and never flagged.
    # DETECTION ONLY — no restart.
    ("alpaca_order_sync", "rth_5min"),
    ("intraday_risk_monitor", "rth_15min"),
    ("scheduler_heartbeat", "rth_30min"),
]

# Output-freshness registry: tables whose newest row proves a feedback loop
# is actually WRITING, not merely that its job "succeeded". EXPECTED_JOBS
# checks a job RAN; this checks its OUTPUT is FRESH — the distinction that
# hid the 2026-05-15→06-09 calibration freeze (daily green job_runs with
# users_updated=0 for 25 days). Entries: (table, timestamp_column,
# max_age_hours). Extend as more loops gain durable outputs (e.g.
# reentry_cooldowns writer health, observe-mode hooks).
OUTPUT_FRESHNESS = [
    (
        "calibration_adjustments",
        "computed_at",
        int(os.getenv("OPS_CALIBRATION_MAX_AGE_HOURS", "240")),  # 10 days
    ),
    (
        # Learning-ingest output: one row per closed position. A multi-week gap
        # while the system is trading means paper_learning_ingest (or its
        # upstream close path) silently stalled — the same "job green, output
        # frozen" class as the 25-day calibration freeze, one loop earlier.
        # Generous default so a normal low-frequency quiet stretch doesn't
        # false-alarm; it surfaces a genuine multi-week stall, not a slow week.
        "learning_feedback_loops",
        "created_at",
        int(os.getenv("OPS_LEARNING_INGEST_MAX_AGE_HOURS", "336")),  # 14 days
    ),
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
class OutputFreshness:
    """Freshness of a registered feedback-loop output table."""
    table: str
    max_age_hours: int
    latest: Optional[datetime]
    age_hours: Optional[float]
    status: str  # "ok" | "stale" | "never" | "error"


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
        stale_threshold_minutes: Threshold for staleness (default: 360 via
            OPS_DATA_STALE_MINUTES — retuned from 30, P1-B 2026-07-02)

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


def _rth_job_status(
    cadence: str,
    last_success_at: Optional[datetime],
    now: datetime,
) -> str:
    """Staleness verdict for an intraday RTH-only job (monitor / order_sync /
    heartbeat). DETECTION ONLY — never restarts anything.

    Closed market / weekend → always 'ok': the scheduler fires these jobs only
    during the regular session (and each job's own broker-clock gate
    short-circuits out-of-session fires), so silence then is BY DESIGN and must
    never alarm.

    Inside the session, the job is stale once it has missed its cadence by a
    margin. Elapsed time is measured from max(last_success, conservative
    session open) so the start-of-session warm-up — and the winter DST hour
    where is_us_market_hours() leads the real open — cannot false-positive:
    right at the open the prior session's last run is hours stale, but today's
    open is recent, so nothing fires until the first in-session run could have
    landed. Returns 'late' when a prior success exists, 'never_run' when none
    does — matching the existing daily/weekly status vocabulary so the
    ops_health_check handler alerts through its current job_late /
    job_never_run path with no change.
    """
    if not is_us_market_hours(now):
        return "ok"
    interval = _RTH_CADENCE_MINUTES.get(cadence, 15)
    threshold = timedelta(minutes=interval + OPS_INTRADAY_STALENESS_MARGIN_MIN)
    open_h, open_m = _RTH_WARMUP_OPEN_UTC
    session_open = now.replace(
        hour=open_h, minute=open_m, second=0, microsecond=0
    )
    anchor = (
        last_success_at
        if (last_success_at is not None and last_success_at > session_open)
        else session_open
    )
    if (now - anchor) <= threshold:
        return "ok"
    return "late" if last_success_at is not None else "never_run"


def _weekend_excluded_age(last_success: datetime, now: datetime) -> timedelta:
    """Wall-clock age minus UTC-weekend hours inside the window (P1-B).

    The daily jobs are scheduled mon–fri; weekend silence is BY DESIGN
    (§6). Measured on the wall clock, Friday's run is >26h old from Monday
    13:07Z until it reruns that evening — 20 false `job_late` warns every
    Monday (40 observed in 14d). A flat threshold raise (~74h) would instead
    delay real Tue–Fri detection by days, so the age itself excludes full
    UTC Sat/Sun hours: Friday-evening→Monday-morning reads ~16h (ok), while
    a job that actually misses Monday reads ~40h by Tuesday (late).

    UTC weekend vs the CT schedule skews the exclusion by a few evening
    hours on Friday/Sunday — all four daily jobs run 13:00–22:10Z, well
    inside UTC weekdays, so the skew never spans a scheduled fire. Windows
    longer than 30 days skip the exclusion (already unambiguously late).
    """
    age = now - last_success
    if age > timedelta(days=30):
        return age
    weekend = timedelta(0)
    day = last_success.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < now:
        nxt = day + timedelta(days=1)
        if day.weekday() >= 5:  # Saturday=5, Sunday=6
            start = max(day, last_success)
            end = min(nxt, now)
            if end > start:
                weekend += end - start
        day = nxt
    return age - weekend


def get_expected_jobs(
    client, now: Optional[datetime] = None
) -> List[ExpectedJob]:
    """
    Get status of expected scheduled jobs.

    Args:
        client: Supabase client
        now: Optional reference time (UTC) — defaults to wall-clock now.
            Injectable so the intraday market-hours gating is deterministically
            testable.

    Returns:
        List of ExpectedJob with name, cadence, last_success_at, status.
    """
    results = []
    now = now or datetime.now(timezone.utc)

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

            # Intraday RTH-only jobs (monitor / order_sync / heartbeat) use a
            # market-hours-gated staleness check so closed-market silence is
            # never flagged; everything else keeps the daily/weekly logic.
            if cadence in _RTH_CADENCE_MINUTES:
                last_success = None
                if result.data and len(result.data) > 0:
                    fa = result.data[0].get("finished_at")
                    if fa:
                        if fa.endswith("Z"):
                            fa = fa.replace("Z", "+00:00")
                        last_success = datetime.fromisoformat(fa)
                        if last_success.tzinfo is None:
                            last_success = last_success.replace(tzinfo=timezone.utc)
                results.append(ExpectedJob(
                    name=job_name,
                    cadence=cadence,
                    last_success_at=last_success,
                    status=_rth_job_status(cadence, last_success, now),
                ))
                continue

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
                    # Daily mon–fri jobs: weekend hours don't count against
                    # the 26h (the Monday-storm fix, P1-B). Weekly cadence
                    # keeps wall-clock age (8d already tolerates a weekend).
                    if cadence == "daily":
                        age = _weekend_excluded_age(finished_at, now)
                    else:
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


def get_output_freshness(client) -> List[OutputFreshness]:
    """
    Check every registered feedback-loop output table for freshness.

    "ok" = newest row younger than max_age_hours; "stale" = older; "never" =
    table empty; "error" = the check itself failed (reported, not swallowed —
    a broken checker must not read as healthy).
    """
    results: List[OutputFreshness] = []
    now = datetime.now(timezone.utc)

    for table, ts_col, max_age_hours in OUTPUT_FRESHNESS:
        try:
            res = client.table(table) \
                .select(ts_col) \
                .order(ts_col, desc=True) \
                .limit(1) \
                .execute()
            if not res.data:
                results.append(OutputFreshness(table, max_age_hours, None, None, "never"))
                continue
            raw = str(res.data[0].get(ts_col))
            ts = raw.replace("Z", "+00:00").replace(" ", "T", 1)
            latest = datetime.fromisoformat(ts)
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age_hours = (now - latest).total_seconds() / 3600.0
            status = "stale" if age_hours > max_age_hours else "ok"
            results.append(OutputFreshness(table, max_age_hours, latest, round(age_hours, 1), status))
        except Exception as e:
            logger.warning(f"Output freshness check failed for {table}: {e}")
            results.append(OutputFreshness(table, max_age_hours, None, None, "error"))

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


def get_silent_job_failures(client, hours: int = 24) -> List[Dict[str, Any]]:
    """A4 silent-failure detector: jobs that reported ``status='succeeded'``
    while their OWN ``result.counts.errors`` was > 0.

    This is the MASKING class that hid ``paper_learning_ingest`` running 5×
    "succeeded" with ``errors=1`` for 6 days unseen — a job that swallows
    per-item exceptions, tallies them into ``counts.errors``, and still
    returns success is INVISIBLE to ``get_recent_failures`` (which keys on the
    job_runs ``status`` column). This surfaces it through the existing
    ops-health alert path.

    Best-effort: a query failure is logged and yields ``[]`` (the check must
    never crash the health cycle). The JSON shape is read defensively — a row
    whose ``result``/``counts`` is missing or non-numeric is skipped, never
    counted as an offender.

    Returns:
        List of ``{job_name, error_count, finished_at, run_id}`` dicts, one per
        offending run, newest first.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = client.table("job_runs") \
            .select("id, job_name, finished_at, result") \
            .eq("status", "succeeded") \
            .gte("finished_at", since) \
            .order("finished_at", desc=True) \
            .limit(200) \
            .execute()

        offenders: List[Dict[str, Any]] = []
        for row in result.data or []:
            res = row.get("result")
            if not isinstance(res, dict):
                continue
            counts = res.get("counts")
            if not isinstance(counts, dict):
                continue
            raw_errors = counts.get("errors")
            try:
                error_count = int(raw_errors)
            except (TypeError, ValueError):
                continue
            if error_count > 0:
                offenders.append({
                    "job_name": row.get("job_name"),
                    "error_count": error_count,
                    "finished_at": row.get("finished_at"),
                    "run_id": row.get("id"),
                })
        return offenders
    except Exception as e:
        logger.warning(f"Failed to check silent job failures: {e}")
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


# Regime-conditional staleness — 2026-05-18 fix.
#
# The per-symbol staleness decision used to be:
#   is_symbol_stale = snap.quality.is_stale OR (freshness_ms > threshold)
#
# `snap.quality.is_stale` is set by MarketDataTruthLayer.snapshot_many_v4
# based on vendor-quote-completeness / market-hours / quote-quality logic
# that is INDEPENDENT of timestamp age. During routine regimes it
# frequently fires on SIP-entitled core symbols (SPY/QQQ) within the
# first few minutes after data refresh — well under the 600s timestamp
# threshold. Combined with the SPY-or-QQQ override below, a single
# vendor-quality flag would block an entire entry cycle.
#
# The 2026-05-18 18:01:48 UTC paper_auto_execute block on CSX was the
# forcing example: regime=normal, freshness=108s (1.8 min), threshold=600s,
# but SPY+QQQ both flagged via `is_stale=True` from the vendor side.
#
# Fix: activate the vendor-quality clause ONLY in volatile regimes
# (shock, elevated). In all other regimes — normal, suppressed, chop,
# rebound — fall back to timestamp-vs-threshold only. The regime list
# mirrors CLAUDE.md "Risk per trade math" regime_mult semantics: the
# regimes that trigger sub-1.0 risk multipliers (shock=0.5, elevated=0.8)
# are also the ones that justify extra caution on data quality.
#
# Fail-closed: unknown regime → treat as shock (vendor clause active).
_REGIME_VENDOR_QUALITY_GATED = frozenset({"shock", "elevated"})


def _resolve_regime_for_staleness(regime: Optional[str]) -> str:
    """Normalize caller-provided regime; fall back to the last recorded
    cycle regime if None. If lookup yields no usable value, return
    'shock' so the vendor-quality clause activates (fail-closed).

    The lookup queries the most recent `suggestions_open` job_run for
    its enriched cycle_metadata.regime — same data PR #959 wires up.
    Single indexed query, ~tens of ms; logged on failure but never
    raises (the staleness gate must remain fast and safe)."""
    if regime:
        normalized = regime.strip().lower()
        if normalized:
            return normalized
    try:
        from packages.quantum.jobs.handlers.utils import get_admin_client
        client = get_admin_client()
        # Post-PR \<cycle-metadata-symmetry\>: cycle_metadata is now
        # emitted at all 7 return paths of run_midday_cycle, but pre-
        # budget early-exits (micro_tier_position_open,
        # capital_scan_policy_block) intentionally leave regime=None
        # because the budget engine never ran. Iterate the recent
        # cycles to find one with a populated regime rather than
        # short-circuiting to 'shock' the moment a pre-budget exit
        # is the most-recent row. Fail-closed to 'shock' still
        # applies when no recent cycle has regime data.
        row = (
            client.table("job_runs")
            .select("result")
            .eq("job_name", "suggestions_open")
            .eq("status", "succeeded")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        for cycle_row in (row.data or []):
            result = cycle_row.get("result") or {}
            cycle_results = result.get("cycle_results") or []
            if not cycle_results:
                continue
            meta = cycle_results[0].get("cycle_metadata") or {}
            last_regime = meta.get("regime")
            if last_regime:
                return str(last_regime).strip().lower()
    except Exception as e:
        logger.warning(
            f"[FRESHNESS] regime lookup failed; failing closed "
            f"(treating as 'shock'): {e}"
        )
    return "shock"


def compute_market_data_freshness(
    universe: List[str],
    stale_threshold_ms: int = MARKET_DATA_STALE_THRESHOLD_MS,
    regime: Optional[str] = None,
) -> MarketDataFreshnessResult:
    """
    Check actual market data freshness for symbols in universe.

    Uses MarketDataTruthLayer.snapshot_many_v4() for real-time freshness.
    Stale if ANY core symbol (SPY/QQQ) stale OR >50% universe stale.

    The per-symbol decision is regime-conditional (2026-05-18 fix):
    `snap.quality.is_stale` only contributes in 'shock' / 'elevated'
    regimes. In other regimes the timestamp threshold is the sole gate.
    See _REGIME_VENDOR_QUALITY_GATED above for full rationale.

    Args:
        universe: List of ticker symbols to check
        stale_threshold_ms: Staleness threshold in milliseconds (default: 20 min)
        regime: Current market regime ('normal' | 'suppressed' | 'chop' |
            'rebound' | 'elevated' | 'shock'). If None, the function
            resolves it via the most recent suggestions_open cycle's
            recorded regime; if that lookup fails, falls back to 'shock'
            (fail-closed — vendor-quality clause stays active).

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

    resolved_regime = _resolve_regime_for_staleness(regime)
    use_vendor_quality_flag = resolved_regime in _REGIME_VENDOR_QUALITY_GATED

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
            # Regime-conditional vendor-quality clause: snap.quality.is_stale
            # contributes only in shock/elevated regimes. The timestamp
            # threshold always contributes. See _REGIME_VENDOR_QUALITY_GATED
            # above for the 2026-05-18 incident that motivated this.
            timestamp_stale = (
                freshness_ms is not None and freshness_ms > stale_threshold_ms
            )
            vendor_quality_stale = (
                use_vendor_quality_flag and snap.quality.is_stale
            )
            is_symbol_stale = vendor_quality_stale or timestamp_stale
            if is_symbol_stale:
                stale_symbols.append(symbol)
            if freshness_ms is not None and freshness_ms > worst_age_ms:
                worst_age_ms = freshness_ms

        # Compute overall staleness — SPY-or-QQQ override UNCHANGED.
        # This intentionally applies regardless of how is_symbol_stale
        # was computed above; the override is correct policy and only
        # the per-symbol decision was over-tightened.
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
    min_severity: str = OPS_ALERT_MIN_SEVERITY,
    client: Any = None,
) -> Dict[str, Any]:
    """
    Enhanced alert sender — DUAL-CHANNEL (v5-A4, 2026-06-11).

    Primary channel: `risk_alerts` via the canonical observability alert()
    (requires `client`). Secondary, best-effort: the Slack-compatible
    webhook. `sent` is True if EITHER channel delivered. Severity map for
    risk_alerts: critical→critical, error→high, warning→warning — critical
    and high land in every H11 baseline sweep.

    Args:
        alert_type: Type of alert
        message: Human-readable alert message
        details: Optional additional context
        severity: Override severity (defaults to ALERT_SEVERITY mapping)
        webhook_url: Override webhook URL
        min_severity: Minimum severity to send (default from env)
        client: Supabase client for the risk_alerts channel (None → legacy
            webhook-only with a loud warning)

    Returns:
        Dict with: sent, suppressed_reason, fingerprint, severity,
        risk_alert_written, webhook_sent
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
        "risk_alert_written": False,
        "webhook_sent": False,
    }

    # Check severity threshold. v5-A4 fix: "critical" was MISSING from this
    # map — severity_order.get("critical", 0) = 0 < warning(1), so the most
    # severe class (job_never_run) was the only one ALWAYS suppressed.
    severity_order = {"critical": 3, "error": 2, "warning": 1}
    if severity_order.get(severity, 0) < severity_order.get(min_severity, 0):
        result["suppressed_reason"] = "below_min_severity"
        logger.info(f"[OPS_ALERT] Suppressed {alert_type} (severity {severity} < min {min_severity})")
        return result

    # ── Channel 1 (PRIMARY, v5-A4): risk_alerts — the table the operator
    # and every H11 sweep actually read. Pre-fix, delivery was webhook-only
    # and OPS_ALERT_WEBHOOK_URL has never been configured on this deploy,
    # so every detected issue (incl. the 25-day calibration freeze) died
    # with suppressed_reason="no_webhook" — detected, never delivered.
    if client is not None:
        try:
            from packages.quantum.observability.alerts import alert as _risk_alert
            _risk_alert(
                client,
                alert_type=f"ops_{alert_type}",
                severity={"critical": "critical", "error": "high"}.get(severity, "warning"),
                message=f"[OPS_HEALTH] {message[:400]}",
                user_id=None,
                metadata={
                    "source": "ops_health_check",
                    "ops_alert_type": alert_type,
                    "ops_severity": severity,
                    "fingerprint": fingerprint,
                    **({"details": details} if details else {}),
                },
            )
            result["risk_alert_written"] = True
            result["sent"] = True
        except Exception as e:
            logger.warning(f"[OPS_ALERT] risk_alerts write failed: {e}")
    else:
        logger.warning(
            f"[OPS_ALERT] no supabase client passed — risk_alerts channel "
            f"skipped for {alert_type} (webhook-only legacy mode)"
        )

    # ── Channel 2 (secondary, best-effort): Slack-compatible webhook.
    url = webhook_url or os.getenv("OPS_ALERT_WEBHOOK_URL")
    if not url:
        if not result["sent"]:
            result["suppressed_reason"] = "no_webhook"
        logger.info(f"[OPS_ALERT] No webhook configured for: {alert_type}")
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
            result["webhook_sent"] = True
            result["sent"] = True
        else:
            logger.warning(f"[OPS_ALERT] Webhook returned {response.status_code}")
            if not result["sent"]:
                result["suppressed_reason"] = f"webhook_error:{response.status_code}"
    except Exception as e:
        logger.warning(f"[OPS_ALERT] Failed to send alert: {e}")
        if not result["sent"]:
            result["suppressed_reason"] = f"exception:{str(e)[:30]}"

    return result


# ── Direct-insert alert egress relay (A3 / P1 Window-2, 2026-07-02) ──────
#
# 13 production sites insert risk_alerts rows DIRECTLY (force_close in the
# intraday monitor, order-handler throttles, scanner, policy-lab, scheduler
# dead-letter, exit evaluator, …) without going through observability
# alert() — so #1096's egress never sees them: with the webhook armed, a
# direct-insert critical still reached nobody. This relay polls the TABLE
# (the one choke point every writer shares) and pushes unseen critical/high
# rows out the SAME Channel-2 webhook, so egress coverage becomes a property
# of the table instead of a property of each writer.
#
# Double-send boundaries (both sides already own their egress):
#   - rows written by send_ops_alert_v2 Channel 1: alert_type "ops_*"
#     (its Channel 2 already ran in the same call) → excluded.
#   - rows written by alert() for the #1096 allowlist: alert() now
#     pre-stamps metadata.egress_owner="alert" → excluded.
#
# Epoch guard (#1051 pattern): rows created before ALERT_RELAY_EPOCH never
# relay — the ~1,040 un-acked historical critical/high rows must not fire
# at the operator on first poll. Verified 0 critical/high rows existed
# after this epoch at build time.
ALERT_RELAY_EPOCH_DEFAULT = "2026-07-02T00:00:00+00:00"
ALERT_RELAY_MAX_PER_POLL = int(os.getenv("ALERT_RELAY_MAX_PER_POLL", "10"))
_ALERT_RELAY_WINDOW = 100  # newest-first scan window; sent rows drop out via marker
_RELAY_SEVERITY_TO_OPS = {"critical": "critical", "high": "error"}


def _relay_epoch() -> str:
    return os.getenv("ALERT_RELAY_EPOCH") or ALERT_RELAY_EPOCH_DEFAULT


def relay_direct_insert_alerts(
    client: Any, *, max_per_poll: Optional[int] = None
) -> Dict[str, Any]:
    """Egress un-relayed post-epoch critical/high risk_alerts rows.

    Best-effort by contract: every failure mode (query error, webhook down,
    mark-write error) logs a WARNING and leaves the row unmarked so the next
    poll retries it; this function never raises. Channel-2-only send
    (client=None) — the existing row IS the DB record; no duplicate insert.
    Rate-guarded at ``max_per_poll`` sends per cycle (capped → WARNING).
    """
    result: Dict[str, Any] = {
        "scanned": 0, "sent": 0, "skipped": 0, "failed": 0,
        "capped": False, "pending_after_cap": 0,
    }
    if client is None:
        result["failed"] += 1
        logger.warning("[ALERT_RELAY] no supabase client — cycle skipped")
        return result
    cap = ALERT_RELAY_MAX_PER_POLL if max_per_poll is None else max_per_poll
    epoch = _relay_epoch()

    try:
        res = (
            client.table("risk_alerts")
            .select(
                "id, alert_type, severity, message, symbol, position_id, "
                "created_at, metadata"
            )
            .in_("severity", ["critical", "high"])
            .gt("created_at", epoch)
            .order("created_at", desc=True)
            .limit(_ALERT_RELAY_WINDOW)
            .execute()
        )
        rows = list(res.data or [])
    except Exception as e:
        logger.warning(f"[ALERT_RELAY] poll query failed (retry next cycle): {e}")
        result["failed"] += 1
        return result

    # Oldest first so a burst drains in arrival order under the cap.
    rows.reverse()
    eligible = []
    for row in rows:
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        if meta.get("egressed_at") or meta.get("egress_owner"):
            result["skipped"] += 1
            continue
        if str(row.get("alert_type") or "").startswith("ops_"):
            result["skipped"] += 1
            continue
        eligible.append((row, meta))

    consecutive_failures = 0
    for row, meta in eligible:
        if result["sent"] >= cap:
            result["capped"] = True
            result["pending_after_cap"] = len(eligible) - result["scanned"]
            logger.warning(
                f"[ALERT_RELAY] per-poll cap {cap} reached; "
                f"{result['pending_after_cap']} row(s) deferred to next poll"
            )
            break
        if consecutive_failures >= 3:
            # Webhook is clearly down — stop burning 10s timeouts inside the
            # health-check job; everything unmarked retries next poll.
            logger.warning(
                "[ALERT_RELAY] 3 consecutive send failures — webhook likely "
                "down; deferring remaining rows to next poll"
            )
            break
        result["scanned"] += 1
        try:
            send_res = send_ops_alert_v2(
                alert_type=str(row.get("alert_type") or "unknown"),
                message=str(row.get("message") or ""),
                details={
                    "relayed_from": "risk_alerts",
                    "risk_alert_id": row.get("id"),
                    "row_severity": row.get("severity"),
                    "row_created_at": row.get("created_at"),
                    **({"symbol": row["symbol"]} if row.get("symbol") else {}),
                    **(
                        {"position_id": row["position_id"]}
                        if row.get("position_id")
                        else {}
                    ),
                },
                severity=_RELAY_SEVERITY_TO_OPS.get(
                    str(row.get("severity") or ""), "warning"
                ),
                # Channel 2 ONLY: Channel 1 would insert a duplicate DB row.
                client=None,
            )
        except Exception as e:
            result["failed"] += 1
            consecutive_failures += 1
            logger.warning(
                f"[ALERT_RELAY] send failed for {row.get('id')} "
                f"(retry next cycle): {e}"
            )
            continue

        if send_res.get("webhook_sent"):
            outcome_meta = {
                **meta,
                "egressed_at": datetime.now(timezone.utc).isoformat(),
                "egress_owner": "relay",
            }
            result["sent"] += 1
            consecutive_failures = 0
        elif send_res.get("suppressed_reason") == "below_min_severity":
            # Deterministic suppression under current config — retrying every
            # poll would spin forever; mark it skipped-with-reason instead.
            outcome_meta = {
                **meta,
                "egress_owner": "relay",
                "egress_skipped": "below_min_severity",
            }
            result["skipped"] += 1
        else:
            # no_webhook / webhook error / send exception → unmarked, so the
            # next poll retries. Deliberate: criticals that landed while the
            # channel was down/disarmed still reach the operator on recovery
            # (bounded by the per-poll cap).
            result["failed"] += 1
            consecutive_failures += 1
            logger.warning(
                f"[ALERT_RELAY] webhook not delivered for {row.get('id')} "
                f"({send_res.get('suppressed_reason')}); will retry"
            )
            continue

        try:
            client.table("risk_alerts").update({"metadata": outcome_meta}).eq(
                "id", row["id"]
            ).execute()
        except Exception as e:
            # Sent but unmarked → next poll may re-send this one row. The
            # duplicate is preferable to silently never marking (best-effort).
            logger.warning(
                f"[ALERT_RELAY] mark-write failed for {row.get('id')}: {e}"
            )

    return result
