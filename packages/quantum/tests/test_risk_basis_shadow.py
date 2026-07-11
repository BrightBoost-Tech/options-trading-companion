"""P0-B book-scaling — risk-basis persistence + observe-only shadow.

Pins: totals persisted correctly (both structures + partial fill) · legacy NULL
never fabricated · flag-off decisions byte-identical + shadow log fires ·
flag-on honest basis WITHOUT the ×qty double-scaling trap.
"""
import logging
import os
import unittest
from unittest.mock import patch

from packages.quantum.services.risk_basis_shadow import (
    compute_position_risk_basis,
    honest_position_risk,
    choose_basis,
    log_risk_basis_shadow,
    is_max_loss_basis_enabled,
)


def _clear_flag():
    os.environ.pop("RISK_BASIS_MAX_LOSS_ENABLED", None)


# ── write side: compute_position_risk_basis ─────────────────────────────────

class TestComputeRiskBasis(unittest.TestCase):
    def test_debit_full_fill(self):
        # premium 2.00, qty 5, suggestion max_loss_total 1000 over 5 contracts.
        cbt, mlt = compute_position_risk_basis(2.00, 5, 1000.0, 5)
        self.assertEqual(cbt, 1000.0)   # 2.00 × 100 × 5
        self.assertEqual(mlt, 1000.0)   # full-fill: total unchanged

    def test_credit_ic_reuses_suggestion_total(self):
        # a credit IC: premium (cost basis) UNDER-states max loss — that's the point.
        cbt, mlt = compute_position_risk_basis(0.81, 1, 372.0, 1)
        self.assertEqual(cbt, 81.0)     # premium basis (0.81 × 100 × 1)
        self.assertEqual(mlt, 372.0)    # honest defined-risk total

    def test_partial_fill_scales_max_loss(self):
        # suggestion total 1860 over 5 contracts, only 2 filled → 744.
        _, mlt = compute_position_risk_basis(2.0, 2, 1860.0, 5)
        self.assertEqual(mlt, 744.0)

    def test_legacy_no_suggestion_total_is_null(self):
        cbt, mlt = compute_position_risk_basis(1.5, 3, None, None)
        self.assertEqual(cbt, 450.0)    # cost basis always computable
        self.assertIsNone(mlt)          # H9: never fabricated

    def test_unusable_contract_count_is_null(self):
        # can't scale safely → NULL, not a wrong magnitude.
        _, mlt = compute_position_risk_basis(2.0, 5, 1860.0, 0)
        self.assertIsNone(mlt)


# ── units trap: honest_position_risk never × qty ────────────────────────────

class TestUnitsTrap(unittest.TestCase):
    def test_qty_four_position_total_consumed_as_is(self):
        # max_loss_total is ALREADY a total; a qty-4 position must contribute 400,
        # NOT 1600. This is the RBE double-scaling guard.
        self.assertEqual(honest_position_risk({"max_loss_total": 400.0, "quantity": 4}), 400.0)

    def test_missing_is_none(self):
        self.assertIsNone(honest_position_risk({"quantity": 4}))

    def test_object_attr_access(self):
        class _P:
            max_loss_total = 250.0
        self.assertEqual(honest_position_risk(_P()), 250.0)


# ── decision basis: flag off byte-identical, on = honest ────────────────────

class TestChooseBasis(unittest.TestCase):
    def tearDown(self):
        _clear_flag()

    def test_flag_off_returns_current(self):
        _clear_flag()
        self.assertFalse(is_max_loss_basis_enabled())
        self.assertEqual(choose_basis(81.0, 372.0), 81.0)   # byte-identical

    def test_flag_on_returns_honest(self):
        os.environ["RISK_BASIS_MAX_LOSS_ENABLED"] = "1"
        self.assertTrue(is_max_loss_basis_enabled())
        self.assertEqual(choose_basis(81.0, 372.0), 372.0)

    def test_flag_on_null_honest_falls_to_current(self):
        os.environ["RISK_BASIS_MAX_LOSS_ENABLED"] = "1"
        self.assertEqual(choose_basis(81.0, None), 81.0)

    def test_non_one_value_stays_off(self):
        os.environ["RISK_BASIS_MAX_LOSS_ENABLED"] = "true"
        self.assertFalse(is_max_loss_basis_enabled())   # strict '=1'
        self.assertEqual(choose_basis(81.0, 372.0), 81.0)


# ── shadow logging: fires, never raises, null-basis path ────────────────────

class TestShadowLog(unittest.TestCase):
    def test_log_fires_with_both_bases(self):
        with self.assertLogs("packages.quantum.services.risk_basis_shadow", level="INFO") as cm:
            log_risk_basis_shadow("utilization_candidate", 149.0, 372.0, threshold_usd=200.0)
        line = "\n".join(cm.output)
        self.assertIn("[RISK_BASIS_SHADOW]", line)
        self.assertIn("current=149.00", line)
        self.assertIn("honest=372.00", line)
        self.assertIn("would_flip=True", line)   # 149 ≤ 200 < 372

    def test_null_honest_logged_as_legacy(self):
        with self.assertLogs("packages.quantum.services.risk_basis_shadow", level="INFO") as cm:
            log_risk_basis_shadow("allocator_open_book", 0.0, None)
        self.assertIn("basis=null_legacy", "\n".join(cm.output))

    def test_never_raises_on_bad_input(self):
        # must never break a decision path
        log_risk_basis_shadow("x", object(), object())


# ── consumer flag-off byte-identical + shadow fires (utilization) ────────────

class TestUtilizationConsumer(unittest.TestCase):
    def tearDown(self):
        _clear_flag()

    def _sugg(self, limit=0.81, contracts=1, max_loss_total=372.0):
        return {"order_json": {"limit_price": limit, "contracts": contracts},
                "ticker": "QQQ", "max_loss_total": max_loss_total}

    def test_flag_off_returns_premium_and_logs(self):
        from packages.quantum.risk.utilization_gate import candidate_cost_usd
        _clear_flag()
        with self.assertLogs("packages.quantum.services.risk_basis_shadow", level="INFO") as cm:
            cost = candidate_cost_usd(self._sugg())
        self.assertEqual(cost, 81.0)  # premium basis, byte-identical
        self.assertIn("[RISK_BASIS_SHADOW]", "\n".join(cm.output))

    def test_flag_on_returns_honest_max_loss(self):
        from packages.quantum.risk.utilization_gate import candidate_cost_usd
        os.environ["RISK_BASIS_MAX_LOSS_ENABLED"] = "1"
        cost = candidate_cost_usd(self._sugg())
        self.assertEqual(cost, 372.0)  # honest defined-risk basis


if __name__ == "__main__":
    unittest.main()
