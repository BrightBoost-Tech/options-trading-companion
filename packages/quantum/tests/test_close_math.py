"""
Unit tests for compute_realized_pl — PR #6 Commit 2.

Test matrix (per PR #6 scope spec):
    1. PYPL cfe69b28 regression (HEADLINE — 2026-04-17 incident)
    2. Single-leg long call (baseline)
    3. Single-leg short put (negative-credit baseline)
    4. Multi-leg debit spread, profitable close
    5. Multi-leg debit spread, stop-loss close (loss but smaller than PYPL)
    6. Multi-leg credit spread, profitable close
    7. Multi-leg credit spread, stop-loss close (loss)
    8. Partial-fill detection: raises PartialFillDetected
    9. Additional defensive cases (empty legs, bad action, qty <= 0,
       bad spread_type, bad multiplier type coercion)

The PYPL regression (test 1) is the headline. Its presence enforces
that the post-PR #790 sign convention logic, now consolidated into
compute_realized_pl, does not regress during future refactors.
"""

import unittest
from decimal import Decimal

from packages.quantum.services.close_math import (
    compute_realized_pl,
    PartialFillDetected,
)


class TestPyplCfe69b28Regression(unittest.TestCase):
    """
    Regression test for PYPL cfe69b28 (2026-04-17).

    Pre-PR #790, _close_position_on_fill computed realized_pl without
    handling Alpaca's multi-leg net-credit sign convention, producing
    realized_pl = -3324 for a position whose true realized P&L was
    -204 (paid 2.94 debit on entry, received 2.60 credit on close,
    6 spreads × 100 multiplier = −$204).

    This function, when migrated into the close path (PR #6 remaining
    commits), MUST produce Decimal('-204.00') for these exact leg
    inputs. If this test ever returns -3324, the sign convention
    logic has regressed into the reconciler.

    Exact leg-fill data from Alpaca order da0b9146-59f7-46a8-a292-
    86c0325aaca9 (the close order that filled 2026-04-17 17:15:11Z
    and produced the ghost fill that #784/#790/PYPL-incident-chain
    was diagnosing):
        - sell PYPL260515C00047500 @ 5.05, filled_qty=6
        - buy  PYPL260515C00052500 @ 2.45, filled_qty=6
        - net close credit per spread = 5.05 - 2.45 = 2.60
        - entry was 2.94 debit per spread (paper_positions.avg_entry_price)
        - realized = (2.60 - 2.94) * 6 * 100 = −$204
    """

    def test_compute_realized_pl_pypl_cfe69b28_regression(self):
        close_legs = [
            {
                "symbol": "PYPL260515C00047500",
                "action": "sell",
                "filled_qty": 6,
                "filled_avg_price": Decimal("5.05"),
            },
            {
                "symbol": "PYPL260515C00052500",
                "action": "buy",
                "filled_qty": 6,
                "filled_avg_price": Decimal("2.45"),
            },
        ]
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("2.94"),
            qty=6,
            spread_type="debit",
        )
        self.assertEqual(
            result, Decimal("-204.00"),
            f"PYPL cfe69b28 regression: expected -204.00, got {result}. "
            f"Pre-PR #790 buggy math produced -3324.00 for this case. "
            f"If this test fails with -3324, the sign convention "
            f"has regressed.",
        )
        # Belt-and-suspenders: explicitly assert we do NOT produce
        # the pre-PR #790 incorrect value under any circumstance.
        self.assertNotEqual(
            result, Decimal("-3324.00"),
            "compute_realized_pl regressed to pre-PR #790 buggy math.",
        )
        self.assertNotEqual(
            result, Decimal("-3324"),
            "compute_realized_pl regressed to pre-PR #790 buggy math.",
        )


class TestSingleLegBaselines(unittest.TestCase):
    """Simple single-leg cases. No multi-leg sign convention at play —
    these establish baseline arithmetic correctness."""

    def test_single_leg_long_call_profitable(self):
        """Bought call @ 3.00, sold @ 5.00, 2 contracts → +$400."""
        close_legs = [
            {
                "symbol": "AAPL260417C00180000",
                "action": "sell",
                "filled_qty": 2,
                "filled_avg_price": Decimal("5.00"),
            },
        ]
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("3.00"),
            qty=2,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("400.00"))

    def test_single_leg_long_call_loss(self):
        """Bought call @ 3.00, sold @ 1.50, 2 contracts → -$300."""
        close_legs = [
            {
                "symbol": "AAPL260417C00180000",
                "action": "sell",
                "filled_qty": 2,
                "filled_avg_price": Decimal("1.50"),
            },
        ]
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("3.00"),
            qty=2,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("-300.00"))

    def test_single_leg_short_put_profitable(self):
        """Sold put @ 4.50 (credit received), bought back @ 1.00, 3 contracts.
        Short credit: realized = (entry − close) × qty × 100 = (4.50 − 1.00) × 3 × 100 = +$1,050."""
        close_legs = [
            {
                "symbol": "TSLA260320P00200000",
                "action": "buy",
                "filled_qty": 3,
                "filled_avg_price": Decimal("1.00"),
            },
        ]
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("4.50"),
            qty=3,
            spread_type="credit",
        )
        self.assertEqual(result, Decimal("1050.00"))

    def test_single_leg_short_put_loss(self):
        """Sold put @ 2.00 (credit), bought back @ 6.00, 1 contract.
        Realized = (2.00 − 6.00) × 1 × 100 = −$400."""
        close_legs = [
            {
                "symbol": "TSLA260320P00200000",
                "action": "buy",
                "filled_qty": 1,
                "filled_avg_price": Decimal("6.00"),
            },
        ]
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("2.00"),
            qty=1,
            spread_type="credit",
        )
        self.assertEqual(result, Decimal("-400.00"))


