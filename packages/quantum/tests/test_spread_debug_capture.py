"""Tests for the D8 observation-only credit-spread capture (pin the 2×credit artifact).

OBSERVATION-ONLY: build_spread_debug_capture is pure — it returns capture fields
and changes no scanner logic. These verify purity/isolation, fail-soft on missing
quotes, and that the fields needed to pin H-fetch vs H-formula are recorded.
"""

import copy
import unittest

from packages.quantum.options_scanner import build_spread_debug_capture


def _specimen():
    """An MU-like credit-spread rejection: credit 5.07, combo_width_share 10.14,
    max_loss_share 5.07 (the artifact: combo = 2×credit; max_loss_share == credit
    instead of width − credit). Wing (buy) leg arrives bid=0."""
    legs = [
        {"strike": 900.0, "side": "sell", "bid": 8.0, "ask": 9.0, "premium": 8.0},
        {"strike": 890.0, "side": "buy", "bid": 0.0, "ask": 3.0, "premium": 3.0},
    ]
    return dict(
        legs=legs,
        cost_range=None,            # wing bid=0 → _combo_cost_range_from_legs None
        sum_leg_spreads=None,       # wing bid=0 → None
        combo_width_share=10.14,
        fallback_width_share=0.2535,  # 0.05 * 5.07
        total_cost=-5.07,           # credit (negative)
        max_loss_contract=507.0,
        max_loss_share=5.07,        # the suspicious value (== credit)
    )


class TestSpreadDebugCapture(unittest.TestCase):
    def test_purity_inputs_not_mutated(self):
        args = _specimen()
        legs_before = copy.deepcopy(args["legs"])
        _ = build_spread_debug_capture(**args)
        self.assertEqual(args["legs"], legs_before)  # no mutation

    def test_per_leg_captured_with_wing_bid_zero(self):
        out = build_spread_debug_capture(**_specimen())
        self.assertEqual(len(out["per_leg"]), 2)
        wing = [l for l in out["per_leg"] if l["side"] == "buy"][0]
        self.assertEqual(wing["bid"], 0.0)  # the missing-piece signal
        self.assertEqual(wing["strike"], 890.0)

    def test_combo_source_fallback_when_cost_range_none(self):
        out = build_spread_debug_capture(**_specimen())
        self.assertEqual(out["combo_source"], "fallback")
        self.assertIsNone(out["cost_range"])

    def test_combo_source_cost_range_when_present(self):
        args = _specimen()
        args["cost_range"] = {"cost_min": -5.07, "cost_max": -4.0, "combo_spread_share": 1.07}
        out = build_spread_debug_capture(**args)
        self.assertEqual(out["combo_source"], "cost_range")
        self.assertAlmostEqual(out["cost_range"]["combo_spread_share"], 1.07)

    def test_max_loss_derivation_pins_h_formula(self):
        out = build_spread_debug_capture(**_specimen())
        d = out["max_loss_derivation"]
        # The H-formula test: width − credit = 10 − 5.07 = 4.93 (what a credit
        # spread's max_loss_share SHOULD be), vs the captured 5.07 (== credit).
        self.assertAlmostEqual(d["credit"], 5.07, places=2)
        self.assertAlmostEqual(d["strike_width"], 10.0, places=2)
        self.assertAlmostEqual(d["expected_credit_max_loss_share"], 4.93, places=2)
        self.assertAlmostEqual(d["max_loss_share"], 5.07, places=2)
        # The artifact fingerprint:
        self.assertAlmostEqual(d["combo_over_credit"], 2.0, places=3)

    def test_candidate_values_recorded(self):
        out = build_spread_debug_capture(**_specimen())
        cv = out["candidate_values"]
        self.assertAlmostEqual(cv["logged_combo_width_share"], 10.14, places=2)
        self.assertIsNone(cv["sum_leg_spreads"])
        self.assertAlmostEqual(cv["fallback_width_share"], 0.2535, places=4)

    def test_failsoft_missing_bid_ask(self):
        legs = [
            {"strike": 900.0, "side": "sell"},  # no bid/ask
            {"strike": 890.0, "side": "buy", "bid": None, "ask": None},
        ]
        out = build_spread_debug_capture(
            legs=legs, cost_range=None, sum_leg_spreads=None,
            combo_width_share=10.14, fallback_width_share=0.25,
            total_cost=-5.07, max_loss_contract=507.0, max_loss_share=5.07,
        )
        self.assertEqual(len(out["per_leg"]), 2)
        self.assertIsNone(out["per_leg"][0]["bid"])  # null, no raise

    def test_handles_garbage_legs(self):
        out = build_spread_debug_capture(
            legs=["junk", None], cost_range=None, sum_leg_spreads=None,
            combo_width_share=None, fallback_width_share=None,
            total_cost=0, max_loss_contract=None, max_loss_share=None,
        )
        self.assertEqual(out["per_leg"], [])  # non-dict legs skipped, no raise


if __name__ == "__main__":
    unittest.main()
