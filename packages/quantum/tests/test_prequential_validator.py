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
import unittest

from packages.quantum.analytics.calibration_service import CalibrationService
from packages.quantum.analytics import prequential_validator as pv


def _row(ev, pnl, pop=None, strat="S", regime="R", ticker="X"):
    return {"ev_predicted": ev, "pnl_realized": pnl, "pop_predicted": pop,
            "strategy": strat, "regime": regime, "ticker": ticker,
            "closed_at": "2026-07-01T00:00:00+00:00"}


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


if __name__ == "__main__":
    unittest.main()