class TestMultiLegDebitSpread(unittest.TestCase):
    """Long debit spreads — this is the class where PR #790's sign
    convention matters. compute_realized_pl derives from legs, so
    the mleg parent sign question is out of scope here."""

    def test_debit_spread_profitable_close(self):
        """Long call debit spread, entry 1.50, close net credit 3.00, qty 4.
        Realized = (3.00 − 1.50) × 4 × 100 = +$600."""
        close_legs = [
            {
                "symbol": "SPY260515C00500000",
                "action": "sell",
                "filled_qty": 4,
                "filled_avg_price": Decimal("4.50"),
            },
            {
                "symbol": "SPY260515C00510000",
                "action": "buy",
                "filled_qty": 4,
                "filled_avg_price": Decimal("1.50"),
            },
        ]
        # net close credit per spread: 4.50 − 1.50 = 3.00
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("1.50"),
            qty=4,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("600.00"))

    def test_debit_spread_stop_loss_close(self):
        """Long call debit spread, entry 2.00, close net credit 0.80, qty 5.
        Realized = (0.80 − 2.00) × 5 × 100 = −$600.
        Smaller loss than PYPL to distinguish 'loss happened'
        from 'PYPL-specific value'."""
        close_legs = [
            {
                "symbol": "QQQ260515C00450000",
                "action": "sell",
                "filled_qty": 5,
                "filled_avg_price": Decimal("1.20"),
            },
            {
                "symbol": "QQQ260515C00455000",
                "action": "buy",
                "filled_qty": 5,
                "filled_avg_price": Decimal("0.40"),
            },
        ]
        # net close credit per spread: 1.20 − 0.40 = 0.80
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("2.00"),
            qty=5,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("-600.00"))


class TestMultiLegCreditSpread(unittest.TestCase):
    """Short credit spreads — entry is credit received, close is
    debit paid. Symmetric to debit spreads."""

    def test_credit_spread_profitable_close(self):
        """Short put credit spread, entry 1.80 credit, close debit 0.50, qty 3.
        Realized = (1.80 − 0.50) × 3 × 100 = +$390."""
        close_legs = [
            {
                "symbol": "AMD260515P00120000",
                "action": "buy",
                "filled_qty": 3,
                "filled_avg_price": Decimal("1.00"),
            },
            {
                "symbol": "AMD260515P00115000",
                "action": "sell",
                "filled_qty": 3,
                "filled_avg_price": Decimal("0.50"),
            },
        ]
        # net close debit per spread: 1.00 − 0.50 = 0.50
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("1.80"),
            qty=3,
            spread_type="credit",
        )
        self.assertEqual(result, Decimal("390.00"))

    def test_credit_spread_stop_loss_close(self):
        """Short call credit spread, entry 1.50 credit, close debit 4.00, qty 2.
        Realized = (1.50 − 4.00) × 2 × 100 = −$500."""
        close_legs = [
            {
                "symbol": "NVDA260515C00900000",
                "action": "buy",
                "filled_qty": 2,
                "filled_avg_price": Decimal("6.00"),
            },
            {
                "symbol": "NVDA260515C00910000",
                "action": "sell",
                "filled_qty": 2,
                "filled_avg_price": Decimal("2.00"),
            },
        ]
        # net close debit per spread: 6.00 − 2.00 = 4.00
        result = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("1.50"),
            qty=2,
            spread_type="credit",
        )
        self.assertEqual(result, Decimal("-500.00"))


class TestPartialFillDetection(unittest.TestCase):
    """PR #6 scope is all-or-nothing. Partial fills must be flagged,
    never silently computed. Caller handles via critical risk_alert."""

    def test_partial_fill_leg_qty_mismatch(self):
        """One leg filled fewer contracts than the other → partial."""
        close_legs = [
            {
                "symbol": "PYPL260515C00047500",
                "action": "sell",
                "filled_qty": 6,
                "filled_avg_price": Decimal("5.05"),
            },
            {
                "symbol": "PYPL260515C00052500",
                "action": "buy",
                "filled_qty": 4,  # mismatch!
                "filled_avg_price": Decimal("2.45"),
            },
        ]
        with self.assertRaises(PartialFillDetected) as cm:
            compute_realized_pl(
                close_legs=close_legs,
                entry_price=Decimal("2.94"),
                qty=6,
                spread_type="debit",
            )
        self.assertIn("filled_qty", str(cm.exception))

    def test_partial_fill_all_legs_same_but_below_position_qty(self):
        """Both legs filled same count, but less than position qty."""
        close_legs = [
            {
                "symbol": "PYPL260515C00047500",
                "action": "sell",
                "filled_qty": 3,
                "filled_avg_price": Decimal("5.05"),
            },
            {
                "symbol": "PYPL260515C00052500",
                "action": "buy",
                "filled_qty": 3,
                "filled_avg_price": Decimal("2.45"),
            },
        ]
        with self.assertRaises(PartialFillDetected):
            compute_realized_pl(
                close_legs=close_legs,
                entry_price=Decimal("2.94"),
                qty=6,  # position had 6, only 3 filled
                spread_type="debit",
            )


