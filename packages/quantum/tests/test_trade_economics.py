"""
Tests for D1 trade-economics surfacing helper (compute-on-read).

Covers: reward:risk formed from per-contract geometry, breakeven for debit/credit
× call/put, payoff-grid endpoints (= -max_loss / +max_profit) and the breakeven
row (= $0), and None for non-vertical structures.
"""

import unittest

from packages.quantum.services.trade_economics import (
    compute_trade_economics,
    _parse_occ,
)


def _sugg(strategy, legs, limit_price):
    return {
        "strategy": strategy,
        "order_json": {"legs": legs, "limit_price": limit_price},
    }


class TestParseOcc(unittest.TestCase):
    def test_with_prefix(self):
        info = _parse_occ("O:F260626C00015500")
        self.assertEqual(info["type"], "call")
        self.assertAlmostEqual(info["strike"], 15.5)

    def test_without_prefix(self):
        info = _parse_occ("F260626P00017500")
        self.assertEqual(info["type"], "put")
        self.assertAlmostEqual(info["strike"], 17.5)

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_occ("not-an-occ-symbol"))
        self.assertIsNone(_parse_occ(None))


class TestDebitCallSpread(unittest.TestCase):
    """F-shaped row: buy 15.5C / sell 17.5C, width 2.0, debit 0.96."""

    def setUp(self):
        self.econ = compute_trade_economics(_sugg(
            "LONG_CALL_DEBIT_SPREAD",
            [
                {"side": "buy", "symbol": "O:F260626C00015500", "quantity": 5},
                {"side": "sell", "symbol": "O:F260626C00017500", "quantity": 5},
            ],
            0.96,
        ))

    def test_structure(self):
        self.assertEqual(self.econ["structure"], "debit_spread")
        self.assertEqual(self.econ["option_type"], "call")
        self.assertAlmostEqual(self.econ["width"], 2.0)

    def test_max_profit_loss(self):
        self.assertAlmostEqual(self.econ["max_loss_per_contract"], 96.0)
        self.assertAlmostEqual(self.econ["max_profit_per_contract"], 104.0)

    def test_reward_risk(self):
        # (width - debit) / debit = 1.04 / 0.96
        self.assertAlmostEqual(self.econ["reward_risk_ratio"], 1.083, places=3)

    def test_breakeven(self):
        # long strike + debit
        self.assertAlmostEqual(self.econ["breakeven"], 16.46)

    def test_payoff_endpoints_and_breakeven_row(self):
        table = {row["underlying"]: row["pl_per_contract"] for row in self.econ["payoff_table"]}
        # below both strikes -> max loss
        self.assertAlmostEqual(table[14.5], -96.0)
        # above both strikes -> max profit
        self.assertAlmostEqual(table[18.5], 104.0)
        # breakeven row -> ~$0
        self.assertAlmostEqual(table[16.46], 0.0, places=2)


class TestDebitPutSpread(unittest.TestCase):
    """buy 100P / sell 95P, width 5, debit 2.0."""

    def setUp(self):
        self.econ = compute_trade_economics(_sugg(
            "LONG_PUT_DEBIT_SPREAD",
            [
                {"side": "buy", "symbol": "O:XYZ260626P00100000", "quantity": 1},
                {"side": "sell", "symbol": "O:XYZ260626P00095000", "quantity": 1},
            ],
            2.0,
        ))

    def test_breakeven_and_rr(self):
        self.assertEqual(self.econ["option_type"], "put")
        self.assertAlmostEqual(self.econ["breakeven"], 98.0)  # long strike - debit
        self.assertAlmostEqual(self.econ["max_loss_per_contract"], 200.0)
        self.assertAlmostEqual(self.econ["max_profit_per_contract"], 300.0)
        self.assertAlmostEqual(self.econ["reward_risk_ratio"], 1.5, places=3)

    def test_payoff_endpoints(self):
        table = {row["underlying"]: row["pl_per_contract"] for row in self.econ["payoff_table"]}
        self.assertAlmostEqual(table[102.5], -200.0)  # above both -> max loss
        self.assertAlmostEqual(table[92.5], 300.0)    # below both -> max profit


