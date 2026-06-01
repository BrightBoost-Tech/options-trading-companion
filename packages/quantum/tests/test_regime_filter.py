"""D4 regime_filter — OBSERVATION-ONLY cross-asset regime signal.

Load-bearing: with the flag ON, the LIVE regime engine's output is IDENTICAL to
flag-OFF (the signal logs but changes nothing live). Plus: it computes from the
TLT/HYG proxies with VIX excluded (Step-0 gate); assumptions are flagged, not
hard-asserted; the observation row records would-be vs live.
"""

import os
import unittest
from unittest import mock

from packages.quantum.analytics import regime_filter as rf


def _bars(closes):
    return [{"close": c} for c in closes]


def _flat(n=60, v=100.0):
    return _bars([v] * n)


def _falling(n=60, start=100.0, drop_per=0.5):
    return _bars([start - drop_per * i for i in range(n)])


class TestComputeRegimeFilter(unittest.TestCase):
    def test_applicable_with_tlt_hyg_vix_excluded(self):
        out = rf.compute_regime_filter({"TLT": _flat(), "HYG": _flat()})
        self.assertTrue(out["applicable"])
        self.assertEqual(out["vix_status"], "absent_not_live")  # Step-0 gate
        self.assertIn(out["regime_filter_state"], {"SUPPRESSED", "NORMAL", "ELEVATED", "SHOCK"})
        self.assertTrue(0.5 <= out["would_be_scaler"] <= 1.2)
        self.assertIn("assumptions", out)  # guessed magnitudes surfaced for calibration

    def test_na_on_insufficient_bars(self):
        out = rf.compute_regime_filter({"TLT": _flat(5), "HYG": _flat(5)})
        self.assertFalse(out["applicable"])
        self.assertEqual(out["vix_status"], "absent_not_live")

    def test_credit_stress_raises_risk_directionally(self):
        # HYG falling (credit stress) must produce a HIGHER cross-asset risk
        # score than HYG flat — directional sanity (magnitudes are flagged
        # assumptions, not asserted).
        flat = rf.compute_regime_filter({"TLT": _flat(), "HYG": _flat()})
        stressed = rf.compute_regime_filter({"TLT": _flat(), "HYG": _falling()})
        self.assertGreater(stressed["cross_asset_risk_score"], flat["cross_asset_risk_score"])

    def test_vix_dimension_absent_not_stale(self):
        out = rf.compute_regime_filter({"TLT": _flat(), "HYG": _flat()})
        # rates+credit only; no vix_read field used from a stale source
        self.assertNotIn("vix_read", out)
        self.assertEqual(out["assumptions"]["vix"].split()[0], "EXCLUDED_not_live")


class TestObserveWritesComparison(unittest.TestCase):
    def test_observe_records_would_be_and_live(self):
        rows = []
        supa = mock.MagicMock()
        supa.table.return_value.insert.side_effect = lambda r: rows.append(r) or mock.MagicMock()
        out = rf.observe_regime_filter(
            supa, {"TLT": _flat(), "HYG": _falling()},
            live_state="NORMAL", live_risk_score=45.0, live_scaler=1.0, as_of_ts="2026-06-01T15:00:00")
        self.assertIsNotNone(out)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # both would-be and live actual are recorded + the divergence flag
        self.assertIn("rf_state", row)
        self.assertEqual(row["live_state"], "NORMAL")
        self.assertEqual(row["live_scaler"], 1.0)
        self.assertIn("diverged", row)
        self.assertEqual(row["vix_status"], "absent_not_live")

    def test_observe_fail_soft_on_write_error(self):
        supa = mock.MagicMock()
        supa.table.return_value.insert.return_value.execute.side_effect = Exception("db down")
        # must not raise (logging never breaks the live cycle)
        out = rf.observe_regime_filter(
            supa, {"TLT": _flat(), "HYG": _flat()},
            live_state="NORMAL", live_risk_score=50.0, live_scaler=1.0, as_of_ts="t")
        self.assertIsNone(out)


class TestObservationOnlyByteIdentical(unittest.TestCase):
    """LOAD-BEARING: the live regime engine's snapshot is identical whether the
    observe flag is ON or OFF — the signal records but never alters a live
    decision."""

    @staticmethod
    def _real_engine_cls():
        # Load the REAL RegimeEngineV3 from file — another test
        # (test_weekly_report_win_rate) replaces the module with a MagicMock in
        # sys.modules for the whole session, so a plain import is polluted
        # in-suite. Loading from the file path bypasses that and keeps the
        # runtime byte-identical proof intact.
        import importlib.util as _ilu
        from pathlib import Path as _Path
        p = _Path(__file__).resolve().parent.parent / "analytics" / "regime_engine_v3.py"
        spec = _ilu.spec_from_file_location("_regime_engine_v3_real_test", p)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.RegimeEngineV3

    def _engine(self, obs_rows):
        RegimeEngineV3 = self._real_engine_cls()
        eng = RegimeEngineV3.__new__(RegimeEngineV3)
        # uniform basket bars (enough for SMA50/RV) + quotes for liquidity
        md = mock.MagicMock()
        md.daily_bars.side_effect = lambda sym, start, end: _bars([100.0 + (i % 3) for i in range(60)])
        md.snapshot_many.return_value = {
            s: {"quote": {"bid": 99.99, "ask": 100.01, "mid": 100.0}} for s in eng.BASKET}
        eng.market_data = md
        supa = mock.MagicMock()
        supa.table.return_value.insert.side_effect = lambda r: obs_rows.append(r) or mock.MagicMock()
        eng.supabase = supa
        return eng

    def _snapshot(self, flag_value, obs_rows):
        from datetime import datetime
        eng = self._engine(obs_rows)
        with mock.patch.dict(os.environ, {rf.FLAG_ENV: flag_value}, clear=False):
            return eng.compute_global_snapshot(datetime(2026, 6, 1, 15, 0, 0))

    def test_snapshot_identical_flag_on_vs_off(self):
        off_rows, on_rows = [], []
        snap_off = self._snapshot("0", off_rows)
        snap_on = self._snapshot("1", on_rows)
        # the live decision surfaces are byte-identical
        self.assertEqual(snap_off.state, snap_on.state)
        self.assertEqual(snap_off.risk_scaler, snap_on.risk_scaler)
        self.assertEqual(snap_off.risk_score, snap_on.risk_score)
        self.assertEqual(snap_off.features, snap_on.features)
        # flag OFF logged nothing; flag ON logged exactly one observation row
        self.assertEqual(len(off_rows), 0)
        self.assertEqual(len(on_rows), 1)


class TestFlagDefaultOff(unittest.TestCase):
    def test_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(rf.is_observe_enabled())


if __name__ == "__main__":
    unittest.main()
