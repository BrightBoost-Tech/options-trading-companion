"""Observability remainder (queue ②, 2026-07-11) — 5 noise-class closures.

Fix 1 gets a behavioral test in BOTH directions (flat book suppressed, held
book still fires — the guard must not eat a real stale-mark alert). Fixes 2-5
are pinned on the production code (the seams need heavy job-run mocking; the
partial-classification they rely on is covered by test_typed_job_outcome).
"""

from pathlib import Path

from packages.quantum.services.ops_health_service import (
    get_output_freshness,
    EXPECTED_JOBS,
)

_Q = Path(__file__).parent.parent


class _Exec:
    def __init__(self, data, count):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, data, count):
        self._d, self._c = data, count

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Exec(self._d, self._c)


class _Client:
    """One row (an OLD mark → stale) + a configurable open-position count."""
    def __init__(self, open_count):
        self._count = open_count

    def table(self, name):
        # old timestamp → every freshness entry reads 'stale' by age
        return _Query([{"last_marked_at": "2026-01-01T00:00:00+00:00"}], self._count)


def _pp(results):
    return next(r for r in results if r.table == "paper_positions").status


class TestFlatBookGuard:
    def test_flat_book_suppresses_stale_mark(self):
        # 0 open positions → the aged mark is by-design, not a failure → 'flat'
        assert _pp(get_output_freshness(_Client(open_count=0))) == "flat"

    def test_held_book_still_fires_stale(self):
        # a HELD position unmarked past TTL is a REAL dead mark-refresh loop
        assert _pp(get_output_freshness(_Client(open_count=1))) == "stale"

    def test_flat_status_does_not_alert(self):
        # the alert path fires only on 'stale'/'never' — 'flat' must be neither
        assert _pp(get_output_freshness(_Client(open_count=0))) not in ("stale", "never")


class TestWiring:
    def _txt(self, *p):
        return _Q.joinpath(*p).read_text(encoding="utf-8")

    def test_expected_jobs_watch_real_producer(self):
        names = [j[0] for j in EXPECTED_JOBS]
        assert "paper_learning_ingest" in names  # the real EOD producer
        assert "learning_ingest" not in names    # the no-op stub is unwatched

    def test_condition_dedup_by_run_id(self):
        # Durable re-fire dedup (2026-07-20) REPLACED the 2026-07-11 last-5-runs
        # fingerprint cooldown (its ~2.5h read-back window was far shorter than
        # the 24h re-detection lookback → the same run re-emitted ~every 3h).
        # The emit is now keyed on the append-only risk_alerts rows themselves.
        # AUTHORITATIVE route-driven coverage (first emits, repeat suppressed,
        # changed signature / bumped version re-emit, double-poll → exactly one,
        # historical NULL-version row suppresses) lives in
        # test_alert_resilience_a4_detector.py; this only guards the seam.
        src = self._txt("jobs", "handlers", "ops_health_check.py")
        assert "find_prior_silent_failure_alert(" in src
        assert "detector_version=A4_DETECTOR_VERSION" in src

    def test_accuracy_dedup_on_value_change_and_daily(self):
        src = self._txt("jobs", "handlers", "ops_health_check.py")
        assert '"wins": overall.get("wins"), "n": overall.get("n")' in src
        assert "should_suppress_alert(client, fingerprint, 1440)" in src

    def test_iv_all_missing_emits_counts_errors(self):
        src = self._txt("jobs", "handlers", "iv_daily_refresh.py")
        assert '_all_missing = stats["ok"] == 0 and len(symbols) > 0' in src
        assert '"counts": {"errors": stats["missing_data"] if _all_missing else 0}' in src
