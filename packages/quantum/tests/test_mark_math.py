"""Unit tests for the shared full-count mark math (risk.mark_math, #3).

Both mark readers route through compute_current_value + finalize_mark, so these
pin the single source of truth: full-count leg sum, P&L scaled exactly once,
F-shape → +$30 (the value the intraday path used to double-count to +$2,070).
"""

import unittest

from packages.quantum.risk.mark_math import compute_current_value, finalize_mark


class TestFinalizeMark(unittest.TestCase):
    def test_f_shape_debit_plus_30(self):
        # F bdbe4d04: 5 contracts, entry 0.96, current spread net 1.02.
        # current_value (total) = 1.02 * 100 * 5 = 510; entry = 0.96 * 5 * 100 = 480.
        mark, upl = finalize_mark(5, 0.96, 510.0)
        self.assertAlmostEqual(mark, 1.02, places=4)
        self.assertAlmostEqual(upl, 30.0, places=2)

    def test_debit_loss_scaled_once(self):
        # 4 contracts, entry 2.50, current total 880 (=2.20*100*4) → -120.
        mark, upl = finalize_mark(4, 2.50, 880.0)
        self.assertAlmostEqual(mark, 2.20, places=4)
        self.assertAlmostEqual(upl, -120.0, places=2)

    def test_credit_sign(self):
        # qty=-4, entry 0.50 credit, current_value -120 → entry-|cur| = 200-120 = 80.
        mark, upl = finalize_mark(-4, 0.50, -120.0)
        self.assertAlmostEqual(upl, 80.0, places=2)
        self.assertAlmostEqual(mark, -0.30, places=4)

    def test_qty_zero_collapses_to_zero(self):
        mark, upl = finalize_mark(0, 2.50, 220.0)
        self.assertEqual(mark, 0.0)
        self.assertEqual(upl, 0.0)


class TestComputeCurrentValue(unittest.TestCase):
    def _legs(self, q=5):
        return [
            {"action": "buy", "symbol": "O:F260626C00015500", "quantity": q},
            {"action": "sell", "symbol": "O:F260626C00017500", "quantity": q},
        ]

    def test_full_count_total_value(self):
        mids = {"O:F260626C00015500": 1.10, "O:F260626C00017500": 0.08}
        cv = compute_current_value(self._legs(5), lambda s: mids.get(s), 5)
        # (1.10*100*5) - (0.08*100*5) = 550 - 40 = 510
        self.assertAlmostEqual(cv, 510.0, places=2)
        # end-to-end → +30
        _, upl = finalize_mark(5, 0.96, cv)
        self.assertAlmostEqual(upl, 30.0, places=2)

    def test_unpriced_leg_returns_none_and_records_failure(self):
        mids = {"O:F260626C00015500": 1.10}  # second leg missing
        failed = []
        cv = compute_current_value(self._legs(5), lambda s: mids.get(s), 5, failed_legs=failed)
        self.assertIsNone(cv)
        self.assertIn("O:F260626C00017500", failed)

    def test_leg_qty_falls_back_to_pos_quantity(self):
        legs = [
            {"action": "buy", "symbol": "A", "quantity": None},
            {"action": "sell", "symbol": "B", "quantity": None},
        ]
        cv = compute_current_value(legs, lambda s: 1.0 if s == "A" else 0.4, 3)
        # (1.0*100*3) - (0.4*100*3) = 300 - 120 = 180
        self.assertAlmostEqual(cv, 180.0, places=2)

    def test_empty_legs_returns_none(self):
        self.assertIsNone(compute_current_value([], lambda s: 1.0, 5))


if __name__ == "__main__":
    unittest.main()
