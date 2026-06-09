"""Tests for the calibration-circuit fix (audit Areas 1+3+4, one defect).

The 2026-05-15→06-09 incident: calibration_update silently no-opped daily
(7 outcomes < MIN_CALIBRATION_TRADES=8 in the fixed 30d window) while
get_calibration_adjustments served the frozen 05-15 blob with no age check,
and apply_calibration silently defaulted ×1.0 for any strategy missing from
the blob (LONG_PUT shipped raw while LONG_CALL was halved).

Pins:
- window escalation: insufficient at 30d → retries 60d/90d, writes on success
- producer honesty: per-user attempt detail; stale alert on persistent no-op
- consumer TTL: blob older than CALIBRATION_MAX_AGE_DAYS → {} + alert,
  never silently served; fresh blob served unchanged; TTL kill switch
- _overall fallback: uncovered strategy gets the blob's overall multiplier
  (logged), not a silent ×1.0; covered segments still win
- ops_health output-freshness registry: ok / stale / never / error
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from packages.quantum.analytics import calibration_service as cs
from packages.quantum.jobs.handlers import calibration_update as cu
from packages.quantum.services import ops_health_service as ohs


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable PostgREST stub returning canned rows per table."""

    def __init__(self, rows, raise_exc=None):
        self._rows = rows
        self._raise = raise_exc

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def insert(self, row):
        self._rows.append(row)
        return self

    def execute(self):
        if self._raise is not None:
            raise self._raise
        return _Result(list(self._rows))


class _Supabase:
    def __init__(self, tables=None, raise_for=None):
        self.tables = tables or {}
        self.raise_for = raise_for or {}
        self.inserted = {}

    def table(self, name):
        return _Query(
            self.tables.setdefault(name, []),
            raise_exc=self.raise_for.get(name),
        )


def _iso(dt):
    return dt.isoformat()


def _outcome(strategy="LONG_PUT_DEBIT_SPREAD", ev=100.0, pnl=-50.0, pop=0.6):
    return {
        "strategy": strategy,
        "regime": "normal",
        "window": "midday_entry",
        "ev_predicted": ev,
        "pop_predicted": pop,
        "pnl_realized": pnl,
        "pnl_predicted": ev,
        "closed_at": _iso(datetime.now(timezone.utc)),
        "details_json": {"dte_at_entry": 30},
    }


# ---------------------------------------------------------------------------
# window escalation (producer)
# ---------------------------------------------------------------------------

class _FakeSvc:
    """compute_calibration_adjustments stub keyed by window_days."""

    def __init__(self, by_window):
        self.by_window = by_window
        self.calls = []

    def compute_calibration_adjustments(self, user_id, window_days):
        self.calls.append(window_days)
        return self.by_window[window_days]


INSUFFICIENT = {"status": "insufficient_data", "sample_size": 7, "minimum_required": 8}
OK = {"status": "ok", "adjustments": {}, "total_outcomes": 18}


class TestWindowEscalation:
    def test_widens_until_sufficient(self):
        svc = _FakeSvc({30: INSUFFICIENT, 60: OK})
        result, window_used, attempts = cu._compute_with_escalation(svc, "user", 30)
        assert result["status"] == "ok"
        assert window_used == 60
        assert svc.calls == [30, 60]
        assert [a["window_days"] for a in attempts] == [30, 60]
        assert attempts[0]["status"] == "insufficient_data"

    def test_stops_at_first_success(self):
        svc = _FakeSvc({30: OK})
        result, window_used, attempts = cu._compute_with_escalation(svc, "user", 30)
        assert window_used == 30
        assert svc.calls == [30]

    def test_exhausts_ladder_when_never_sufficient(self):
        svc = _FakeSvc({30: INSUFFICIENT, 60: INSUFFICIENT, 90: INSUFFICIENT})
        result, window_used, attempts = cu._compute_with_escalation(svc, "user", 30)
        assert result["status"] == "insufficient_data"
        assert window_used == 90
        assert svc.calls == [30, 60, 90]

    def test_escalation_steps_exclude_narrower_than_base(self, monkeypatch):
        monkeypatch.setenv("CALIBRATION_WINDOW_ESCALATION_DAYS", "20,60")
        assert cu._escalation_windows(30) == [30, 60]

    def test_malformed_env_falls_back_to_default_ladder(self, monkeypatch):
        monkeypatch.setenv("CALIBRATION_WINDOW_ESCALATION_DAYS", "sixty,ninety")
        assert cu._escalation_windows(30) == [30, 60, 90]

    def test_corruption_floor_bounds_widened_windows(self, monkeypatch):
        # The service-level guarantee escalation relies on: effective_cutoff
        # never precedes CORRUPTED_PNL_FLOOR no matter how wide the window.
        captured = {}

        class _FloorProbe(cs.CalibrationService):
            def _fetch_outcomes(self, user_id, window_days):
                window_cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=window_days)
                ).isoformat()
                captured["effective"] = max(window_cutoff, cs.CORRUPTED_PNL_FLOOR)
                return []

        _FloorProbe(_Supabase()).compute_calibration_report("u", window_days=365)
        assert captured["effective"] == cs.CORRUPTED_PNL_FLOOR


