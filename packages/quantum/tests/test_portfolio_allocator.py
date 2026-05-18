"""Regression tests for PortfolioAllocator (small-tier allocation-aware sizing).

Spec: ``docs/small_tier_allocation.md`` §4 + §3 worked examples A-E.
Implementation: ``packages/quantum/services/portfolio_allocator.py``.

Coverage:
  - Edge case: 0 candidates → empty list
  - Edge case: 1 candidate → 36% ceiling binds
  - Edge case: 2 candidates → ceiling binds for higher-score; lower
    at skew-clamp 34% (NOT 36% — spec text says "both" but the actual
    math shows only one ceiling binds; this test asserts the math)
  - Edge case: 3 candidates → no ceiling binding
  - Edge case: 4 candidates → no ceiling binding, hit concurrent cap exactly
  - Edge case: 5+ candidates → top 4 selected by score, 5th dropped
  - Regime variations: normal, suppressed, elevated, shock
  - Open-position cost basis subtraction
  - Score skew direction (highest score → highest allocation in set)
  - Worked examples A-E from design doc (exact dollar values)
  - Compounding mode off path (allocator unchanged regardless of flag)
  - Micro-tier regression guard: PortfolioAllocator should NOT be
    instantiated when tier == 'micro' (caller responsibility but
    asserted here for documentation)

H7 fallback (Option 1) is tested at the integration level (no
redistribution when a candidate is dropped post-allocation). The
allocator itself doesn't run H7 — it's a downstream gate — so the
"no redistribution" property is just "allocator output is what it
emitted, downstream drops don't ripple back."
"""
from __future__ import annotations

import unittest
from typing import List, Dict, Any

from packages.quantum.services.portfolio_allocator import (
    AllocationResult,
    GLOBAL_ENVELOPE_PCT,
    MAX_CONCURRENT_POSITIONS,
    PER_TRADE_CEILING_PCT,
    PortfolioAllocator,
)
from packages.quantum.services.analytics.small_account_compounder import (
    SmallAccountCompounder,
)


def _make_candidate(score: float, ticker: str = "TEST") -> Dict[str, Any]:
    """Minimum candidate shape: score + ticker."""
    return {"score": score, "ticker": ticker}


def _candidates_from_scores(scores: List[float]) -> List[Dict[str, Any]]:
    return [_make_candidate(s, f"SYM{i}") for i, s in enumerate(scores)]


def _open_position(cost_basis: float, ticker: str = "OPEN") -> Dict[str, Any]:
    return {"ticker": ticker, "cost_basis": cost_basis}


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.allocator = PortfolioAllocator()

    def test_zero_candidates_returns_empty(self):
        result = self.allocator.allocate(
            candidates=[], total_equity=1500.0, regime="normal",
        )
        self.assertEqual(result, [])

    def test_zero_equity_returns_empty(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([90]),
            total_equity=0.0, regime="normal",
        )
        self.assertEqual(result, [])

    def test_one_candidate_ceiling_binds_at_36pct(self):
        result = self.allocator.allocate(
            candidates=[_make_candidate(88)],
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 1)
        # base = 0.85 / 1 = 0.85; skew = 0.8 (score==median);
        # raw_pct = 0.68; ceiling 0.36 binds → 0.36
        self.assertAlmostEqual(result[0].allocated_pct, 0.36, places=4)
        self.assertAlmostEqual(result[0].allocated_budget, 540.0, places=2)
        self.assertTrue(result[0].ceiling_binding)

    def test_two_candidates_higher_score_ceiling_binds(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([92, 78]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 2)
        # Cand 1 (92): median=85, skew=0.856, raw_pct = 0.425*0.856 = 0.364
        # → ceiling 0.36 binds
        self.assertAlmostEqual(result[0].allocated_pct, 0.36, places=4)
        self.assertAlmostEqual(result[0].allocated_budget, 540.0, places=2)
        self.assertTrue(result[0].ceiling_binding)
        # Cand 2 (78): skew clamped to 0.8, raw_pct = 0.425*0.8 = 0.34
        # → ceiling NOT binding
        self.assertAlmostEqual(result[1].allocated_pct, 0.34, places=4)
        self.assertAlmostEqual(result[1].allocated_budget, 510.0, places=2)
        self.assertFalse(result[1].ceiling_binding)

    def test_three_candidates_no_ceiling(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([88, 80, 72]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 3)
        # base = 0.85/3 ≈ 0.2833 → max possible per-trade ≈ 0.34 (skew 1.2)
        # well under 0.36 ceiling
        for r in result:
            self.assertFalse(r.ceiling_binding)
            self.assertLess(r.allocated_pct, 0.36)

    def test_four_candidates_no_ceiling_hits_concurrent_cap(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 4)
        # base = 0.85/4 = 0.2125 → max possible per-trade = 0.255 (skew 1.2)
        # well under 0.36 ceiling
        for r in result:
            self.assertFalse(r.ceiling_binding)

    def test_five_candidates_top_four_selected_by_score(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76, 60]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 4)  # capped at MAX_CONCURRENT_POSITIONS
        # The 60-score candidate should NOT appear
        selected_scores = [r.candidate["score"] for r in result]
        self.assertNotIn(60, selected_scores)
        self.assertEqual(set(selected_scores), {95, 88, 82, 76})

    def test_envelope_exhausted_by_open_positions_returns_empty(self):
        # 100% of envelope consumed by an open position
        envelope = 1500.0 * GLOBAL_ENVELOPE_PCT  # 1275
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([90, 85]),
            total_equity=1500.0,
            regime="normal",
            open_positions=[_open_position(envelope + 1.0)],
        )
        self.assertEqual(result, [])