class TestDefensiveInputs(unittest.TestCase):
    """Guards against malformed input — fail loud, not silent."""

    def test_empty_close_legs_raises(self):
        with self.assertRaises(ValueError) as cm:
            compute_realized_pl(
                close_legs=[],
                entry_price=Decimal("1.00"),
                qty=1,
                spread_type="debit",
            )
        self.assertIn("empty", str(cm.exception).lower())

    def test_qty_zero_raises(self):
        legs = [{"action": "sell", "filled_qty": 0, "filled_avg_price": Decimal("1.00")}]
        with self.assertRaises(ValueError) as cm:
            compute_realized_pl(
                close_legs=legs,
                entry_price=Decimal("1.00"),
                qty=0,
                spread_type="debit",
            )
        self.assertIn("positive", str(cm.exception).lower())

    def test_qty_negative_raises(self):
        legs = [{"action": "sell", "filled_qty": 1, "filled_avg_price": Decimal("1.00")}]
        with self.assertRaises(ValueError):
            compute_realized_pl(
                close_legs=legs,
                entry_price=Decimal("1.00"),
                qty=-1,  # caller forgot abs()
                spread_type="debit",
            )

    def test_invalid_spread_type_raises(self):
        legs = [{"action": "sell", "filled_qty": 1, "filled_avg_price": Decimal("1.00")}]
        with self.assertRaises(ValueError) as cm:
            compute_realized_pl(
                close_legs=legs,
                entry_price=Decimal("1.00"),
                qty=1,
                spread_type="neither",  # type: ignore
            )
        self.assertIn("spread_type", str(cm.exception))

    def test_unrecognized_leg_action_raises(self):
        legs = [{"action": "hodl", "filled_qty": 1, "filled_avg_price": Decimal("1.00")}]
        with self.assertRaises(ValueError) as cm:
            compute_realized_pl(
                close_legs=legs,
                entry_price=Decimal("1.00"),
                qty=1,
                spread_type="debit",
            )
        self.assertIn("hodl", str(cm.exception))

    def test_accepts_side_key_as_alias_for_action(self):
        """Alpaca leg data uses 'side'; position.legs use 'action'.
        Function accepts both for caller convenience."""
        legs = [
            {"side": "sell", "filled_qty": 1, "filled_avg_price": Decimal("2.00")},
        ]
        result = compute_realized_pl(
            close_legs=legs,
            entry_price=Decimal("1.00"),
            qty=1,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("100.00"))  # (2.00 − 1.00) × 1 × 100

    def test_accepts_buy_to_close_sell_to_close_variants(self):
        """Alpaca position_intent-decorated sides should also work."""
        legs = [
            {
                "action": "sell_to_close",
                "filled_qty": 1,
                "filled_avg_price": Decimal("3.00"),
            },
        ]
        result = compute_realized_pl(
            close_legs=legs,
            entry_price=Decimal("1.00"),
            qty=1,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("200.00"))

    def test_numeric_input_coercion_from_string(self):
        """Supabase returns Numeric columns as strings. Function must
        handle them via Decimal string-init (not float-init)."""
        legs = [
            {"action": "sell", "filled_qty": "2", "filled_avg_price": "2.50"},
        ]
        result = compute_realized_pl(
            close_legs=legs,
            entry_price="1.50",  # string input
            qty=2,
            spread_type="debit",
        )
        self.assertEqual(result, Decimal("200.00"))

    def test_float_entry_price_does_not_corrupt_decimal_math(self):
        """Belt-and-suspenders: even if a caller passes float entry_price
        by mistake, the internal Decimal math should not produce
        float-imprecision artifacts (e.g., 0.1 + 0.2 ≠ 0.3). This
        test uses a classic float-imprecision-prone case."""
        legs = [
            {"action": "sell", "filled_qty": 1, "filled_avg_price": 0.3},
        ]
        result = compute_realized_pl(
            close_legs=legs,
            entry_price=0.1,  # classic 0.1 + 0.2 float imprecision source
            qty=1,
            spread_type="debit",
        )
        # Expected: (0.30 − 0.10) × 1 × 100 = 20.00 exactly.
        # If coercion went through Decimal(float), we'd see
        # 19.99999... or similar.
        self.assertEqual(result, Decimal("20.00"))


if __name__ == "__main__":
    unittest.main()
