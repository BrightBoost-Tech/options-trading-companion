"""Raw-mode blob-clear — closes #1076 (the 06-18-×1.5-still-served bug).

The live-only relearn (#1076) correctly went insufficient_data (5 live < 8), but
calibration_update wrote NO row on insufficient_data, so get_calibration_adjustments
kept serving the prior contaminated 06-18 ×1.5 blob (it serves the LATEST row).

Fix:
- compute distinguishes a fetch FAILURE (status=error) from a legit-empty/low
  result (status=insufficient_data): _fetch_outcomes returns None on query error.
- calibration_update WRITES an empty reset row on status=insufficient_data ONLY
  (never on error → last-good preserved). The empty row becomes the latest →
  served → apply_calibration = ×1.0.
"""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

for _m in ("alpaca", "alpaca.trading", "alpaca.trading.requests"):
    sys.modules.setdefault(_m, types.ModuleType(_m))

from packages.quantum.analytics import calibration_service as cs
from packages.quantum.jobs.handlers import calibration_update as cu


def _svc():
    s = cs.CalibrationService.__new__(cs.CalibrationService)
    s.client = MagicMock()
    return s


# ── compute: error (fetch failure) vs insufficient (legit empty/low) ──

class TestComputeErrorVsInsufficient(unittest.TestCase):
    def test_fetch_outcomes_returns_none_on_query_error(self):
        svc = _svc()
        svc.client.table.side_effect = RuntimeError("db down")
        assert svc._fetch_outcomes("u", 30) is None   # None, not [] — distinguishable

    def test_fetch_failure_none_yields_status_error(self):
        svc = _svc()
        svc._fetch_outcomes = lambda *a, **k: None
        res = svc.compute_calibration_adjustments("u")
        assert res["status"] == "error" and res["reason"] == "fetch_failed"

    def test_legit_empty_yields_insufficient(self):
        svc = _svc()
        svc._fetch_outcomes = lambda *a, **k: []
        res = svc.compute_calibration_adjustments("u")
        assert res["status"] == "insufficient_data" and res["sample_size"] == 0

    def test_below_min_yields_insufficient(self):
        svc = _svc()
        n = cs.MIN_CALIBRATION_TRADES - 1
        svc._fetch_outcomes = lambda *a, **k: [{} for _ in range(n)]
        res = svc.compute_calibration_adjustments("u")
        assert res["status"] == "insufficient_data" and res["sample_size"] == n


# ── read side: the LATEST empty row wins over a stale contaminated one ─

class TestReadLatestWinsOverStale(unittest.TestCase):
    def _serve(self, latest_row):
        sb = MagicMock()
        (sb.table.return_value.select.return_value.eq.return_value
         .order.return_value.limit.return_value.execute.return_value) = MagicMock(
            data=[latest_row]
        )
        return cs.get_calibration_adjustments("u", sb)

    def test_empty_latest_serves_raw_then_apply_is_identity(self):
        # The 06-18-×1.5 bug: an empty (raw) row written AFTER the contaminated
        # ×1.5 row is the LATEST → served → {} (not the stale ×1.5).
        adj = self._serve({"adjustments": {}, "computed_at": "2099-01-01T00:00:00+00:00"})
        assert adj == {}
        ev, pop = cs.apply_calibration(100.0, 0.6, "LONG_PUT_DEBIT_SPREAD", "normal", adj)
        assert ev == 100.0 and pop == 0.6        # ×1.0, the ×1.5 is gone

    def test_populated_latest_still_served(self):
        # Regression: a real (ok) blob still serves when it is the latest.
        adj = self._serve({
            "adjustments": {"S": {"normal": {"_all": {"ev_multiplier": 0.9}}}},
            "computed_at": "2099-01-01T00:00:00+00:00",
        })
        assert adj == {"S": {"normal": {"_all": {"ev_multiplier": 0.9}}}}


# ── write side: run() writes empty on insufficient, never on error ──

class _FakeChain:
    """Records inserts; returns empty data for selects so _last_write_age_days
    finds no prior row (age None → no staleness alert)."""
    def __init__(self, store):
        self.store = store
        self._pending = None
        self._table = None

    def table(self, name):
        self._table = name
        self._pending = None
        return self

    def insert(self, row):
        self._pending = row
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._pending is not None:
            self.store.append((self._table, dict(self._pending)))
            row, self._pending = self._pending, None
            return SimpleNamespace(data=[row])
        return SimpleNamespace(data=[])


class TestRunWriteSide(unittest.TestCase):
    def _run(self, status_result):
        store = []
        with patch("packages.quantum.jobs.handlers.calibration_update.get_admin_client",
                   return_value=_FakeChain(store)), \
             patch.object(cs.CalibrationService, "compute_calibration_adjustments",
                          return_value=status_result):
            cu.run({"user_id": "u1", "window_days": 30})
        return [r for (t, r) in store if t == "calibration_adjustments"]

    def test_insufficient_writes_empty_reset_row(self):
        ins = self._run({"status": "insufficient_data", "sample_size": 5})
        assert len(ins) == 1
        assert ins[0]["adjustments"] == {}
        assert ins[0]["total_outcomes"] == 5
        assert ins[0]["user_id"] == "u1"

    def test_error_does_not_clear_last_good_preserved(self):
        ins = self._run({"status": "error", "reason": "fetch_failed"})
        assert ins == []     # NO reset row — last-good blob left intact

    def test_ok_writes_the_real_blob_unchanged(self):
        blob = {"S": {"normal": {"_all": {"ev_multiplier": 0.9}}}}
        ins = self._run({"status": "ok", "adjustments": blob, "total_outcomes": 12})
        assert len(ins) == 1
        assert ins[0]["adjustments"] == blob
        assert ins[0]["total_outcomes"] == 12


if __name__ == "__main__":
    unittest.main()