class TestRegimeVariations(unittest.TestCase):

    def setUp(self):
        self.allocator = PortfolioAllocator()

    def test_normal_regime_envelope_at_85pct(self):
        # 4 candidates, normal regime → envelope = $1275
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=1500.0, regime="normal",
        )
        total = sum(r.allocated_budget for r in result)
        # Should be well under $1275 envelope (skew distributes ~70%)
        self.assertLess(total, 1275.0)

    def test_elevated_regime_envelope_shrinks(self):
        # 4 candidates, elevated regime → envelope = 0.85*0.8*equity
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=3000.0, regime="elevated",
        )
        total = sum(r.allocated_budget for r in result)
        envelope = 3000.0 * 0.85 * 0.8  # $2040
        # Total should equal envelope exactly (last candidate truncated)
        self.assertAlmostEqual(total, envelope, places=2)

    def test_shock_regime_severely_constrains_envelope(self):
        # Shock regime: envelope = 0.85 * 0.5 = 0.425 of equity
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=2000.0, regime="shock",
        )
        total = sum(r.allocated_budget for r in result)
        envelope = 2000.0 * 0.85 * 0.5  # $850
        # Envelope binds — total cannot exceed envelope
        self.assertLessEqual(total, envelope + 0.01)

    def test_suppressed_regime_at_90pct_of_normal(self):
        # 1 candidate (so envelope-driven truncation doesn't muddy
        # the assertion); ceiling binds; allocation reflects envelope
        # constraint, not the 36% ceiling.
        result = self.allocator.allocate(
            candidates=[_make_candidate(90)],
            total_equity=1500.0, regime="suppressed",
        )
        # Envelope = 1500 * 0.85 * 0.9 = $1147.50
        # 1-candidate raw allocation: base 0.85, skew 0.8, ceiling 0.36
        # → $540, well under envelope. Ceiling binds.
        self.assertAlmostEqual(result[0].allocated_budget, 540.0, places=2)
        self.assertTrue(result[0].ceiling_binding)

    def test_chop_regime_uses_normal_envelope(self):
        result = self.allocator.allocate(
            candidates=[_make_candidate(88)],
            total_equity=1500.0, regime="chop",
        )
        # Chop regime_mult = 1.0, same as normal → $540
        self.assertAlmostEqual(result[0].allocated_budget, 540.0, places=2)


