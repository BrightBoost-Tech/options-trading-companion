"""Unit tests for D6 Phase 1 geometry + candidate exit rules (pure, log-only)."""

import unittest

from packages.quantum.services.exit_geometry import (
    compute_spread_geometry,
    evaluate_geometry_rules,
)


def _f_call_spread():
    """F debit call spread: long 15.5C / short 17.5C, entry 0.96 → breakeven 16.46."""
    return {
        "id": "f", "symbol": "F", "quantity": 5, "avg_entry_price": 0.96,
        "legs": [
            {"type": "call", "action": "buy", "strike": 15.5, "symbol": "O:F260626C00015500", "quantity": 5},
            {"type": "call", "action": "sell", "strike": 17.5, "symbol": "O:F260626C00017500", "quantity": 5},
        ],
    }


def _put_debit_spread():
    """Long 100P / short 95P, entry 2.0 → breakeven 98 (bearish, profit as spot falls)."""
    return {
        "id": "p", "symbol": "XYZ", "quantity": 2, "avg_entry_price": 2.0,
        "legs": [
            {"type": "put", "action": "buy", "strike": 100.0, "symbol": "O:XYZ...P00100000", "quantity": 2},
            {"type": "put", "action": "sell", "strike": 95.0, "symbol": "O:XYZ...P00095000", "quantity": 2},
        ],
    }


class TestGeometry(unittest.TestCase):
    def test_f_call_geometry(self):
        g = compute_spread_geometry(_f_call_spread(), underlying_spot=17.0, dte=29)
        self.assertTrue(g["applicable"])
        self.assertEqual(g["structure"], "debit_call_spread")
        self.assertAlmostEqual(g["breakeven"], 16.46, places=2)
        self.assertAlmostEqual(g["width"], 2.0)
        self.assertEqual(g["long_strike"], 15.5)
        self.assertEqual(g["short_strike"], 17.5)

    def test_put_geometry_breakeven(self):
        g = compute_spread_geometry(_put_debit_spread(), underlying_spot=97.0, dte=20)
        self.assertTrue(g["applicable"])
        self.assertEqual(g["structure"], "debit_put_spread")
        self.assertAlmostEqual(g["breakeven"], 98.0, places=2)  # long - debit

    def test_credit_spread_not_applicable(self):
        # call spread with long>short = credit (sell lower) → out of scope
        pos = {
            "id": "c", "symbol": "X", "quantity": -4, "avg_entry_price": 0.5,
            "legs": [
                {"type": "call", "action": "sell", "strike": 100.0, "quantity": 4},
                {"type": "call", "action": "buy", "strike": 105.0, "quantity": 4},
            ],
        }
        self.assertFalse(compute_spread_geometry(pos, 101.0, 20)["applicable"])

    def test_iron_condor_not_applicable(self):
        pos = {"id": "ic", "symbol": "X", "quantity": -2, "avg_entry_price": 1.0, "legs": [
            {"type": "put", "action": "sell", "strike": 95, "quantity": 2},
            {"type": "put", "action": "buy", "strike": 90, "quantity": 2},
            {"type": "call", "action": "sell", "strike": 105, "quantity": 2},
            {"type": "call", "action": "buy", "strike": 110, "quantity": 2},
        ]}
        g = compute_spread_geometry(pos, 100.0, 20)
        self.assertFalse(g["applicable"])
        rules = evaluate_geometry_rules(g)
        self.assertTrue(all(r["decision"] == "n/a" for r in rules.values()))


class TestRulesF(unittest.TestCase):
    """F call spread; mirrors the prompt's worked thresholds."""

    def _rules_at(self, spot, dte=29):
        g = compute_spread_geometry(_f_call_spread(), underlying_spot=spot, dte=dte)
        return evaluate_geometry_rules(g)

    def test_R1_hold_then_take_profit(self):
        self.assertEqual(self._rules_at(17.0)["R1"]["decision"], "hold")
        self.assertEqual(self._rules_at(17.5)["R1"]["decision"], "take_profit")

    def test_R2_breakeven(self):
        self.assertEqual(self._rules_at(16.3)["R2"]["decision"], "stop")
        self.assertEqual(self._rules_at(16.6)["R2"]["decision"], "hold")

    def test_R3_long_strike(self):
        self.assertEqual(self._rules_at(15.3)["R3"]["decision"], "stop")
        self.assertEqual(self._rules_at(15.6)["R3"]["decision"], "hold")

    def test_R1_frac_level(self):
        # 0.8 level = 15.5 + 0.8*2 = 17.1
        self.assertEqual(self._rules_at(17.0)["R1_frac"]["decision"], "hold")
        self.assertEqual(self._rules_at(17.2)["R1_frac"]["decision"], "take_profit")

    def test_R4_tightens_at_low_dte(self):
        # At dte=2, frac=0.5 → level = 15.5 + 0.5*2 = 16.5; spot 16.6 takes profit.
        self.assertEqual(self._rules_at(16.6, dte=2)["R4"]["decision"], "take_profit")
        # At dte=29 (frac 0.8 → level 17.1), spot 16.6 holds.
        self.assertEqual(self._rules_at(16.6, dte=29)["R4"]["decision"], "hold")

    def test_no_spot_all_na(self):
        g = compute_spread_geometry(_f_call_spread(), underlying_spot=None, dte=29)
        self.assertTrue(g["applicable"])  # geometry computable
        rules = evaluate_geometry_rules(g)  # but rules n/a without spot
        self.assertTrue(all(r["decision"] == "n/a" for r in rules.values()))


if __name__ == "__main__":
    unittest.main()
