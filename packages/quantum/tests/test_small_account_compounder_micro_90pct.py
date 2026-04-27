"""Tests for micro-tier sizing per operator spec (2026-04-27).

Spec: micro tier ($0-$1000) uses base_risk_pct=0.90 and max_trades=1.
Score and compounding multipliers bypassed for micro tier; regime_mult
preserved for shock/elevated safety. One position at a time enforced
via tier.max_trades=1 + a concurrency gate in
workflow_orchestrator.run_midday_cycle.

Pre-fix behavior (8% × multipliers, max_trades=4) is preserved in PR
description, commit message, and CLAUDE.md history.
"""

import unittest

from packages.quantum.services.analytics.small_account_compounder import (
    SmallAccountCompounder,
    SizingConfig,
)


class TestMicroTierFlat90Percent(unittest.TestCase):
    """Micro tier returns 90% × regime_mult regardless of score/compounding."""

    def _size(self, score, regime, compounding, capital=500.0):
        tier = SmallAccountCompounder.get_tier(capital)
        return SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": score},
            capital=capital,
            tier=tier,
            regime=regime,
            compounding=compounding,
        )

    def test_normal_regime_score_50_returns_450(self):
        r = self._size(score=50, regime="normal", compounding=True)
        self.assertAlmostEqual(r["risk_pct"], 0.90, places=4)
        self.assertAlmostEqual(r["risk_budget"], 450.0, places=2)

    def test_normal_regime_score_100_does_not_breakaway(self):
        # Pre-fix this would have been 0.90 × 1.20 × 1.0 × 1.2 = 1.296 (129.6%).
        # Post-fix: flat 90%, multipliers bypassed for micro tier.
        r = self._size(score=100, regime="normal", compounding=True)
        self.assertAlmostEqual(r["risk_budget"], 450.0)
        self.assertAlmostEqual(r["multipliers"]["score"], 1.0)
        self.assertAlmostEqual(r["multipliers"]["compounding"], 1.0)

    def test_normal_regime_compounding_off(self):
        # Compounding-off must NOT collapse micro to 2% (operator spec
        # change vs. pre-fix safety override).
        r = self._size(score=85, regime="normal", compounding=False)
        self.assertAlmostEqual(r["risk_budget"], 450.0)

    def test_elevated_regime_returns_360(self):
        r = self._size(score=85, regime="elevated", compounding=True)
        # 0.90 × 0.8 × $500 = $360
        self.assertAlmostEqual(r["risk_budget"], 360.0)

    def test_shock_regime_returns_225(self):
        r = self._size(score=85, regime="shock", compounding=True)
        # 0.90 × 0.5 × $500 = $225 — still trades, just smaller
        self.assertAlmostEqual(r["risk_budget"], 225.0)

    def test_suppressed_regime(self):
        r = self._size(score=85, regime="suppressed", compounding=True)
        # 0.90 × 0.9 × $500 = $405
        self.assertAlmostEqual(r["risk_budget"], 405.0)

    def test_score_irrelevant_within_micro_tier(self):
        budgets = [
            self._size(score=s, regime="normal", compounding=True)["risk_budget"]
            for s in (40, 50, 70, 80, 85, 90, 100)
        ]
        # All should equal $450 — score has no effect at micro tier.
        for b in budgets:
            self.assertAlmostEqual(b, 450.0)


class TestTierBoundaryHardCutoff(unittest.TestCase):
    """Hard cutoff at $1000 — no smooth scale."""

    def test_capital_999_is_micro(self):
        self.assertEqual(SmallAccountCompounder.get_tier(999).name, "micro")

    def test_capital_1000_is_small(self):
        self.assertEqual(SmallAccountCompounder.get_tier(1000).name, "small")

    def test_capital_4999_is_small(self):
        self.assertEqual(SmallAccountCompounder.get_tier(4999).name, "small")

    def test_capital_5000_is_standard(self):
        self.assertEqual(SmallAccountCompounder.get_tier(5000).name, "standard")

    def test_micro_at_999_returns_899(self):
        tier = SmallAccountCompounder.get_tier(999)
        r = SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": 85}, capital=999, tier=tier,
            regime="normal", compounding=True,
        )
        self.assertAlmostEqual(r["risk_budget"], 899.10, places=2)

    def test_small_at_1000_returns_38_88(self):
        # Hard cutoff sanity: $1000 jumps to small tier math.
        # 0.03 × 1.08 × 1.0 × 1.2 = 0.03888 → $38.88
        tier = SmallAccountCompounder.get_tier(1000)
        r = SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": 85}, capital=1000, tier=tier,
            regime="normal", compounding=True,
        )
        self.assertAlmostEqual(r["risk_budget"], 38.88, places=2)


class TestRankAndSelectMicroOneAtATime(unittest.TestCase):
    """rank_and_select with micro tier returns ≤ 1 candidate."""

    def test_returns_at_most_one_micro(self):
        candidates = [
            {"score": 100, "ticker": "AAA"},
            {"score": 95, "ticker": "BBB"},
            {"score": 85, "ticker": "CCC"},
        ]
        selected = SmallAccountCompounder.rank_and_select(
            candidates=candidates,
            capital=500.0,
            risk_budget=450.0,
            config=SizingConfig(compounding_enabled=True),
            regime="normal",
        )
        self.assertLessEqual(len(selected), 1)

    def test_picks_highest_score_first(self):
        candidates = [
            {"score": 75, "ticker": "LOW"},
            {"score": 100, "ticker": "HIGH"},
            {"score": 85, "ticker": "MID"},
        ]
        selected = SmallAccountCompounder.rank_and_select(
            candidates=candidates,
            capital=500.0,
            risk_budget=450.0,
            config=SizingConfig(compounding_enabled=True),
            regime="normal",
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["ticker"], "HIGH")


class TestSmallTierUnchanged(unittest.TestCase):
    """Small tier ($1k-$5k) behavior unchanged by this fix."""

    def test_small_with_compounding_and_high_score(self):
        tier = SmallAccountCompounder.get_tier(2000)
        r = SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": 85}, capital=2000, tier=tier,
            regime="normal", compounding=True,
        )
        # 0.03 × 1.08 × 1.0 × 1.2 = 0.03888 → $77.76
        self.assertAlmostEqual(r["risk_budget"], 77.76, places=2)

    def test_small_compounding_off_collapses_to_2pct(self):
        tier = SmallAccountCompounder.get_tier(2000)
        r = SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": 85}, capital=2000, tier=tier,
            regime="normal", compounding=False,
        )
        # 0.02 × 1.08 × 1.0 × 1.0 = 0.0216 → $43.20
        self.assertAlmostEqual(r["risk_budget"], 43.20, places=2)

    def test_small_max_trades_unchanged(self):
        tier = SmallAccountCompounder.get_tier(2000)
        self.assertEqual(tier.max_trades, 4)


class TestStandardTierUnchanged(unittest.TestCase):
    """Standard tier ($5k+) behavior unchanged by this fix."""

    def test_standard_2pct_balanced(self):
        tier = SmallAccountCompounder.get_tier(10000)
        r = SmallAccountCompounder.calculate_variable_sizing(
            candidate={"score": 85}, capital=10000, tier=tier,
            regime="normal", compounding=True,
        )
        # 0.02 × 1.08 × 1.0 × 1.0 (no compounding boost at standard) = 0.0216 → $216
        self.assertAlmostEqual(r["risk_budget"], 216.0, places=2)

    def test_standard_max_trades_unchanged(self):
        tier = SmallAccountCompounder.get_tier(10000)
        self.assertEqual(tier.max_trades, 5)


if __name__ == "__main__":
    unittest.main()
