"""
Tests for D1 midday-writer surfacing parity (build_midday_surfacing_fields).

The midday entry writer previously left probability_of_profit / max_loss_total /
capital_required / rationale at column-NULL and never persisted max_profit / net_ev.
This helper assembles those informational fields from values already in scope.
Purely additive — no decision/sizing/ranking code reads these columns.
"""

import unittest

from packages.quantum.services.workflow_orchestrator import (
    build_midday_surfacing_fields,
)


class TestMiddaySurfacingFields(unittest.TestCase):
    def _call(self, **overrides):
        kwargs = dict(
            cand={
                "max_profit_per_contract": 104.0,
                "multi_strategy": {"net_ev": 20.0},
                "score": 72.5,
            },
            sizing={
                "contracts": 5,
                "max_loss_total": 480.0,
                "capital_required": 480.0,
            },
            order_json={"limit_price": 0.96},
            ev=24.08,
            pop=0.36,
            strategy="LONG_CALL_DEBIT_SPREAD",
            ticker="F",
            regime="normal",
            risk_multiplier=1.0,
        )
        kwargs.update(overrides)
        return build_midday_surfacing_fields(**kwargs)

    def test_all_columns_populated(self):
        out = self._call()
        # mirrored sizing values
        self.assertEqual(out["max_loss_total"], 480.0)
        self.assertEqual(out["capital_required"], 480.0)
        self.assertEqual(out["risk_multiplier"], 1.0)
        # max_profit_total = contracts × honest per-contract value
        self.assertAlmostEqual(out["max_profit_total"], 520.0)  # 104 × 5
        # net_ev promoted from multi_strategy
        self.assertEqual(out["net_ev"], 20.0)
        # rationale assembled and factual
        self.assertIn("LONG_CALL_DEBIT_SPREAD on F", out["rationale"])
        self.assertIn("normal regime", out["rationale"])
        self.assertIn("EV $24.08", out["rationale"])
        self.assertIn("PoP 36.0%", out["rationale"])
        self.assertIn("score 72.5", out["rationale"])

    def test_non_finite_max_profit_dropped_to_none(self):
        # Single-leg long call would yield inf per-contract max profit; never
        # emitted today, but guard against persisting a junk value.
        out = self._call(cand={"max_profit_per_contract": float("inf"), "score": 50})
        self.assertIsNone(out["max_profit_total"])

    def test_zero_contracts_yields_none_max_profit(self):
        out = self._call(sizing={"contracts": 0, "max_loss_total": 0, "capital_required": 0})
        self.assertIsNone(out["max_profit_total"])

    def test_missing_multi_strategy_yields_none_net_ev(self):
        out = self._call(cand={"max_profit_per_contract": 104.0, "score": 50})
        self.assertIsNone(out["net_ev"])
        # max_profit still computed
        self.assertAlmostEqual(out["max_profit_total"], 520.0)

    def test_missing_max_profit_per_contract_yields_none(self):
        out = self._call(cand={"multi_strategy": {"net_ev": 5.0}, "score": 50})
        self.assertIsNone(out["max_profit_total"])
        self.assertEqual(out["net_ev"], 5.0)

    def test_handles_none_inputs_gracefully(self):
        out = build_midday_surfacing_fields(
            cand={}, sizing={}, order_json={}, ev=None, pop=None,
            strategy="X", ticker="Y", regime="normal", risk_multiplier=None,
        )
        self.assertIsNone(out["max_profit_total"])
        self.assertIsNone(out["net_ev"])
        self.assertIn("X on Y", out["rationale"])


if __name__ == "__main__":
    unittest.main()