class TestCreditCallSpread(unittest.TestCase):
    """sell 100C / buy 105C, width 5, credit 1.5."""

    def setUp(self):
        self.econ = compute_trade_economics(_sugg(
            "SHORT_CALL_CREDIT_SPREAD",
            [
                {"side": "sell", "symbol": "O:XYZ260626C00100000", "quantity": 1},
                {"side": "buy", "symbol": "O:XYZ260626C00105000", "quantity": 1},
            ],
            1.5,
        ))

    def test_economics(self):
        self.assertEqual(self.econ["structure"], "credit_spread")
        self.assertAlmostEqual(self.econ["max_profit_per_contract"], 150.0)
        self.assertAlmostEqual(self.econ["max_loss_per_contract"], 350.0)
        self.assertAlmostEqual(self.econ["reward_risk_ratio"], 0.429, places=3)
        self.assertAlmostEqual(self.econ["breakeven"], 101.5)  # short strike + credit

    def test_payoff_endpoints(self):
        table = {row["underlying"]: row["pl_per_contract"] for row in self.econ["payoff_table"]}
        self.assertAlmostEqual(table[97.5], 150.0)    # below both -> max profit (keep credit)
        self.assertAlmostEqual(table[107.5], -350.0)  # above both -> max loss
        self.assertAlmostEqual(table[101.5], 0.0, places=2)  # breakeven


class TestCreditPutSpread(unittest.TestCase):
    """sell 100P / buy 95P, width 5, credit 1.5."""

    def test_breakeven(self):
        econ = compute_trade_economics(_sugg(
            "SHORT_PUT_CREDIT_SPREAD",
            [
                {"side": "sell", "symbol": "O:XYZ260626P00100000", "quantity": 1},
                {"side": "buy", "symbol": "O:XYZ260626P00095000", "quantity": 1},
            ],
            1.5,
        ))
        self.assertAlmostEqual(econ["breakeven"], 98.5)  # short strike - credit


class TestNonVertical(unittest.TestCase):
    def test_single_leg_returns_none(self):
        self.assertIsNone(compute_trade_economics(_sugg(
            "LONG_CALL",
            [{"side": "buy", "symbol": "O:F260626C00015500", "quantity": 1}],
            0.42,
        )))

    def test_iron_condor_returns_none(self):
        legs = [
            {"side": "sell", "symbol": "O:XYZ260626P00095000", "quantity": 1},
            {"side": "buy", "symbol": "O:XYZ260626P00090000", "quantity": 1},
            {"side": "sell", "symbol": "O:XYZ260626C00105000", "quantity": 1},
            {"side": "buy", "symbol": "O:XYZ260626C00110000", "quantity": 1},
        ]
        self.assertIsNone(compute_trade_economics(_sugg("IRON_CONDOR", legs, 1.2)))

    def test_mismatched_types_returns_none(self):
        # one call + one put is not a vertical
        self.assertIsNone(compute_trade_economics(_sugg(
            "WEIRD",
            [
                {"side": "buy", "symbol": "O:XYZ260626C00100000", "quantity": 1},
                {"side": "sell", "symbol": "O:XYZ260626P00100000", "quantity": 1},
            ],
            1.0,
        )))

    def test_zero_price_returns_none(self):
        self.assertIsNone(compute_trade_economics(_sugg(
            "LONG_CALL_DEBIT_SPREAD",
            [
                {"side": "buy", "symbol": "O:F260626C00015500", "quantity": 1},
                {"side": "sell", "symbol": "O:F260626C00017500", "quantity": 1},
            ],
            0.0,
        )))


if __name__ == "__main__":
    unittest.main()
