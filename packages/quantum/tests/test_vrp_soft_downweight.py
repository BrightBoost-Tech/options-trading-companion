"""Tests for Cluster 2 — VRP-aware soft down-weight on the debit path.

Asserts:
  * pure multiplier shape: cheap IV (spread<0) -> >1.0, fair (0) -> 1.0,
    rich IV (spread>0) -> <1.0; monotonic; bounded [VRP_FLOOR, VRP_CEIL];
    None -> 1.0 no-op.
  * rich IV reduces the DEBIT score vs a fair reading (REQUIRED).
  * missing iv_rv_spread is a 1.0 no-op (REQUIRED).
  * credit / short-premium scoring is untouched (multiplier == 1.0).

Same sys.modules pollution guard as the #115 / anti-pattern suites
(test_weekly_report_win_rate.py poisons opportunity_scorer at import).
"""

import importlib
import sys
import unittest

for _modname in ("packages.quantum.analytics.opportunity_scorer",):
    sys.modules.pop(_modname, None)

_os_mod = importlib.import_module("packages.quantum.analytics.opportunity_scorer")
OpportunityScorer = _os_mod.OpportunityScorer
vrp_score_multiplier = _os_mod.vrp_score_multiplier
VRP_FLOOR = _os_mod.VRP_FLOOR
VRP_CEIL = _os_mod.VRP_CEIL

assert callable(OpportunityScorer), "opportunity_scorer mocked at file-load"
assert callable(vrp_score_multiplier), "vrp_score_multiplier missing"


def _debit_candidate():
    # long_call → debit / long premium (no 'credit' key, no 'credit' in type)
    return {
        "symbol": "AAPL",
        "type": "debit_spread",
        "short_strike": 105.0,
        "long_strike": 100.0,
        "debit": 1.5,
        "dte": 30,
    }


def _credit_candidate():
    return {
        "symbol": "AAPL",
        "type": "credit_spread",
        "short_strike": 100.0,
        "long_strike": 105.0,
        "credit": 1.0,
        "dte": 30,
    }


def _ctx(iv_rv_spread="__absent__", iv_rank=40.0):
    ctx = {"price": 103.0, "iv_rank": iv_rank, "bid": 1.4, "ask": 1.6}
    if iv_rv_spread != "__absent__":
        ctx["iv_rv_spread"] = iv_rv_spread
    return ctx


class TestPureMultiplier(unittest.TestCase):
    def test_fair_spread_is_unity(self):
        self.assertAlmostEqual(vrp_score_multiplier(0.0), 1.0, places=9)

    def test_none_is_noop(self):
        self.assertEqual(vrp_score_multiplier(None), 1.0)

    def test_rich_below_one_cheap_above_one(self):
        self.assertLess(vrp_score_multiplier(0.10), 1.0)
        self.assertGreater(vrp_score_multiplier(-0.10), 1.0)

    def test_monotonic_decreasing_in_richness(self):
        a = vrp_score_multiplier(0.02)
        b = vrp_score_multiplier(0.08)
        c = vrp_score_multiplier(0.20)
        self.assertGreater(a, b)
        self.assertGreater(b, c)

    def test_bounds_respected(self):
        for s in (-10.0, -0.5, -0.05, 0.0, 0.05, 0.5, 10.0):
            m = vrp_score_multiplier(s)
            self.assertGreaterEqual(m, VRP_FLOOR)
            self.assertLessEqual(m, VRP_CEIL)

    def test_extremes_saturate_at_bounds(self):
        self.assertAlmostEqual(vrp_score_multiplier(100.0), VRP_FLOOR, places=6)
        self.assertAlmostEqual(vrp_score_multiplier(-100.0), VRP_CEIL, places=6)

    def test_continuous_through_origin(self):
        # No step/cliff: tiny +/- spreads stay close to 1.0 and to each other.
        eps = 1e-6
        self.assertAlmostEqual(vrp_score_multiplier(eps), 1.0, places=4)
        self.assertAlmostEqual(vrp_score_multiplier(-eps), 1.0, places=4)


class TestDebitScoreEffect(unittest.TestCase):
    def test_rich_iv_reduces_debit_score(self):
        fair = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=0.0))
        rich = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=0.15))
        self.assertLess(rich["score"], fair["score"])
        self.assertLess(rich["debug"]["vrp_multiplier"], 1.0)
        self.assertAlmostEqual(fair["debug"]["vrp_multiplier"], 1.0, places=6)

    def test_cheap_iv_boosts_debit_score(self):
        fair = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=0.0))
        cheap = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=-0.10))
        self.assertGreaterEqual(cheap["score"], fair["score"])
        self.assertGreater(cheap["debug"]["vrp_multiplier"], 1.0)

    def test_observability_fields_present_and_consistent(self):
        r = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=0.12))
        d = r["debug"]
        for k in ("iv_rv_spread", "vrp_multiplier", "pre_vrp_score", "post_vrp_score"):
            self.assertIn(k, d)
        # post ≈ pre * multiplier (tolerance covers the independent rounding
        # of each debug field vs the unrounded internal computation).
        self.assertAlmostEqual(
            d["post_vrp_score"],
            d["pre_vrp_score"] * d["vrp_multiplier"],
            delta=0.2,
        )
        self.assertLess(d["post_vrp_score"], d["pre_vrp_score"])  # rich → reduced


class TestMissingDataNoOp(unittest.TestCase):
    def test_missing_spread_is_unity_and_score_unchanged(self):
        missing = OpportunityScorer.score(_debit_candidate(), _ctx())  # no iv_rv_spread
        fair = OpportunityScorer.score(_debit_candidate(), _ctx(iv_rv_spread=0.0))
        self.assertEqual(missing["debug"]["vrp_multiplier"], 1.0)
        self.assertIsNone(missing["debug"]["iv_rv_spread"])
        self.assertEqual(missing["score"], fair["score"])


class TestCreditUntouched(unittest.TestCase):
    def test_credit_multiplier_is_unity_even_when_rich(self):
        rich = OpportunityScorer.score(
            _credit_candidate(), _ctx(iv_rv_spread=0.20, iv_rank=80.0)
        )
        self.assertEqual(rich["debug"]["vrp_multiplier"], 1.0)

    def test_credit_score_invariant_to_spread(self):
        a = OpportunityScorer.score(
            _credit_candidate(), _ctx(iv_rv_spread=0.0, iv_rank=80.0)
        )
        b = OpportunityScorer.score(
            _credit_candidate(), _ctx(iv_rv_spread=0.25, iv_rank=80.0)
        )
        self.assertEqual(a["score"], b["score"])


if __name__ == "__main__":
    unittest.main()
