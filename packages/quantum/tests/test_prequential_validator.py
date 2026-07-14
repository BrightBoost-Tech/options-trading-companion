"""Prequential calibration validator + the fit-extraction it rests on.

Pins:
- build_adjustments_from_outcomes is a PURE fit (list → blob), delegated to by
  compute_calibration_adjustments (byte-identical for the production default) —
  the non-circular #1167 substrate.
- THE FALSIFIER has the right sign: a prefix that systematically over-predicts →
  calibration deflates → out-of-sample RMSE drops → CALIBRATION_HELPS; a set
  where the fit misleads the target → RMSE rises → FALSIFIED; a fit that never
  fires → INCONCLUSIVE (raw == calibrated, nothing tested).
- prefix-invariance: the fit is a function of the SET, not the order.
- zero-row / too-short guard never raises.
"""
import os
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.analytics.calibration_service import (
    CalibrationService,
    CORRUPTED_PNL_FLOOR,
    CALIBRATION_EV_EPOCH,
)
from packages.quantum.analytics import prequential_validator as pv


def _row(ev, pnl, pop=None, strat="S", regime="R", ticker="X",
         closed_at="2026-07-01T00:00:00+00:00"):
    return {"ev_predicted": ev, "pnl_realized": pnl, "pop_predicted": pop,
            "strategy": strat, "regime": regime, "ticker": ticker,
            "closed_at": closed_at}


class _RecordingClient:
    """Supabase-style fluent client that RECORDS the filter chain and returns
    configured rows — or raises at .execute() (the DB-origin failure injection
    point for F-A3-4 D1). No .order() is expected: the shared contract sorts in
    Python, so leaving order() unrecorded proves the sort is code-side."""

    def __init__(self, rows=None, raise_on_execute=False):
        self._rows = [] if rows is None else rows
        self._raise = raise_on_execute
        self.eq_calls = []
        self.gte_calls = []

    def table(self, *a, **k):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.eq_calls.append((col, val))
        return self

    def gte(self, col, val):
        self.gte_calls.append((col, val))
        return self

    def execute(self):
        if self._raise:
            raise RuntimeError("injected DB execute failure (origin)")
        return SimpleNamespace(data=list(self._rows))


class TestFitExtraction(unittest.TestCase):
    def setUp(self):
        self.svc = CalibrationService(None)  # build_* uses no client

    def test_pure_fit_deflates_on_overprediction(self):
        # 8 rows: predicted 100, realized 50 → overall ev_mult = 50/100 = 0.5.
        out = self.svc.build_adjustments_from_outcomes([_row(100, 50) for _ in range(8)])
        self.assertEqual(out["status"], "ok")
        self.assertAlmostEqual(out["adjustments"]["_overall"]["ev_multiplier"], 0.5, places=3)

    def test_insufficient_data_below_min(self):
        out = self.svc.build_adjustments_from_outcomes([_row(100, 50) for _ in range(3)],
                                                       min_trades=8)
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["minimum_required"], 8)

    def test_compute_delegates_to_pure_fit(self):
        fixture = [_row(100, 50) for _ in range(8)]
        self.svc._fetch_outcomes = lambda uid, wd: fixture  # type: ignore
        got = self.svc.compute_calibration_adjustments("u", window_days=30)
        want = self.svc.build_adjustments_from_outcomes(fixture)
        # computed_at differs by timestamp; the substance must match.
        self.assertEqual(got["status"], want["status"])
        self.assertEqual(got["adjustments"], want["adjustments"])
        self.assertEqual(got["total_outcomes"], want["total_outcomes"])

    def test_compute_fetch_failure_is_error_not_delegated(self):
        self.svc._fetch_outcomes = lambda uid, wd: None  # type: ignore
        got = self.svc.compute_calibration_adjustments("u")
        self.assertEqual(got["status"], "error")