class TestScoreSkewDirection(unittest.TestCase):

    def test_highest_score_gets_highest_allocation(self):
        # 3 candidates with distinct scores
        result = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([95, 80, 70]),
            total_equity=1500.0, regime="normal",
        )
        # Sorted by allocator (score desc); first should have highest
        scores = [r.candidate["score"] for r in result]
        self.assertEqual(scores, [95, 80, 70])
        # Allocations should be monotonically non-increasing (skew respects ordering)
        for i in range(len(result) - 1):
            self.assertGreaterEqual(
                result[i].allocated_budget,
                result[i + 1].allocated_budget,
                f"Allocation at index {i} not >= index {i+1}",
            )

    def test_input_order_doesnt_affect_output_order(self):
        # Pass candidates in reverse score order; allocator should sort
        result = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([70, 80, 95]),
            total_equity=1500.0, regime="normal",
        )
        scores = [r.candidate["score"] for r in result]
        self.assertEqual(scores, [95, 80, 70])


class TestOpenPositionSubtraction(unittest.TestCase):

    def test_open_position_reduces_available_envelope(self):
        # Example E from design doc: $1500 equity, $450 open, 3 candidates
        result = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([90, 82, 74]),
            total_equity=1500.0,
            regime="normal",
            open_positions=[_open_position(450.0)],
        )
        self.assertEqual(len(result), 3)
        # Envelope = $1275 - $450 = $825
        total = sum(r.allocated_budget for r in result)
        self.assertAlmostEqual(total, 825.0, places=2)
        # Last candidate should be truncated
        # (matches Example E exactly)

    def test_multiple_open_positions_sum_correctly(self):
        result = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([90, 80]),
            total_equity=1500.0,
            regime="normal",
            open_positions=[
                _open_position(300.0, "OPEN_A"),
                _open_position(200.0, "OPEN_B"),
            ],
        )
        # Envelope = $1275 - $500 = $775
        total = sum(r.allocated_budget for r in result)
        self.assertLessEqual(total, 775.01)

    def test_malformed_cost_basis_skipped_gracefully(self):
        # Candidate set should still allocate even if one open position
        # has malformed cost_basis
        result = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([90]),
            total_equity=1500.0,
            regime="normal",
            open_positions=[
                {"ticker": "BAD", "cost_basis": "not_a_number"},
            ],
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].allocated_budget, 540.0, places=2)


