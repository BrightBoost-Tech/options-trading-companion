"""Unit tests for D2 Phase 1 momentum signals + candidate tempers (pure, log-only)."""

import unittest

from packages.quantum.services.momentum_signals import (
    compute_momentum_signals,
    evaluate_tempers,
    direction_from_strategy,
)


class TestDirectionFromStrategy(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(direction_from_strategy("LONG_CALL_DEBIT_SPREAD"), "bullish")
        self.assertEqual(direction_from_strategy("LONG_PUT_DEBIT_SPREAD"), "bearish")
        self.assertEqual(direction_from_strategy("SHORT_PUT_CREDIT_SPREAD"), "bullish")
        self.assertEqual(direction_from_strategy("SHORT_CALL_CREDIT_SPREAD"), "bearish")
        self.assertEqual(direction_from_strategy("IRON_CONDOR"), "neutral")


class TestComputeSignals(unittest.TestCase):
    def test_bullish_momentum_following_flag(self):
        # Strong recent up-move; a bullish trade is momentum-FOLLOWING.
        closes = [10.0 + 0.1 * i for i in range(60)]  # steady uptrend, current 15.9
        sig = compute_momentum_signals(closes, "bullish")
        self.assertGreater(sig["run_up_20d"], 0)
        self.assertGreater(sig["dist_from_sma20"], 0)
        self.assertGreater(sig["signed_run_up_in_direction"], 0)
        self.assertTrue(sig["momentum_following"])

    def test_bearish_against_uptrend_not_following(self):
        # Same uptrend, but a BEARISH trade is going AGAINST the move.
        closes = [10.0 + 0.1 * i for i in range(60)]
        sig = compute_momentum_signals(closes, "bearish")
        self.assertLess(sig["signed_run_up_in_direction"], 0)
        self.assertFalse(sig["momentum_following"])

    def test_bearish_momentum_following_on_downtrend(self):
        closes = [20.0 - 0.1 * i for i in range(60)]  # downtrend
        sig = compute_momentum_signals(closes, "bearish")
        self.assertGreater(sig["signed_run_up_in_direction"], 0)  # moved our (down) way
        self.assertTrue(sig["momentum_following"])

    def test_rsi_present_for_sufficient_history(self):
        closes = [10 + (i % 5) * 0.2 for i in range(40)]  # has up & down days
        sig = compute_momentum_signals(closes, "bullish")
        self.assertIsNotNone(sig["rsi"])
        self.assertGreaterEqual(sig["rsi"], 0.0)
        self.assertLessEqual(sig["rsi"], 100.0)

    def test_short_history_fields_none(self):
        sig = compute_momentum_signals([10.0, 10.5, 11.0], "bullish")
        self.assertIsNone(sig["run_up_20d"])
        self.assertIsNone(sig["dist_from_sma50"])
        self.assertEqual(sig["bars_available"], 3)


class TestTempers(unittest.TestCase):
    def _signals(self, **kw):
        base = {
            "direction": "bullish", "signed_run_up_in_direction": None,
            "dist_from_sma20": None, "rsi": None,
        }
        base.update(kw)
        return base

    def test_T1_runup_discount(self):
        sig = self._signals(signed_run_up_in_direction=0.20)  # +20% in direction
        t = evaluate_tempers(ev=100.0, score=80.0, signals=sig)
        # haircut = min(0.20*0.5, 0.30) = 0.10 → would_be_ev 90
        self.assertAlmostEqual(t["T1"]["haircut"], 0.10, places=4)
        self.assertAlmostEqual(t["T1"]["would_be_ev"], 90.0, places=2)
        self.assertAlmostEqual(t["T1"]["would_be_score"], 72.0, places=2)

    def test_T2_extension_discount(self):
        sig = self._signals(dist_from_sma20=0.10)  # +10% above SMA20, bullish
        t = evaluate_tempers(ev=100.0, score=None, signals=sig)
        self.assertAlmostEqual(t["T2"]["haircut"], 0.08, places=4)  # 0.10*0.8
        self.assertAlmostEqual(t["T2"]["would_be_ev"], 92.0, places=2)

    def test_T3_rsi_overbought_bullish(self):
        sig = self._signals(rsi=75.0)
        t = evaluate_tempers(ev=100.0, score=None, signals=sig)
        self.assertAlmostEqual(t["T3"]["haircut"], 0.20, places=4)
        self.assertAlmostEqual(t["T3"]["would_be_ev"], 80.0, places=2)

    def test_T3_not_extended_no_discount(self):
        sig = self._signals(rsi=55.0)
        t = evaluate_tempers(ev=100.0, score=None, signals=sig)
        self.assertEqual(t["T3"]["haircut"], 0.0)
        self.assertAlmostEqual(t["T3"]["would_be_ev"], 100.0, places=2)

    def test_tempers_only_discount_never_boost(self):
        # Adverse move (run-up against us) must NOT boost EV.
        sig = self._signals(signed_run_up_in_direction=-0.30)
        t = evaluate_tempers(ev=100.0, score=None, signals=sig)
        self.assertEqual(t["T1"]["haircut"], 0.0)
        self.assertAlmostEqual(t["T1"]["would_be_ev"], 100.0, places=2)

    def test_real_ev_inputs_not_mutated(self):
        # evaluate_tempers takes scalars; the would_be values are separate.
        ev_in = 100.0
        sig = self._signals(signed_run_up_in_direction=0.20)
        t = evaluate_tempers(ev=ev_in, score=80.0, signals=sig)
        self.assertEqual(ev_in, 100.0)  # input untouched
        self.assertNotEqual(t["T1"]["would_be_ev"], ev_in)  # temper is a separate value


if __name__ == "__main__":
    unittest.main()
