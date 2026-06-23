"""Cluster 3 — VRP soft down-weight WIRED into the live ranking path
(canonical_ranker.compute_risk_adjusted_ev), gated by VRP_LIVE_ENABLED.

Verifies (matching the remediation spec V1-V5):
  V1  flag OFF  -> ranking byte-identical to baseline (no always-on path).
  V2  flag ON   -> a rich-IV debit candidate ranks BELOW an otherwise-equal
                   fair-IV debit candidate (ordering changes, not just scores).
  V3  no double-application: the multiplier hits a candidate exactly once.
  V4  credit candidates and missing-data candidates are unchanged in BOTH
      flag states.

The multiplier itself (Cluster 2) is reused, not redefined.
"""

import copy
import os
import unittest

from packages.quantum.analytics.canonical_ranker import (
    compute_risk_adjusted_ev,
    rank_suggestions_canonical,
)


def _suggestion(ticker="AAA", iv_rv_spread="__absent__", premium_direction="debit", ev=120.0):
    s = {
        "ticker": ticker,
        "ev": ev,
        "sizing_metadata": {"contracts": 1, "max_loss_total": 200.0},
    }
    if premium_direction is not None:
        s["premium_direction"] = premium_direction
    if iv_rv_spread != "__absent__":
        s["iv_rv_spread"] = iv_rv_spread
    return s


class _FlagCtx:
    """Set/clear VRP_LIVE_ENABLED around a block."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._prior = os.environ.pop("VRP_LIVE_ENABLED", None)
        if self.value is not None:
            os.environ["VRP_LIVE_ENABLED"] = self.value
        return self

    def __exit__(self, *a):
        os.environ.pop("VRP_LIVE_ENABLED", None)
        if self._prior is not None:
            os.environ["VRP_LIVE_ENABLED"] = self._prior


class TestFlagDefaultsOff(unittest.TestCase):
    def test_default_is_off(self):
        os.environ.pop("VRP_LIVE_ENABLED", None)
        # rich-IV debit must be UNCHANGED when the flag is unset (default OFF)
        s = _suggestion(iv_rv_spread=0.20)
        baseline = compute_risk_adjusted_ev(_suggestion(iv_rv_spread=0.20), [], 2000.0)
        got = compute_risk_adjusted_ev(s, [], 2000.0)
        self.assertEqual(got, baseline)
        self.assertNotIn("vrp_ranking", s)


class TestV1FlagOffByteIdentical(unittest.TestCase):
    def test_flag_off_matches_no_vrp_baseline(self):
        # Baseline = a candidate with NO vrp inputs at all.
        baseline = compute_risk_adjusted_ev(
            _suggestion(iv_rv_spread="__absent__", premium_direction=None), [], 2000.0
        )
        with _FlagCtx("0"):
            rich = _suggestion(iv_rv_spread=0.20)
            got = compute_risk_adjusted_ev(rich, [], 2000.0)
        self.assertEqual(got, baseline)
        self.assertNotIn("vrp_ranking", rich)


class TestV2FlagOnReordersRichBelowFair(unittest.TestCase):
    def test_rich_iv_debit_ranks_below_fair_iv_debit(self):
        fair = _suggestion(ticker="FAIR", iv_rv_spread=0.0)
        rich = _suggestion(ticker="RICH", iv_rv_spread=0.15)
        with _FlagCtx("1"):
            ranked = rank_suggestions_canonical([rich, fair], [], 2000.0)
        # otherwise-equal: fair (mult 1.0) must now outrank rich (mult < 1.0)
        self.assertEqual([s["ticker"] for s in ranked], ["FAIR", "RICH"])
        self.assertLess(
            rich["risk_adjusted_ev"], fair["risk_adjusted_ev"]
        )

    def test_cheap_iv_does_not_drop_below_fair(self):
        fair = _suggestion(ticker="FAIR", iv_rv_spread=0.0)
        cheap = _suggestion(ticker="CHEAP", iv_rv_spread=-0.10)
        with _FlagCtx("1"):
            ranked = rank_suggestions_canonical([fair, cheap], [], 2000.0)
        # cheap (mult >= 1.0) ranks at or above fair
        self.assertEqual(ranked[0]["ticker"], "CHEAP")

    def test_observability_stamped(self):
        rich = _suggestion(iv_rv_spread=0.15)
        with _FlagCtx("1"):
            compute_risk_adjusted_ev(rich, [], 2000.0)
        v = rich["vrp_ranking"]
        for k in ("iv_rv_spread", "vrp_multiplier", "pre_vrp_rank", "post_vrp_rank"):
            self.assertIn(k, v)
        self.assertLess(v["vrp_multiplier"], 1.0)
        self.assertLess(v["post_vrp_rank"], v["pre_vrp_rank"])


class TestV3NoDoubleApplication(unittest.TestCase):
    def test_single_application_is_idempotent_per_call(self):
        with _FlagCtx("1"):
            s1 = _suggestion(iv_rv_spread=0.15)
            once = compute_risk_adjusted_ev(s1, [], 2000.0)
            # Re-running on a FRESH equal suggestion yields the same value —
            # the multiplier is computed from raw inputs each call, never
            # compounded onto an already-multiplied value.
            s2 = _suggestion(iv_rv_spread=0.15)
            again = compute_risk_adjusted_ev(s2, [], 2000.0)
        self.assertEqual(once, again)
        # post == pre * multiplier exactly once
        v = s1["vrp_ranking"]
        # tolerance covers the independent rounding of each stored field
        self.assertAlmostEqual(
            v["post_vrp_rank"], v["pre_vrp_rank"] * v["vrp_multiplier"], delta=1e-3
        )


class TestV4CreditAndMissingUnchanged(unittest.TestCase):
    def test_credit_untouched_both_flag_states(self):
        for flag in ("0", "1"):
            base = compute_risk_adjusted_ev(
                _suggestion(premium_direction="credit", iv_rv_spread="__absent__"), [], 2000.0
            )
            with _FlagCtx(flag):
                credit_rich = _suggestion(premium_direction="credit", iv_rv_spread=0.20)
                got = compute_risk_adjusted_ev(credit_rich, [], 2000.0)
            self.assertEqual(got, base, f"credit changed under flag={flag}")
            self.assertNotIn("vrp_ranking", credit_rich)

    def test_missing_spread_is_noop_both_flag_states(self):
        base = compute_risk_adjusted_ev(
            _suggestion(premium_direction="debit", iv_rv_spread="__absent__"), [], 2000.0
        )
        for flag in ("0", "1"):
            with _FlagCtx(flag):
                missing = _suggestion(premium_direction="debit", iv_rv_spread="__absent__")
                got = compute_risk_adjusted_ev(missing, [], 2000.0)
            self.assertEqual(got, base, f"missing-data penalized under flag={flag}")
            self.assertNotIn("vrp_ranking", missing)


class TestInternalCandFallback(unittest.TestCase):
    def test_reads_vrp_inputs_from_internal_cand(self):
        # In-memory midday path: top-level fields absent, internal_cand carries them.
        s = {
            "ticker": "AAA",
            "ev": 120.0,
            "sizing_metadata": {"contracts": 1, "max_loss_total": 200.0},
            "internal_cand": {"iv_rv_spread": 0.15, "premium_direction": "debit"},
        }
        baseline = compute_risk_adjusted_ev(copy.deepcopy(s), [], 2000.0)  # flag off → no change
        with _FlagCtx("1"):
            got = compute_risk_adjusted_ev(s, [], 2000.0)
        self.assertLess(got, baseline)
        self.assertIn("vrp_ranking", s)


if __name__ == "__main__":
    unittest.main()
