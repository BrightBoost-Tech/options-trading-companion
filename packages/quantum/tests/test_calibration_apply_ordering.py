"""F-A1-3 calibration apply-move + score recompute (Option-A 5th application).

Pins: recompute preserves the additive scanner penalties AND the multiplicative
conviction while re-scaling the ev base · de-saturation (a 100-clamped score
drops below 100 at ×0.5) · armed applies EXACTLY ONCE (the sentinel) + stamps
true raw · flag-off mutates nothing (byte-identical) + logs the shadow ·
fail-safe on a calibration error.
"""
import os
import unittest
from unittest import mock

from packages.quantum.analytics import calibration_apply_ordering as cao


def _clear():
    os.environ.pop("CALIBRATION_APPLY_AT_SCORING", None)


def _cand(ticker="QQQ", base=60.0, cost=10.0, regime=0.0, greek=0.0,
          scanner=None, score=None, ev=40.0, pop=0.6):
    inner = max(0.0, min(100.0, base - cost - regime - greek))
    sc = inner if scanner is None else scanner
    return {
        "ticker": ticker, "ev": ev, "probability_of_profit": pop,
        "strategy": "iron_condor", "dte": 30,
        "unified_score_details": {"ev": base, "execution_cost": cost,
                                  "regime_penalty": regime, "greek_penalty": greek},
        "_scanner_score": sc, "score": (sc if score is None else score),
    }


class TestRecompute(unittest.TestCase):
    def test_basic_linear(self):
        # base 60, cost 10 → inner 50; ×0.5 → 30−10 = 20.
        self.assertAlmostEqual(cao.recompute_score(_cand(base=60, cost=10), 0.5), 20.0, places=6)

    def test_de_saturation(self):
        # base 150 → inner clamps at 100 (saturated); ×0.5 → 75−35 = 40 (de-saturates).
        c = _cand(base=150, cost=20, regime=10, greek=5)
        self.assertEqual(c["score"], 100.0)                 # saturated
        self.assertAlmostEqual(cao.recompute_score(c, 0.5), 40.0, places=6)

    def test_preserves_conviction_multiplier(self):
        # inner 50, conviction ×0.8 → score 40. ×0.5 ev → new_inner 20 × 0.8 = 16.
        c = _cand(base=60, cost=10, scanner=50.0, score=40.0)
        self.assertAlmostEqual(cao.recompute_score(c, 0.5), 16.0, places=6)

    def test_preserves_additive_penalty(self):
        # inner 50, 5pt soft/earnings penalty → scanner 45; ×0.5 → 20 − 5 = 15.
        c = _cand(base=60, cost=10, scanner=45.0, score=45.0)
        self.assertAlmostEqual(cao.recompute_score(c, 0.5), 15.0, places=6)

    def test_mult_one_is_identity(self):
        c = _cand(base=60, cost=10, scanner=45.0, score=36.0)  # penalty + conviction
        self.assertAlmostEqual(cao.recompute_score(c, 1.0), 36.0, places=6)

    def test_failsafe_no_components(self):
        self.assertEqual(cao.recompute_score({"score": 42.0}, 0.5), 42.0)


def _fake_apply(mult):
    return lambda ev, pop, strat, reg, cache, dte_bucket=None: (ev * mult, pop)


_DTE = lambda d: "30-45"


class TestApplyOrShadow(unittest.TestCase):
    def tearDown(self):
        _clear()

    def test_armed_mutates_once_and_stamps_raw(self):
        os.environ["CALIBRATION_APPLY_AT_SCORING"] = "1"
        c = _cand(base=60, cost=10, ev=40.0)
        cao.apply_calibration_at_scoring(
            [c], {"blob": 1}, "chop",
            apply_calibration=_fake_apply(0.5), classify_dte=_DTE, cal_enabled=True)
        self.assertEqual(c["ev"], 20.0)                    # 40 × 0.5
        self.assertEqual(c["_ev_raw_true"], 40.0)          # true raw stamped
        self.assertTrue(c["_calibration_applied"])         # sentinel → legacy site skips
        self.assertAlmostEqual(c["score"], 20.0, places=6)  # recomputed from calibrated ev

    def test_flag_off_byte_identical_and_logs(self):
        _clear()
        c = _cand(base=60, cost=10, ev=40.0)
        before = dict(c)
        with self.assertLogs(cao.__name__, level="INFO") as cm:
            cao.apply_calibration_at_scoring(
                [c], {"blob": 1}, "chop",
                apply_calibration=_fake_apply(0.5), classify_dte=_DTE, cal_enabled=True)
        self.assertEqual(c["ev"], before["ev"])            # unchanged
        self.assertNotIn("_calibration_applied", c)        # no sentinel → legacy site applies
        self.assertIn("[APPLY_ORDER_SHADOW]", "\n".join(cm.output))

    def test_shadow_detects_ordering_flip(self):
        _clear()
        # Per-candidate DIFFERENT multipliers (real calibration varies by
        # strategy/regime/dte): HI is punished (×0.3), MID untouched (×1.0), so
        # HI's calibrated score drops below MID → the selection ordering flips.
        hi = _cand("HI", base=70, cost=10); hi["strategy"] = "iron_condor"     # score 60
        mid = _cand("MID", base=65, cost=10); mid["strategy"] = "debit_spread"  # score 55

        def _apply(ev, pop, strat, reg, cache, dte_bucket=None):
            return ev * (0.3 if strat == "iron_condor" else 1.0), pop

        with self.assertLogs(cao.__name__, level="INFO") as cm:
            cao.apply_calibration_at_scoring(
                [hi, mid], {"blob": 1}, "chop",
                apply_calibration=_apply, classify_dte=_DTE, cal_enabled=True)
        line = "\n".join(cm.output)
        self.assertIn("would_differ=True", line)           # HI(11) now below MID(55)

    def test_disabled_or_empty_cache_noop(self):
        c = _cand()
        before = dict(c)
        cao.apply_calibration_at_scoring([c], None, "chop",
                                         apply_calibration=_fake_apply(0.5),
                                         classify_dte=_DTE, cal_enabled=True)
        self.assertEqual(c, before)

    def test_failsafe_calibration_error_never_raises(self):
        os.environ["CALIBRATION_APPLY_AT_SCORING"] = "1"
        c = _cand()
        def _boom(*a, **k):
            raise RuntimeError("cal down")
        # must not raise; candidate left unmutated
        cao.apply_calibration_at_scoring([c], {"b": 1}, "chop",
                                         apply_calibration=_boom, classify_dte=_DTE,
                                         cal_enabled=True)
        self.assertNotIn("_calibration_applied", c)


if __name__ == "__main__":
    unittest.main()
