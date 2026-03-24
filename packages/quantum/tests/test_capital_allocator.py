"""
Tests for capital allocation layer.

Tests:
1. Basic allocation with default weights
2. Regime adjustment reduces allocation
3. Strategy bucket distribution
4. Symbol concentration caps
5. Candidate score-weighted allocation
6. Performance tilt
7. Policy Lab cohort overrides
8. Edge cases: no capital, fully deployed, no candidates
"""

import pytest

from packages.quantum.allocation.capital_allocator import (
    compute_allocation,
    AllocationPlan,
    StrategyBucket,
    SymbolAllocation,
    DEFAULT_STRATEGY_WEIGHTS,
    _compute_current_exposure,
    _get_regime_cap,
    _compute_strategy_weights,
    _allocate_within_bucket,
    _regime_tilts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _positions(n=2, risk_each=200):
    """Create n open positions with given risk each."""
    return [
        {"symbol": f"SYM{i}", "max_credit": risk_each / 100, "quantity": 1}
        for i in range(n)
    ]


def _candidates(*symbols_scores):
    """Create candidates from (symbol, score) pairs."""
    return [
        {"symbol": sym, "score": score, "strategy": "credit_put_spread"}
        for sym, score in symbols_scores
    ]


# ---------------------------------------------------------------------------
# Basic allocation
# ---------------------------------------------------------------------------

class TestBasicAllocation:
    def test_simple_allocation(self):
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=_candidates(("AAPL", 80), ("MSFT", 70), ("GOOG", 60)),
        )
        assert plan.deployable_capital == 100000
        assert plan.total_allocated > 0
        assert len(plan.strategy_buckets) > 0

    def test_plan_to_dict(self):
        plan = compute_allocation(deployable_capital=50000, regime_label="normal")
        d = plan.to_dict()
        assert "deployable_capital" in d
        assert "strategy_buckets" in d
        assert "symbol_totals" in d

    def test_get_allocation_by_symbol(self):
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=_candidates(("AAPL", 90)),
        )
        alloc = plan.get_allocation("AAPL")
        assert alloc >= 0


# ---------------------------------------------------------------------------
# Regime adjustment
# ---------------------------------------------------------------------------

class TestRegimeAdjustment:
    def test_normal_regime_cap(self):
        cap = _get_regime_cap("normal")
        assert cap == pytest.approx(0.40, abs=0.01)

    def test_shock_regime_much_lower(self):
        cap_normal = _get_regime_cap("normal")
        cap_shock = _get_regime_cap("shock")
        assert cap_shock < cap_normal * 0.5

    def test_v4_vector_overrides_label(self):
        # High vol regime → low cap
        cap = _get_regime_cap("normal", regime_vector={"volatility_regime": 0.9})
        assert cap < 0.10

    def test_v4_low_vol_high_cap(self):
        cap = _get_regime_cap("normal", regime_vector={"volatility_regime": 0.1})
        assert cap > 0.40

    def test_elevated_reduces_allocation(self):
        normal = compute_allocation(100000, regime_label="normal")
        elevated = compute_allocation(100000, regime_label="elevated")
        assert elevated.total_allocated < normal.total_allocated

    def test_shock_minimal_allocation(self):
        plan = compute_allocation(100000, regime_label="shock")
        assert plan.total_allocated < 10000  # Very conservative


# ---------------------------------------------------------------------------
# Strategy bucket distribution
# ---------------------------------------------------------------------------

class TestStrategyBuckets:
    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_STRATEGY_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_buckets_created(self):
        plan = compute_allocation(100000, regime_label="normal")
        assert len(plan.strategy_buckets) == len(DEFAULT_STRATEGY_WEIGHTS)

    def test_regime_tilts_change_weights(self):
        base = DEFAULT_STRATEGY_WEIGHTS.copy()
        tilted = _compute_strategy_weights(base, "elevated")
        # Elevated should increase credit spreads
        assert tilted.get("credit_put_spread", 0) > base.get("credit_put_spread", 0)

    def test_custom_weights(self):
        custom = {"credit_put_spread": 0.5, "iron_condor": 0.5}
        plan = compute_allocation(100000, regime_label="normal", strategy_weights=custom)
        assert len(plan.strategy_buckets) == 2


# ---------------------------------------------------------------------------
# Symbol allocation
# ---------------------------------------------------------------------------

class TestSymbolAllocation:
    def test_score_weighted(self):
        """Higher score should get more allocation."""
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=_candidates(("AAPL", 90), ("MSFT", 30)),
        )
        aapl = plan.get_allocation("AAPL")
        msft = plan.get_allocation("MSFT")
        assert aapl > msft

    def test_concentration_cap(self):
        """Single symbol shouldn't exceed max_symbol_alloc_pct."""
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=_candidates(("AAPL", 100)),
            max_symbol_alloc_pct=0.20,
        )
        assert plan.get_allocation("AAPL") <= 20000

    def test_multiple_symbols_diverse(self):
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=_candidates(("AAPL", 80), ("MSFT", 75), ("GOOG", 70), ("AMZN", 65)),
        )
        assert len(plan.symbol_totals) >= 4


# ---------------------------------------------------------------------------
# Performance tilt
# ---------------------------------------------------------------------------

class TestPerformanceTilt:
    def test_performance_increases_weight(self):
        base = {"credit_put_spread": 0.5, "iron_condor": 0.5}
        # Credit puts performed well
        perf = {"credit_put_spread": 0.8, "iron_condor": -0.2}
        tilted = _compute_strategy_weights(base, "normal", performance=perf)
        assert tilted["credit_put_spread"] > tilted["iron_condor"]


# ---------------------------------------------------------------------------
# Policy Lab integration
# ---------------------------------------------------------------------------

class TestPolicyLabOverrides:
    def test_cohort_custom_weights(self):
        policy = {"strategy_weights": {"credit_put_spread": 0.8, "iron_condor": 0.2}}
        weights = _compute_strategy_weights(
            DEFAULT_STRATEGY_WEIGHTS, "normal", policy_config=policy,
        )
        # Custom weights should dominate
        assert weights["credit_put_spread"] > 0.4


# ---------------------------------------------------------------------------
# Exposure computation
# ---------------------------------------------------------------------------

class TestExposure:
    def test_exposure_from_positions(self):
        positions = _positions(3, risk_each=300)
        exposure = _compute_current_exposure(positions)
        assert exposure == pytest.approx(900, abs=10)

    def test_exposure_subtracts_from_available(self):
        plan = compute_allocation(
            deployable_capital=100000,
            current_positions=_positions(5, risk_each=5000),
            regime_label="normal",
        )
        assert plan.available_capital < 100000
        assert plan.current_exposure > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_capital(self):
        plan = compute_allocation(deployable_capital=0, regime_label="normal")
        assert plan.total_allocated == 0
        assert "no_capital" in plan.diagnostics

    def test_fully_deployed(self):
        plan = compute_allocation(
            deployable_capital=10000,
            current_positions=_positions(5, risk_each=3000),
            regime_label="normal",
        )
        assert plan.total_allocated == 0
        assert "fully_deployed" in plan.diagnostics

    def test_no_candidates(self):
        plan = compute_allocation(
            deployable_capital=100000,
            regime_label="normal",
            candidates=None,
        )
        # Buckets exist but have no symbol allocations
        assert plan.total_allocated > 0
        assert len(plan.symbol_totals) == 0

    def test_within_bucket_empty(self):
        result = _allocate_within_bucket([], 10000, 100000, 0.25)
        assert result == []