class TestFalsifier(unittest.TestCase):
    def test_helps_when_prefix_predicts_target_bias(self):
        # Every close over-predicts 2×; calibration learns ×0.5 and nails targets.
        rows = [_row(100, 50, pop=0.9) for _ in range(8)]
        rep = pv.run_prequential_validation(rows, warmup=4, min_trades=4)
        self.assertEqual(rep["status"], "ok")
        self.assertGreater(rep["n_calibration_fired"], 0)
        self.assertEqual(rep["falsifier"]["verdict"], "CALIBRATION_HELPS")
        self.assertGreater(rep["ev_rmse"]["improvement"], 0)
        self.assertTrue(rep["prefix_invariant"])
        # PoP over-confidence (0.9 vs 100% wins) also corrects toward 1.0.
        self.assertGreaterEqual(rep["brier"]["improvement"], 0)

    def test_falsified_when_fit_misleads_target(self):
        # Prefix over-predicts (100/50 → learns ×0.5) but targets are already
        # well-calibrated (50/50) → deflating them INJECTS error.
        rows = [_row(100, 50) for _ in range(4)] + [_row(50, 50) for _ in range(4)]
        rep = pv.run_prequential_validation(rows, warmup=4, min_trades=4)
        self.assertEqual(rep["falsifier"]["verdict"], "FALSIFIED_CALIBRATION_DOES_NOT_HELP")
        self.assertLess(rep["ev_rmse"]["improvement"], 0)
        self.assertGreater(rep["n_calibration_fired"], 0)

    def test_inconclusive_when_calibration_never_fires(self):
        # min_trades never satisfied by any prefix → adj empty → raw == calibrated.
        rows = [_row(100, 50) for _ in range(8)]
        rep = pv.run_prequential_validation(rows, warmup=4, min_trades=100)
        self.assertEqual(rep["falsifier"]["verdict"], "INCONCLUSIVE_CALIBRATION_NEVER_FIRED")
        self.assertEqual(rep["n_calibration_fired"], 0)
        self.assertAlmostEqual(rep["ev_rmse"]["improvement"], 0.0, places=9)


class TestGuardsAndInvariance(unittest.TestCase):
    def test_zero_row_guard(self):
        rep = pv.run_prequential_validation([], warmup=4)
        self.assertEqual(rep["status"], "insufficient_data")
        self.assertEqual(rep["n_outcomes"], 0)

    def test_too_short_guard(self):
        rep = pv.run_prequential_validation([_row(1, 1) for _ in range(4)], warmup=4)
        self.assertEqual(rep["status"], "insufficient_data")  # n == warmup, nothing to score

    def test_fit_order_invariant(self):
        svc = CalibrationService(None)
        prefix = [_row(100, 50), _row(80, 90), _row(120, 40), _row(60, 70),
                  _row(100, 55), _row(90, 60)]
        self.assertTrue(pv._fit_is_order_invariant(prefix, svc, min_trades=4))


