"""
Tests for the scheduler-watchdog staleness detection (DETECTION ONLY).

Covers the SPOF gap where a single in-process scheduler runs the monitor, the
exits, AND its own watchdog:

  - `intraday_risk_monitor` (q15min) and `alpaca_order_sync` (q5min) were NOT
    in EXPECTED_JOBS, so a monitor that simply STOPS being scheduled wrote no
    job_runs and was UNDETECTED.
  - `scheduler_heartbeat` was PRODUCED by scheduler.py but never CONSUMED.

These tests assert:

  1. A silent `intraday_risk_monitor` DURING RTH is FLAGGED (load-bearing —
     a silent monitor is now detected).
  2. The SAME silence on a CLOSED market / weekend is NOT flagged (no false
     positive — weekend / overnight silence is by design).
  3. A silent / stale `scheduler_heartbeat` during RTH is FLAGGED (the new
     consumer).
  4. Supporting guards: healthy mid-session jobs stay 'ok', the start-of-
     session warm-up does not false-positive, and order_sync staleness is
     detected.

No auto-restart anywhere — the production code only sets a status that the
existing ops_health_check handler turns into a job_late / job_never_run alert.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from packages.quantum.services.ops_health_service import (
    EXPECTED_JOBS,
    _RTH_CADENCE_MINUTES,
    get_expected_jobs,
    is_us_market_hours,
)


# A weekday inside RTH (Mon-Fri 13:30-20:00 UTC): Monday 2026-06-29 17:00Z.
RTH_NOW = datetime(2026, 6, 29, 17, 0, tzinfo=timezone.utc)
# A weekend (Sunday 2026-06-28) — market closed all day.
WEEKEND_NOW = datetime(2026, 6, 28, 17, 0, tzinfo=timezone.utc)
# A weekday AFTER the close: Monday 2026-06-29 23:00Z (outside 13:30-20:00).
AFTER_HOURS_NOW = datetime(2026, 6, 29, 23, 0, tzinfo=timezone.utc)


def _mock_client(last_success_iso):
    """Supabase client stub whose last-succeeded job_run query returns
    `last_success_iso` for EVERY job_name. Pass None for "never ran"."""
    client = MagicMock()
    data = [] if last_success_iso is None else [
        {"finished_at": last_success_iso, "status": "succeeded"}
    ]
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return client


def _status(results, name):
    return next(j for j in results if j.name == name).status


def test_market_hours_anchors_are_what_we_think():
    """Guard: the chosen reference times really are in/out of RTH so the
    other assertions test what they claim."""
    assert is_us_market_hours(RTH_NOW) is True
    assert is_us_market_hours(WEEKEND_NOW) is False
    assert is_us_market_hours(AFTER_HOURS_NOW) is False


def test_intraday_jobs_registered():
    """The two loss-protection monitors + the heartbeat are on the watchlist
    with intraday RTH cadences."""
    registry = dict(EXPECTED_JOBS)
    assert registry["intraday_risk_monitor"] == "rth_15min"
    assert registry["alpaca_order_sync"] == "rth_5min"
    assert registry["scheduler_heartbeat"] == "rth_30min"
    for cad in ("rth_5min", "rth_15min", "rth_30min"):
        assert cad in _RTH_CADENCE_MINUTES


def test_monitor_stale_during_rth_is_flagged():
    """LOAD-BEARING: a monitor that last ran 2h ago, evaluated DURING RTH,
    is flagged (status 'late') — the previously-silent monitor is detected."""
    last = (RTH_NOW - timedelta(hours=2)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=RTH_NOW)
    assert _status(results, "intraday_risk_monitor") == "late"


def test_monitor_never_ran_during_rth_is_flagged():
    """A monitor with NO successful run, evaluated mid-session past the warm-up,
    is flagged 'never_run'."""
    results = get_expected_jobs(_mock_client(None), now=RTH_NOW)
    assert _status(results, "intraday_risk_monitor") == "never_run"


def test_monitor_stale_when_market_closed_not_flagged_weekend():
    """NO FALSE POSITIVE: the SAME 2h-stale monitor on a WEEKEND is NOT flagged
    (weekend silence is by design)."""
    last = (WEEKEND_NOW - timedelta(hours=2)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=WEEKEND_NOW)
    assert _status(results, "intraday_risk_monitor") == "ok"


def test_monitor_stale_after_hours_not_flagged():
    """NO FALSE POSITIVE: a stale monitor evaluated after the close on a
    weekday is NOT flagged."""
    last = (AFTER_HOURS_NOW - timedelta(hours=6)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=AFTER_HOURS_NOW)
    assert _status(results, "intraday_risk_monitor") == "ok"


def test_monitor_recent_during_rth_is_ok():
    """A monitor that ran 5 min ago mid-session is healthy (no false alarm on
    a live, well-behaved monitor)."""
    last = (RTH_NOW - timedelta(minutes=5)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=RTH_NOW)
    assert _status(results, "intraday_risk_monitor") == "ok"


def test_warmup_no_false_positive_just_after_open():
    """At 14:35Z — minutes into the session — a monitor whose last run is from
    the PRIOR session is NOT yet flagged: the session-open warm-up anchor
    absorbs the overnight gap until the first in-session run could land."""
    just_after_open = datetime(2026, 6, 29, 14, 35, tzinfo=timezone.utc)
    assert is_us_market_hours(just_after_open) is True
    prior_session = datetime(2026, 6, 26, 19, 0, tzinfo=timezone.utc)  # Fri
    results = get_expected_jobs(
        _mock_client(prior_session.isoformat()), now=just_after_open
    )
    assert _status(results, "intraday_risk_monitor") == "ok"


def test_order_sync_stale_during_rth_is_flagged():
    """order_sync (q5min, threshold 20m) silent for 40 min mid-session is
    flagged — fill/orphan reconcile silence is detected."""
    last = (RTH_NOW - timedelta(minutes=40)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=RTH_NOW)
    assert _status(results, "alpaca_order_sync") == "late"


def test_order_sync_within_cadence_is_ok():
    """order_sync that ran 3 min ago is within its q5min cadence — healthy."""
    last = (RTH_NOW - timedelta(minutes=3)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=RTH_NOW)
    assert _status(results, "alpaca_order_sync") == "ok"


def test_heartbeat_silent_during_rth_is_flagged():
    """The scheduler_heartbeat CONSUMER: a heartbeat last seen 2h ago during
    RTH is flagged 'late' (scheduler has gone silent)."""
    last = (RTH_NOW - timedelta(hours=2)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=RTH_NOW)
    assert _status(results, "scheduler_heartbeat") == "late"


def test_heartbeat_never_seen_during_rth_is_flagged():
    """A scheduler that never emitted a heartbeat at all (mid-session, past
    warm-up) is flagged 'never_run'."""
    results = get_expected_jobs(_mock_client(None), now=RTH_NOW)
    assert _status(results, "scheduler_heartbeat") == "never_run"


def test_heartbeat_silent_when_closed_not_flagged():
    """NO FALSE POSITIVE: a long-silent heartbeat on the weekend is NOT flagged
    (the scheduler intentionally idles outside the session window)."""
    last = (WEEKEND_NOW - timedelta(hours=12)).isoformat()
    results = get_expected_jobs(_mock_client(last), now=WEEKEND_NOW)
    assert _status(results, "scheduler_heartbeat") == "ok"


def test_daily_jobs_behavior_unchanged():
    """Regression guard: the daily-cadence path still uses its 26h window —
    a daily job that ran 2h ago is 'ok', and 30h ago is 'late'.

    Fixture updated for P1-B (2026-07-02): daily age is now WEEKEND-EXCLUDED
    (the Monday-storm fix), so the stale case anchors on a Thursday — a 30h
    gap with no weekend inside. The original fixture's 30h window happened to
    cross Sunday (RTH_NOW is a Monday), which correctly reads ~17h effective
    under the new semantics; weekday-gap detection is what this pin protects.
    """
    fresh = get_expected_jobs(
        _mock_client((RTH_NOW - timedelta(hours=2)).isoformat()), now=RTH_NOW
    )
    assert _status(fresh, "suggestions_close") == "ok"
    # Thursday 2026-07-02 17:00Z − 30h = Wednesday 11:00Z: no weekend inside.
    thursday_now = datetime(2026, 7, 2, 17, 0, tzinfo=timezone.utc)
    stale = get_expected_jobs(
        _mock_client((thursday_now - timedelta(hours=30)).isoformat()),
        now=thursday_now,
    )
    assert _status(stale, "suggestions_close") == "late"


def test_query_error_surfaces_as_error_status():
    """A failed job_runs query yields status 'error' (a broken checker must
    not read as healthy), for intraday jobs too."""
    client = MagicMock()
    client.table.side_effect = Exception("DB down")
    results = get_expected_jobs(client, now=RTH_NOW)
    assert _status(results, "intraday_risk_monitor") == "error"