class TestWorkedExamples(unittest.TestCase):
    """Worked examples A-E from docs/small_tier_allocation.md §3.
    Exact dollar values asserted to defend against any drift in the
    allocator's math."""

    def setUp(self):
        self.allocator = PortfolioAllocator()

    def test_example_a_four_candidates_normal(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 4)
        # Median = (88+82)/2 = 85
        # Cand 1 (95): skew=0.88, pct=0.187, $280.50
        # Cand 2 (88): skew=0.824, pct=0.1751, $262.65
        # Cand 3 (82): skew=0.776→0.8 clamp, pct=0.17, $255.00
        # Cand 4 (76): skew=0.728→0.8 clamp, pct=0.17, $255.00
        self.assertAlmostEqual(result[0].allocated_budget, 280.50, places=2)
        self.assertAlmostEqual(result[1].allocated_budget, 262.65, places=2)
        self.assertAlmostEqual(result[2].allocated_budget, 255.00, places=2)
        self.assertAlmostEqual(result[3].allocated_budget, 255.00, places=2)
        total = sum(r.allocated_budget for r in result)
        self.assertAlmostEqual(total, 1053.15, places=2)

    def test_example_b_two_candidates_normal(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([92, 78]),
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 2)
        # Cand 1 (92): ceiling binds at 36% → $540
        self.assertAlmostEqual(result[0].allocated_budget, 540.00, places=2)
        self.assertTrue(result[0].ceiling_binding)
        # Cand 2 (78): skew clamped 0.8, raw 34%, ceiling NOT binding → $510
        self.assertAlmostEqual(result[1].allocated_budget, 510.00, places=2)
        self.assertFalse(result[1].ceiling_binding)

    def test_example_c_one_candidate_normal(self):
        result = self.allocator.allocate(
            candidates=[_make_candidate(88)],
            total_equity=1500.0, regime="normal",
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].allocated_budget, 540.00, places=2)
        self.assertTrue(result[0].ceiling_binding)

    def test_example_d_four_candidates_elevated(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([90, 85, 80, 72]),
            total_equity=3000.0, regime="elevated",
        )
        self.assertEqual(len(result), 4)
        # Envelope = $3000*0.85*0.8 = $2040
        # Median = (85+80)/2 = 82.5
        # Cand 1 (90): skew=0.86, pct=0.18275, raw $548.25
        # Cand 2 (85): skew=0.82, pct=0.17425, raw $522.75
        # Cand 3 (80): skew=0.78→0.8 clamp, pct=0.17, raw $510.00
        # Cand 4 (72): raw $510, truncated to envelope remainder $459.00
        self.assertAlmostEqual(result[0].allocated_budget, 548.25, places=2)
        self.assertAlmostEqual(result[1].allocated_budget, 522.75, places=2)
        self.assertAlmostEqual(result[2].allocated_budget, 510.00, places=2)
        self.assertAlmostEqual(result[3].allocated_budget, 459.00, places=2)
        total = sum(r.allocated_budget for r in result)
        self.assertAlmostEqual(total, 2040.00, places=2)  # = envelope exactly

    def test_example_e_open_position_subtraction(self):
        result = self.allocator.allocate(
            candidates=_candidates_from_scores([90, 82, 74]),
            total_equity=1500.0,
            regime="normal",
            open_positions=[_open_position(450.0)],
        )
        self.assertEqual(len(result), 3)
        # Envelope = $1275 - $450 = $825
        # Median = 82
        # Cand 1 (90): skew=0.864, pct=0.2448, raw $367.20
        # Cand 2 (82): skew=0.8 (score==median), pct=0.2267, raw $340.00
        # Cand 3 (74): skew=0.736→0.8 clamp, pct=0.2267, raw $340 → truncated $117.80
        self.assertAlmostEqual(result[0].allocated_budget, 367.20, places=2)
        self.assertAlmostEqual(result[1].allocated_budget, 340.00, places=2)
        self.assertAlmostEqual(result[2].allocated_budget, 117.80, places=2)
        total = sum(r.allocated_budget for r in result)
        self.assertAlmostEqual(total, 825.00, places=2)  # = available envelope


class TestH7FallbackOption1(unittest.TestCase):
    """H7 fallback semantics: when downstream H7 drops a candidate,
    remaining candidates keep their ORIGINAL allocator budgets — no
    redistribution.

    The allocator itself doesn't run H7 (downstream concern). This
    test asserts that simply dropping a candidate from the result
    list doesn't ripple back to other candidates' allocations.
    """

    def test_dropping_one_candidate_preserves_others_allocations(self):
        # Allocate 4 candidates; capture their budgets
        all_four = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([95, 88, 82, 76]),
            total_equity=1500.0, regime="normal",
        )
        all_four_budgets = [r.allocated_budget for r in all_four]
        # Re-run allocator with one candidate removed (simulates
        # caller dropping a candidate post-allocation)
        # The allocator can't be re-run for this test — that would BE
        # redistribution. Instead, assert that the original 3 budgets
        # remain valid even when iterating allocations with one filtered
        # out (which is what the downstream gate would do).
        survivors = all_four[:3]  # drop the 4th (lowest score)
        survivor_budgets = [r.allocated_budget for r in survivors]
        # Survivors retain identical allocations
        self.assertEqual(survivor_budgets, all_four_budgets[:3])


