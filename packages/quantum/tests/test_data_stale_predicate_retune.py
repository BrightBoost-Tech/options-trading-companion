"""P1-B (2026-07-02) — data_stale predicate retune. PREDICATE ONLY:
#1106's content/fingerprint wiring is untouched (its pins run separately).

Pins:
- default threshold 30→360 (owner-approved; 39/39 job-arm firings in 14d
  were false HIGHs; max healthy in-gate age observed = 187 min);
- 187-min age → NOT stale; a genuinely dead job (367 min) → stale SAME-DAY;
- daily job_late measures weekend-excluded age (the Monday-storm fix):
  Friday-evening→Monday-morning reads ~16h (ok), a job that actually missed
  Monday reads ~40h by Tuesday (late); Tue–Fri detection unchanged;
- weekend exclusion is hour-accurate and passes through on >30d windows.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from packages.quantum.services.ops_health_service import (
    DATA_STALE_THRESHOLD_MINUTES,
    _weekend_excluded_age,
    compute_data_freshness,
    get_expected_jobs,
)


def _freshness_client(finished_at_iso):
    client = MagicMock()
    (
        client.table.return_value
        .select.return_value
        .in_.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = MagicMock(data=[{"finished_at": finished_at_iso, "job_name": "suggestions_open"}])
    return client


def _jobs_client(last_success_iso):
    client = MagicMock()
    data = [] if last_success_iso is None else [
        {"finished_at": last_success_iso, "status": "succeeded"}
    ]
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return client


def _status(results, name):
    return next(j for j in results if j.name == name).status


DAILY_JOBS = (
    "suggestions_close", "suggestions_open",
    "learning_ingest", "daily_progression_eval",
)

# Anchors: Friday 2026-06-26 21:15Z (post-learning-chain success) and the
# following Monday/Tuesday 13:07Z checks (the observed storm window).
FRIDAY_RUN = datetime(2026, 6, 26, 21, 15, tzinfo=timezone.utc)
MONDAY_CHECK = datetime(2026, 6, 29, 13, 7, tzinfo=timezone.utc)
TUESDAY_CHECK = datetime(2026, 6, 30, 13, 7, tzinfo=timezone.utc)


class TestThresholdRetune:
    def test_default_threshold_is_360(self):
        assert DATA_STALE_THRESHOLD_MINUTES == 360

    def test_observed_max_healthy_age_not_stale(self):
        # 187 min = the worst healthy in-gate age observed over 10/10
        # trading days (19:07Z check vs the 16:00Z suggestions_open run).
        ts = (datetime.now(timezone.utc) - timedelta(minutes=187)).isoformat()
        res = compute_data_freshness(_freshness_client(ts))
        assert res.is_stale is False

    def test_dead_job_still_alerts_same_day(self):
        # suggestions_open dead → by the 19:07Z check the age is 367 min.
        ts = (datetime.now(timezone.utc) - timedelta(minutes=367)).isoformat()
        res = compute_data_freshness(_freshness_client(ts))
        assert res.is_stale is True
        assert "360" in (res.reason or "")

    def test_explicit_threshold_arg_still_honored(self):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        res = compute_data_freshness(_freshness_client(ts), stale_threshold_minutes=30)
        assert res.is_stale is True


class TestMondayWarmupAnchor:
    def test_monday_morning_after_friday_run_is_ok(self):
        client = _jobs_client(FRIDAY_RUN.isoformat())
        results = get_expected_jobs(client, now=MONDAY_CHECK)
        for name in DAILY_JOBS:
            assert _status(results, name) == "ok", (
                f"{name}: Friday-evening success must not read late Monday "
                f"morning — weekend silence is by design"
            )

    def test_actually_missed_monday_flags_tuesday(self):
        client = _jobs_client(FRIDAY_RUN.isoformat())
        results = get_expected_jobs(client, now=TUESDAY_CHECK)
        for name in DAILY_JOBS:
            assert _status(results, name) == "late", (
                f"{name}: a job that really missed Monday must flag by "
                f"Tuesday (weekend-excluded age ~40h > 26h)"
            )

    def test_tue_fri_detection_unchanged(self):
        # 27h gap with no weekend inside → late, exactly as before.
        wednesday_run = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
        thursday_check = datetime(2026, 7, 2, 17, 0, tzinfo=timezone.utc)
        client = _jobs_client(wednesday_run.isoformat())
        results = get_expected_jobs(client, now=thursday_check)
        for name in DAILY_JOBS:
            assert _status(results, name) == "late"

    def test_never_run_unchanged(self):
        client = _jobs_client(None)
        results = get_expected_jobs(client, now=TUESDAY_CHECK)
        for name in DAILY_JOBS:
            assert _status(results, name) == "never_run"


class TestWeekendExcludedAge:
    def test_full_weekend_excluded_hour_accurate(self):
        # Fri 22:00 → Mon 13:00 = 63h wall − 48h weekend = 15h.
        last = datetime(2026, 6, 26, 22, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 29, 13, 0, tzinfo=timezone.utc)
        assert _weekend_excluded_age(last, now) == timedelta(hours=15)

    def test_window_starting_mid_saturday_partial_exclusion(self):
        # Sat 12:00 → Mon 12:00 = 48h wall − (12h Sat + 24h Sun) = 12h.
        last = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
        assert _weekend_excluded_age(last, now) == timedelta(hours=12)

    def test_no_weekend_in_window_is_wall_clock(self):
        last = datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        assert _weekend_excluded_age(last, now) == timedelta(hours=24)

    def test_over_30d_passthrough(self):
        last = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        assert _weekend_excluded_age(last, now) == now - last
