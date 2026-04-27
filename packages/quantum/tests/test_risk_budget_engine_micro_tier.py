"""Tests for tier-aware RiskBudgetEngine per operator spec (2026-04-27).

Verifies:
  - Micro tier ($0-$1000): max_risk_per_trade and global_alloc.max
    both = capital × 0.90 × regime_mult.
  - Small/standard tiers: existing risk_profile-based behavior preserved.
  - Hard cutoff at $1000 (no smooth scale).
  - STRATEGY_TRACK env value does NOT influence micro tier sizing
    (engine bypasses risk_profile branch for micro).

Source-level structural assertions where engine instantiation requires
heavy dependency stubbing.
"""

import os
import unittest
from unittest.mock import MagicMock

from packages.quantum.services.risk_budget_engine import (
    RiskBudgetEngine,
    RegimeState,
)


class _MockSupabase:
    """Minimal supabase stub for RiskBudgetEngine.compute()."""

    def __init__(self):
        self.table_mock = MagicMock()

    def table(self, name):
        return self.table_mock


def _compute(capital, regime=RegimeState.NORMAL, risk_profile="balanced",
             positions=None):
    engine = RiskBudgetEngine(_MockSupabase())
    return engine.compute(
        user_id="test-user",
        deployable_capital=capital,
        regime_input=regime,
        positions=positions or [],
        risk_profile=risk_profile,
    )


class TestMicroTierBudget(unittest.TestCase):
    """Micro tier budget = capital × 0.90 × regime_mult, no profile mult."""

    def test_micro_normal_balanced(self):
        report = _compute(capital=500.0, regime=RegimeState.NORMAL)
        self.assertAlmostEqual(report.max_risk_per_trade, 450.0, places=2)
        self.assertAlmostEqual(report.global_allocation.max_limit, 450.0, places=2)
        self.assertIn("micro_tier_active", report.diagnostics)
        self.assertIn("micro_tier_global_alloc", report.diagnostics)

    def test_micro_elevated_regime(self):
        report = _compute(capital=500.0, regime=RegimeState.ELEVATED)
        # 0.90 × 0.8 × $500 = $360
        self.assertAlmostEqual(report.max_risk_per_trade, 360.0, places=2)
        self.assertAlmostEqual(report.global_allocation.max_limit, 360.0, places=2)

    def test_micro_shock_regime(self):
        report = _compute(capital=500.0, regime=RegimeState.SHOCK)
        # 0.90 × 0.5 × $500 = $225
        self.assertAlmostEqual(report.max_risk_per_trade, 225.0, places=2)

    def test_micro_999_returns_899(self):
        report = _compute(capital=999.0, regime=RegimeState.NORMAL)
        self.assertAlmostEqual(report.max_risk_per_trade, 899.10, places=2)


class TestMicroTierStrategyTrackIndependence(unittest.TestCase):
    """Regression guard: STRATEGY_TRACK does not affect micro tier sizing."""

    def test_balanced_yields_450(self):
        report = _compute(capital=500.0, risk_profile="balanced")
        self.assertAlmostEqual(report.max_risk_per_trade, 450.0)

    def test_aggressive_yields_450(self):
        # Pre-fix: 0.05 × $500 = $25. Post-fix: micro tier ignores profile.
        report = _compute(capital=500.0, risk_profile="aggressive")
        self.assertAlmostEqual(report.max_risk_per_trade, 450.0)

    def test_conservative_yields_450(self):
        # Pre-fix: 0.02 × $500 = $10. Post-fix: micro tier ignores profile.
        report = _compute(capital=500.0, risk_profile="conservative")
        self.assertAlmostEqual(report.max_risk_per_trade, 450.0)


class TestSmallTierUnchanged(unittest.TestCase):
    """Small tier ($1k-$5k) preserves existing risk_profile-based behavior."""

    def test_small_balanced(self):
        # 0.03 × $2000 = $60. global_max stays at total_equity × 0.40 = $800
        # for NORMAL regime (small/standard tier path).
        report = _compute(capital=2000.0, risk_profile="balanced")
        self.assertAlmostEqual(report.max_risk_per_trade, 60.0, places=2)
        self.assertAlmostEqual(report.global_allocation.max_limit, 800.0, places=2)
        self.assertNotIn("micro_tier_active", report.diagnostics)

    def test_small_aggressive(self):
        # 0.05 × $2000 = $100
        report = _compute(capital=2000.0, risk_profile="aggressive")
        self.assertAlmostEqual(report.max_risk_per_trade, 100.0, places=2)


class TestStandardTierUnchanged(unittest.TestCase):
    """Standard tier ($5k+) preserves existing behavior."""

    def test_standard_balanced(self):
        # 0.03 × $10000 = $300
        report = _compute(capital=10000.0, risk_profile="balanced")
        self.assertAlmostEqual(report.max_risk_per_trade, 300.0, places=2)
        # global_max = total_equity × 0.40 = $4000 (NORMAL regime)
        self.assertAlmostEqual(report.global_allocation.max_limit, 4000.0, places=2)

    def test_standard_aggressive(self):
        # 0.05 × $10000 = $500
        report = _compute(capital=10000.0, risk_profile="aggressive")
        self.assertAlmostEqual(report.max_risk_per_trade, 500.0, places=2)


class TestHardCutoffAt1000(unittest.TestCase):
    """No smooth interpolation between $999 (micro) and $1000 (small)."""

    def test_999_is_micro(self):
        report = _compute(capital=999.0)
        self.assertIn("micro_tier_active", report.diagnostics)
        self.assertAlmostEqual(report.max_risk_per_trade, 899.10, places=2)

    def test_1000_is_small(self):
        report = _compute(capital=1000.0)
        self.assertNotIn("micro_tier_active", report.diagnostics)
        # 0.03 × $1000 = $30
        self.assertAlmostEqual(report.max_risk_per_trade, 30.0, places=2)

    def test_jump_at_boundary(self):
        # $899 vs $30 — a 30× drop at the $1 boundary. Operator-confirmed
        # hard cutoff (no interpolation).
        micro = _compute(capital=999.0).max_risk_per_trade
        small = _compute(capital=1000.0).max_risk_per_trade
        self.assertGreater(micro / max(small, 0.01), 25.0)


if __name__ == "__main__":
    unittest.main()