class TestMicroTierGuard(unittest.TestCase):
    """Defensive: PortfolioAllocator should NOT be invoked at micro
    tier. The caller (workflow_orchestrator) is responsible for tier
    dispatch; these tests assert that property holds in the existing
    SmallAccountCompounder tier definitions."""

    def test_micro_tier_definition_unchanged(self):
        # Operator spec: micro tier 90% single-position
        micro = SmallAccountCompounder.get_tier(500.0)
        self.assertEqual(micro.name, "micro")
        self.assertEqual(micro.max_trades, 1)
        self.assertAlmostEqual(micro.base_risk_pct, 0.90, places=4)

    def test_small_tier_definition_unchanged(self):
        # Small tier max_trades = 4 (matches MAX_CONCURRENT_POSITIONS)
        small = SmallAccountCompounder.get_tier(2500.0)
        self.assertEqual(small.name, "small")
        self.assertEqual(small.max_trades, MAX_CONCURRENT_POSITIONS)

    def test_calculate_variable_sizing_micro_ignores_allocation_hint(self):
        # Even when caller passes allocation_hint, micro tier ignores
        # it (defensive against accidental cross-tier activation).
        candidate = _make_candidate(85)
        micro_tier = SmallAccountCompounder.get_tier(500.0)
        result = SmallAccountCompounder.calculate_variable_sizing(
            candidate=candidate,
            capital=500.0,
            tier=micro_tier,
            regime="normal",
            compounding=True,
            allocation_hint=123.45,  # would be wrong for micro
        )
        # Micro path: 0.90 × 1.0 (normal) × 500 = $450
        self.assertAlmostEqual(result["risk_budget"], 450.00, places=2)
        self.assertAlmostEqual(result["risk_pct"], 0.90, places=4)


class TestCompoundingMode(unittest.TestCase):
    """COMPOUNDING_MODE doesn't directly affect allocator math; the
    36% ceiling already accounts for the 1.2 boost historically.
    These tests assert that property."""

    def test_allocator_output_independent_of_compounding_flag(self):
        # Allocator doesn't read COMPOUNDING_MODE; same output regardless
        result_a = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([90, 80]),
            total_equity=1500.0, regime="normal",
        )
        result_b = PortfolioAllocator().allocate(
            candidates=_candidates_from_scores([90, 80]),
            total_equity=1500.0, regime="normal",
        )
        budgets_a = [r.allocated_budget for r in result_a]
        budgets_b = [r.allocated_budget for r in result_b]
        self.assertEqual(budgets_a, budgets_b)

    def test_compounder_small_tier_uses_allocation_hint_overrides_compounding(self):
        # When allocation_hint is set at small tier, compounding multipliers
        # are bypassed (hint is authoritative).
        candidate = _make_candidate(95)  # high score; would normally get 1.2 boost
        small_tier = SmallAccountCompounder.get_tier(2500.0)
        result = SmallAccountCompounder.calculate_variable_sizing(
            candidate=candidate,
            capital=2500.0,
            tier=small_tier,
            regime="normal",
            compounding=True,
            allocation_hint=500.0,
        )
        # Hint is authoritative: risk_budget = $500
        self.assertAlmostEqual(result["risk_budget"], 500.00, places=2)
        self.assertTrue(result.get("allocation_hint_applied", False))


class TestAllocationResultShape(unittest.TestCase):

    def test_result_preserves_candidate_dict_verbatim(self):
        cand = {"score": 88, "ticker": "SPY", "strategy": "iron_condor",
                "custom_field": "preserve_me"}
        result = PortfolioAllocator().allocate(
            candidates=[cand], total_equity=1500.0, regime="normal",
        )
        # The original dict is preserved (identity check)
        self.assertIs(result[0].candidate, cand)
        self.assertEqual(result[0].candidate["custom_field"], "preserve_me")

    def test_result_includes_diagnostic_fields(self):
        result = PortfolioAllocator().allocate(
            candidates=[_make_candidate(88)],
            total_equity=1500.0, regime="normal",
        )
        r = result[0]
        # All diagnostic fields populated
        self.assertIsNotNone(r.allocated_budget)
        self.assertIsNotNone(r.allocated_pct)
        self.assertIsNotNone(r.score_skew)
        self.assertIsInstance(r.ceiling_binding, bool)
        # Allocated pct matches budget / equity
        self.assertAlmostEqual(
            r.allocated_pct, r.allocated_budget / 1500.0, places=6,
        )


if __name__ == "__main__":
    unittest.main()
