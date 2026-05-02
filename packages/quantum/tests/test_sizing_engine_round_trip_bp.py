"""Tests for #100 / Option A — round-trip BP check at sizing.

Per docs/designs/option_a_round_trip_bp.md Section 6 test plan.
Three layers:
- Layer 1: source-level structural assertions (helper exists,
  signature accepts strategy, rejection-reason vocabulary present)
- Layer 2: helper behavioral (one test per row of Section 3
  formula table)
- Layer 3: sizing integration behavioral (one test per row of
  Section 6 Layer 3 table; boundary OBP = ceil(296 + 296 × 1.1) = 622
  per locked safety_factor=1.1 calibration)
"""

import inspect
import unittest
from pathlib import Path

from packages.quantum.services.sizing_engine import (
    DEFAULT_ROUND_TRIP_SAFETY_FACTOR,
    calculate_sizing,
    estimate_close_bp,
)


SIZING_ENGINE_PATH = (
    Path(__file__).parent.parent / "services" / "sizing_engine.py"
)


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural
# ─────────────────────────────────────────────────────────────────────


class TestSourceLevelStructural(unittest.TestCase):
    def test_estimate_close_bp_function_exists(self):
        self.assertTrue(callable(estimate_close_bp))

    def test_calculate_sizing_accepts_strategy_kwarg(self):
        sig = inspect.signature(calculate_sizing)
        self.assertIn("strategy", sig.parameters)
        self.assertIn("safety_factor", sig.parameters)
        # Both must be keyword-only so positional callers don't break.
        self.assertEqual(
            sig.parameters["strategy"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(
            sig.parameters["safety_factor"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

    def test_rejection_reason_vocabulary_includes_round_trip(self):
        src = SIZING_ENGINE_PATH.read_text(encoding="utf-8")
        self.assertIn("round_trip_bp_insufficient", src)


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Helper behavioral (one per Section 3 formula row)
# ─────────────────────────────────────────────────────────────────────


class TestEstimateCloseBpHelper(unittest.TestCase):
    def test_long_call_zero_close_bp(self):
        self.assertEqual(estimate_close_bp("LONG_CALL", 100.0), 0.0)

    def test_long_put_zero_close_bp(self):
        self.assertEqual(estimate_close_bp("LONG_PUT", 100.0), 0.0)

    def test_long_call_debit_spread_full_close(self):
        # BAC-shape: $296 max_loss → $296 estimated close BP
        self.assertEqual(
            estimate_close_bp("LONG_CALL_DEBIT_SPREAD", 296.0),
            296.0,
        )

    def test_long_put_debit_spread_full_close(self):
        self.assertEqual(
            estimate_close_bp("LONG_PUT_DEBIT_SPREAD", 200.0),
            200.0,
        )

    def test_short_call_credit_zero_close_bp(self):
        self.assertEqual(
            estimate_close_bp("SHORT_CALL_CREDIT_SPREAD", 500.0),
            0.0,
        )

    def test_short_put_credit_zero_close_bp(self):
        self.assertEqual(
            estimate_close_bp("SHORT_PUT_CREDIT_SPREAD", 500.0),
            0.0,
        )

    def test_iron_condor_double_close_bp(self):
        self.assertEqual(
            estimate_close_bp("IRON_CONDOR", 250.0),
            500.0,
        )

    def test_unknown_strategy_defaults_conservative(self):
        # Conservative fallback: full max_loss
        self.assertEqual(estimate_close_bp("FOO", 100.0), 100.0)

    def test_zero_max_loss_returns_zero(self):
        # Edge case: any strategy + 0 max_loss → 0
        self.assertEqual(
            estimate_close_bp("LONG_CALL_DEBIT_SPREAD", 0.0),
            0.0,
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 3 — Sizing integration behavioral
# ─────────────────────────────────────────────────────────────────────


# Boundary OBP at the locked calibration: ceil(296 + 296 * 1.1)
# = ceil(621.6) = 622. If DEFAULT_ROUND_TRIP_SAFETY_FACTOR ever
# changes, this value must be recomputed.
_BOUNDARY_OBP_AT_CALIBRATED = 622


class TestSizingIntegration(unittest.TestCase):
    """Integration tests call real `calculate_sizing` end-to-end."""

    def _make_call(
        self,
        *,
        obp: float,
        entry: float,
        strategy: str = "LONG_CALL_DEBIT_SPREAD",
        safety: float = DEFAULT_ROUND_TRIP_SAFETY_FACTOR,
        risk_budget_dollars: float = 100_000.0,
    ):
        """Helper. Uses risk_budget_dollars override to ensure
        contracts_by_risk doesn't dominate; we want the round-trip
        dimension to be the visible constraint in these tests."""
        return calculate_sizing(
            account_buying_power=obp,
            max_loss_per_contract=entry,
            collateral_required_per_contract=entry,
            risk_budget_dollars=risk_budget_dollars,
            strategy=strategy,
            safety_factor=safety,
        )

    def test_sufficient_obp_passes(self):
        # OBP=1000, entry=296, close=296×1.1=325.6 → required=621.6
        # contracts_by_round_trip = floor(1000/621.6) = 1
        result = self._make_call(obp=1000, entry=296)
        self.assertGreaterEqual(result["contracts"], 1)

    def test_insufficient_obp_rejected(self):
        # OBP=500, required=621.6 → contracts=0, reason cites round-trip
        result = self._make_call(obp=500, entry=296)
        self.assertEqual(result["contracts"], 0)
        self.assertIn("round_trip_bp_insufficient", result["reason"])

    def test_boundary_just_enough(self):
        # OBP = ceil(296 + 296 × 1.1) = 622 → exactly 1 contract fits
        result = self._make_call(
            obp=_BOUNDARY_OBP_AT_CALIBRATED,
            entry=296,
        )
        self.assertEqual(result["contracts"], 1)

    def test_safety_factor_1_0_more_permissive(self):
        # Explicitly pass safety=1.0 to verify the parameter wires through.
        # Math: 296 + 296×1.0 = 592 ≤ 600 → 1 contract fits at OBP=600.
        result = self._make_call(obp=600, entry=296, safety=1.0)
        self.assertEqual(result["contracts"], 1)

    def test_long_call_unaffected_by_close_bp(self):
        # OBP=100, entry=50, close=0 (LONG_CALL) → required = 50 + 0 = 50
        # contracts_by_round_trip = floor(100/50) = 2
        result = self._make_call(
            obp=100, entry=50, strategy="LONG_CALL",
        )
        self.assertEqual(result["contracts"], 2)

    def test_credit_spread_unaffected(self):
        # OBP=500, entry=500, close=0 (CREDIT) → required = 500
        # contracts_by_round_trip = floor(500/500) = 1
        result = self._make_call(
            obp=500, entry=500, strategy="SHORT_CALL_CREDIT_SPREAD",
        )
        self.assertEqual(result["contracts"], 1)

    def test_iron_condor_double_constraint(self):
        # OBP=1000, entry=250, close=500 (IRON_CONDOR = 2×max_loss),
        # safety=1.1 → required = 250 + 500×1.1 = 800
        # contracts_by_round_trip = floor(1000/800) = 1
        result = self._make_call(
            obp=1000, entry=250, strategy="IRON_CONDOR",
        )
        self.assertEqual(result["contracts"], 1)


if __name__ == "__main__":
    unittest.main()