# ---------------------------------------------------------------------------
# consumer staleness TTL
# ---------------------------------------------------------------------------

def _blob_row(age_days, adjustments=None):
    computed = datetime.now(timezone.utc) - timedelta(days=age_days)
    return {
        "adjustments": adjustments
        or {"LONG_CALL_DEBIT_SPREAD": {"normal": {"_all": {"ev_multiplier": 0.5, "pop_multiplier": 0.5}}}},
        "computed_at": _iso(computed),
    }


class TestConsumerStalenessTTL:
    def setup_method(self):
        cs._STALE_ALERTED_ON = None

    def test_fresh_blob_served(self, monkeypatch):
        monkeypatch.delenv("CALIBRATION_STALENESS_TTL_ENABLED", raising=False)
        sb = _Supabase({"calibration_adjustments": [_blob_row(age_days=1)]})
        adj = cs.get_calibration_adjustments("user", sb)
        assert "LONG_CALL_DEBIT_SPREAD" in adj

    def test_stale_blob_not_served_and_alerted(self, monkeypatch, caplog):
        monkeypatch.delenv("CALIBRATION_STALENESS_TTL_ENABLED", raising=False)
        sb = _Supabase({"calibration_adjustments": [_blob_row(age_days=25)], "risk_alerts": []})
        with caplog.at_level(logging.WARNING):
            adj = cs.get_calibration_adjustments("user", sb)
        assert adj == {}
        assert any("days old" in r.message for r in caplog.records)
        # alert row written (the alerts helper inserts into risk_alerts)
        assert len(sb.tables.get("risk_alerts", [])) == 1

    def test_stale_alert_once_per_day(self, monkeypatch):
        monkeypatch.delenv("CALIBRATION_STALENESS_TTL_ENABLED", raising=False)
        sb = _Supabase({"calibration_adjustments": [_blob_row(age_days=25)], "risk_alerts": []})
        cs.get_calibration_adjustments("user", sb)
        cs.get_calibration_adjustments("user", sb)
        assert len(sb.tables.get("risk_alerts", [])) == 1

    def test_ttl_kill_switch_serves_stale_legacy(self, monkeypatch):
        monkeypatch.setenv("CALIBRATION_STALENESS_TTL_ENABLED", "0")
        sb = _Supabase({"calibration_adjustments": [_blob_row(age_days=25)]})
        adj = cs.get_calibration_adjustments("user", sb)
        assert "LONG_CALL_DEBIT_SPREAD" in adj

    def test_empty_string_flag_is_ON(self, monkeypatch):
        monkeypatch.setenv("CALIBRATION_STALENESS_TTL_ENABLED", "")
        assert cs._staleness_ttl_enabled() is True

    def test_query_error_logged_not_swallowed(self, monkeypatch, caplog):
        sb = _Supabase(raise_for={"calibration_adjustments": RuntimeError("PGRST205")})
        with caplog.at_level(logging.WARNING):
            adj = cs.get_calibration_adjustments("user", sb)
        assert adj == {}
        assert any("get_calibration_adjustments failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _overall fallback in apply_calibration
# ---------------------------------------------------------------------------

class TestOverallFallback:
    ADJ = {
        "LONG_CALL_DEBIT_SPREAD": {"normal": {"_all": {"ev_multiplier": 0.5, "pop_multiplier": 0.5}}},
        cs.OVERALL_KEY: {"ev_multiplier": 0.7, "pop_multiplier": 0.8, "sample_size": 18},
    }

    def test_covered_strategy_uses_its_segment(self):
        ev, pop = cs.apply_calibration(100.0, 0.6, "LONG_CALL_DEBIT_SPREAD", "normal", self.ADJ)
        assert ev == pytest.approx(50.0)
        assert pop == pytest.approx(0.3)

    def test_uncovered_strategy_falls_to_overall_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            ev, pop = cs.apply_calibration(100.0, 0.6, "LONG_PUT_DEBIT_SPREAD", "normal", self.ADJ)
        assert ev == pytest.approx(70.0)
        assert pop == pytest.approx(0.48)
        assert any("no segment coverage" in r.message for r in caplog.records)

    def test_no_overall_no_coverage_is_identity(self):
        adj = {"LONG_CALL_DEBIT_SPREAD": {"normal": {"_all": {"ev_multiplier": 0.5, "pop_multiplier": 0.5}}}}
        ev, pop = cs.apply_calibration(100.0, 0.6, "LONG_PUT_DEBIT_SPREAD", "normal", adj)
        assert ev == pytest.approx(100.0)
        assert pop == pytest.approx(0.6)

    def test_empty_adjustments_is_identity(self):
        ev, pop = cs.apply_calibration(100.0, 0.6, "ANY", "normal", {})
        assert ev == pytest.approx(100.0)
        assert pop == pytest.approx(0.6)

    def test_compute_includes_overall_key(self, monkeypatch):
        svc = cs.CalibrationService(_Supabase())
        outcomes = [_outcome() for _ in range(10)]
        monkeypatch.setattr(svc, "_fetch_outcomes", lambda uid, wd: outcomes)
        result = svc.compute_calibration_adjustments("user", window_days=30)
        assert result["status"] == "ok"
        overall = result["adjustments"].get(cs.OVERALL_KEY)
        assert overall is not None
        assert overall["sample_size"] == 10
        # predicted +100 avg vs realized -50 avg → clamp floor 0.5
        assert overall["ev_multiplier"] == pytest.approx(0.5)

    def test_overall_key_cannot_shadow_a_strategy(self):
        # _get_current_multiplier-style lookups navigate adjustments[strategy];
        # the reserved key must never collide with a real strategy name.
        assert cs.OVERALL_KEY.startswith("_")


# ---------------------------------------------------------------------------
# ops_health output-freshness registry
# ---------------------------------------------------------------------------

class TestOutputFreshness:
    def _client_with(self, rows, raise_exc=None):
        return _Supabase(
            {"calibration_adjustments": rows},
            raise_for={"calibration_adjustments": raise_exc} if raise_exc else None,
        )

    def test_fresh_output_ok(self):
        rows = [{"computed_at": _iso(datetime.now(timezone.utc) - timedelta(hours=20))}]
        out = ohs.get_output_freshness(self._client_with(rows))
        assert out[0].table == "calibration_adjustments"
        assert out[0].status == "ok"

    def test_stale_output_flagged(self):
        rows = [{"computed_at": _iso(datetime.now(timezone.utc) - timedelta(days=25))}]
        out = ohs.get_output_freshness(self._client_with(rows))
        assert out[0].status == "stale"
        assert out[0].age_hours > out[0].max_age_hours

    def test_empty_table_is_never(self):
        out = ohs.get_output_freshness(self._client_with([]))
        assert out[0].status == "never"

    def test_check_error_reported_not_ok(self):
        out = ohs.get_output_freshness(self._client_with([], raise_exc=RuntimeError("boom")))
        assert out[0].status == "error"

    def test_registry_contains_calibration(self):
        assert any(t == "calibration_adjustments" for t, _, _ in ohs.OUTPUT_FRESHNESS)