class TestFetchParity(unittest.TestCase):
    """F-A3-4 D1: the validator fetches the EXACT eligible rows production
    calibration does — via the SHARED CalibrationService.fetch_eligible_outcomes
    contract, not a second copied is_paper/epoch/floor predicate."""

    def _clean_env(self):
        # Ensure CALIBRATION_TRAIN_LIVE_ONLY is unset → ON (default), so the
        # live-only predicate is exercised deterministically.
        env = dict(os.environ)
        env.pop("CALIBRATION_TRAIN_LIVE_ONLY", None)
        return patch.dict(os.environ, env, clear=True)

    def test_validator_and_production_share_the_same_chain(self):
        # Same rows, same window → identical filter chain from BOTH entrypoints.
        with self._clean_env():
            c_val = _RecordingClient(rows=[_row(1, 1)])
            pv.fetch_live_outcomes(c_val, "u", window_days=120)

            c_prod = _RecordingClient(rows=[_row(1, 1)])
            CalibrationService(c_prod)._fetch_outcomes("u", 120)

        self.assertEqual(c_val.eq_calls, c_prod.eq_calls)
        self.assertEqual(c_val.gte_calls, c_prod.gte_calls)

    def test_live_only_predicate_and_date_floor(self):
        with self._clean_env():
            client = _RecordingClient(rows=[_row(1, 1)])
            pv.fetch_live_outcomes(client, "u", window_days=120)

        # live-only predicate (is_paper=false — execution-derived provenance).
        self.assertIn(("is_paper", False), client.eq_calls)
        self.assertIn(("user_id", "u"), client.eq_calls)
        # date floor: with a 120-day window today, the EV epoch is the binding
        # floor (max of now-120d, corrupted floor, epoch).
        self.assertEqual(len(client.gte_calls), 1)
        col, cutoff = client.gte_calls[0]
        self.assertEqual(col, "closed_at")
        self.assertEqual(cutoff, max(CORRUPTED_PNL_FLOOR, CALIBRATION_EV_EPOCH))

    def test_live_only_off_reverts_to_is_paper_blind_in_both(self):
        with patch.dict(os.environ, {"CALIBRATION_TRAIN_LIVE_ONLY": "0"}, clear=False):
            c_val = _RecordingClient(rows=[_row(1, 1)])
            pv.fetch_live_outcomes(c_val, "u", window_days=30)
        # Explicit falsy → NO is_paper filter (parity with production's flag).
        self.assertNotIn(("is_paper", False), c_val.eq_calls)
        self.assertIn(("user_id", "u"), c_val.eq_calls)

    def test_three_era_population_sorted_asc_and_floored(self):
        # A population spanning three eras: pre-live paper, broker-live,
        # current post-epoch. The shared fetch returns them closed_at ASC (the
        # prequential prefix requirement) and applies the epoch floor at the DB.
        rows = [
            _row(10, 5, closed_at="2026-07-10T00:00:00+00:00"),  # current post-epoch
            _row(10, 5, closed_at="2026-03-01T00:00:00+00:00"),  # pre-live paper era
            _row(10, 5, closed_at="2026-06-15T00:00:00+00:00"),  # broker-live era
        ]
        with self._clean_env():
            client = _RecordingClient(rows=rows)
            out = pv.fetch_live_outcomes(client, "u", window_days=365)

        got = [r["closed_at"] for r in out]
        self.assertEqual(got, sorted(got))                       # ASC
        self.assertEqual(got[0], "2026-03-01T00:00:00+00:00")
        # DB-side floor that would exclude pre-epoch rows: gte cutoff == epoch
        # (365-day window reaches older than the epoch, so the epoch binds).
        _, cutoff = client.gte_calls[0]
        self.assertEqual(cutoff, CALIBRATION_EV_EPOCH)
        self.assertIn(("is_paper", False), client.eq_calls)


class TestFetchFailureVsEmpty(unittest.TestCase):
    """F-A3-4 D1: a query FAILURE is typed error/fetch_failed; a legitimate
    empty cohort is insufficient_data. Failure must NEVER read as green vacuum."""

    def test_origin_injected_fetch_failure_surfaces_error(self):
        client = _RecordingClient(raise_on_execute=True)
        # The DB origin (.execute) raises → fetch returns the None sentinel.
        self.assertIsNone(pv.fetch_live_outcomes(client, "u"))
        # The PUBLIC validator result is typed error, never insufficient_data.
        rep = pv.run_live_prequential(client, "u", warmup=4)
        self.assertEqual(rep["status"], "error")
        self.assertEqual(rep["reason"], "fetch_failed")
        self.assertNotIn("falsifier", rep)  # no green verdict on a failed fetch

    def test_legitimate_empty_cohort_is_insufficient_not_error(self):
        client = _RecordingClient(rows=[])
        self.assertEqual(pv.fetch_live_outcomes(client, "u"), [])  # success, 0 rows
        rep = pv.run_live_prequential(client, "u", warmup=4)
        self.assertEqual(rep["status"], "insufficient_data")
        self.assertEqual(rep["n_outcomes"], 0)
        self.assertNotEqual(rep["status"], "error")


if __name__ == "__main__":
    unittest.main()
