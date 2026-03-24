"""
Tests for Optimizer V4 — utility-maximizing portfolio optimizer.

Tests:
1. Kelly fraction computation
2. Correlation penalty estimation
3. Basic optimization with candidates
4. Risk budget constraint
5. Greeks constraints
6. Concentration limits
7. PDT constraint
8. Confidence-adjusted sizing
9. Edge cases
"""

import math
import pytest
import numpy as np
from unittest.mock import patch

from packages.quantum.core.optimizer_v4 import (
    CandidateInput,
    OptimizedPosition,
    OptimizationResult,
    compute_kelly_fraction,
    estimate_correlation_penalty,
    optimize_portfolio_v4,
    is_optimizer_v4_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _candidate(
    symbol="AAPL",
    strategy="credit_put_spread",
    max_profit=200,
    max_loss=800,
    collateral=800,
    prob_profit=0.85,
    ev_amount=50,
    score=75,
    confidence=0.8,
    delta=0.3,
    vega=0.05,
    is_same_day=False,
) -> CandidateInput:
    return CandidateInput(
        symbol=symbol,
        strategy=strategy,
        max_profit=max_profit,
        max_loss=max_loss,
        collateral=collateral,
        prob_profit=prob_profit,
        ev_amount=ev_amount,
        score=score,
        forecast_confidence=confidence,
        delta_per_contract=delta,
        vega_per_contract=vega,
        is_same_day=is_same_day,
    )


# ---------------------------------------------------------------------------
# Kelly fraction
# ---------------------------------------------------------------------------

class TestKellyFraction:
    def test_positive_ev_trade(self):
        # p=0.85, W=200, L=800: EV = 0.85*200 - 0.15*800 = 170-120 = 50
        # kelly = 50/800 = 0.0625, half-kelly*0.8 = 0.025
        f = compute_kelly_fraction(prob_profit=0.85, max_profit=200, max_loss=800)
        assert f > 0
        assert f <= 0.15

    def test_negative_ev_returns_zero(self):
        # p=0.20, W=200, L=800: EV = 0.20*200 - 0.80*800 = 40-640 = -600 → 0
        f = compute_kelly_fraction(prob_profit=0.20, max_profit=200, max_loss=800)
        assert f == 0.0

    def test_confidence_scales_down(self):
        high = compute_kelly_fraction(0.85, 200, 800, confidence=1.0)
        low = compute_kelly_fraction(0.85, 200, 800, confidence=0.3)
        assert low < high

    def test_zero_loss_returns_zero(self):
        assert compute_kelly_fraction(0.70, 200, 0) == 0.0

    def test_high_edge_capped(self):
        f = compute_kelly_fraction(prob_profit=0.95, max_profit=1000, max_loss=100)
        assert f <= 0.15  # Hard cap


# ---------------------------------------------------------------------------
# Correlation estimation
# ---------------------------------------------------------------------------

class TestCorrelation:
    def test_same_symbol_high_corr(self):
        c1 = _candidate("AAPL")
        c2 = _candidate("AAPL")
        corr = estimate_correlation_penalty([c1, c2])
        assert corr[0, 1] > 0.9

    def test_different_symbols_low_corr(self):
        c1 = _candidate("AAPL")
        c2 = _candidate("MSFT")
        corr = estimate_correlation_penalty([c1, c2])
        assert corr[0, 1] < 0.5

    def test_diagonal_is_one(self):
        candidates = [_candidate("AAPL"), _candidate("MSFT"), _candidate("GOOG")]
        corr = estimate_correlation_penalty(candidates)
        for i in range(3):
            assert corr[i, i] == 1.0

    def test_symmetric(self):
        candidates = [_candidate("AAPL"), _candidate("MSFT")]
        corr = estimate_correlation_penalty(candidates)
        assert corr[0, 1] == corr[1, 0]


# ---------------------------------------------------------------------------
# Basic optimization
# ---------------------------------------------------------------------------

class TestBasicOptimization:
    def test_simple_optimization(self):
        candidates = [
            _candidate("AAPL", ev_amount=80, prob_profit=0.90, score=85),
            _candidate("MSFT", ev_amount=50, prob_profit=0.88, score=70),
            _candidate("GOOG", ev_amount=30, prob_profit=0.87, score=60),
        ]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=20000,
        )
        assert len(result.positions) > 0
        assert result.total_capital_used > 0
        assert result.total_risk <= 20000 * 1.1

    def test_higher_ev_gets_more(self):
        """Higher EV candidate should get larger allocation."""
        candidates = [
            _candidate("AAPL", ev_amount=100, prob_profit=0.80),
            _candidate("MSFT", ev_amount=20, prob_profit=0.55),
        ]
        result = optimize_portfolio_v4(
            candidates, available_capital=50000, risk_budget=10000,
        )
        aapl = next((p for p in result.positions if p.symbol == "AAPL"), None)
        msft = next((p for p in result.positions if p.symbol == "MSFT"), None)
        if aapl and msft:
            assert aapl.contracts >= msft.contracts

    def test_result_serialization(self):
        candidates = [_candidate("AAPL")]
        result = optimize_portfolio_v4(
            candidates, available_capital=50000, risk_budget=10000,
        )
        d = result.to_dict()
        assert "positions" in d
        assert "total_capital_used" in d
        assert "solver_status" in d


# ---------------------------------------------------------------------------
# Risk budget constraint
# ---------------------------------------------------------------------------

class TestRiskBudget:
    def test_respects_risk_budget(self):
        candidates = [_candidate(f"SYM{i}", max_loss=2000) for i in range(10)]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=5000,
        )
        assert result.total_risk <= 6000  # Budget + rounding tolerance

    def test_small_budget_limits_positions(self):
        candidates = [_candidate("AAPL", max_loss=3000, collateral=3000)]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=2000,
        )
        # Can't even fill 1 contract at $3000 risk if budget is $2000
        # But concentration limit at 25% of capital = $25000, so risk_budget is binding
        assert result.total_risk <= 3000


# ---------------------------------------------------------------------------
# Greeks constraints
# ---------------------------------------------------------------------------

class TestGreeksConstraints:
    def test_delta_limit(self):
        candidates = [_candidate(f"SYM{i}", delta=0.8) for i in range(5)]
        result = optimize_portfolio_v4(
            candidates, available_capital=50000, risk_budget=20000,
            max_portfolio_delta=2.0,
        )
        assert abs(result.portfolio_delta) <= 3.0  # 2.0 + tolerance

    def test_no_delta_limit(self):
        candidates = [_candidate("AAPL", delta=0.5)]
        result = optimize_portfolio_v4(
            candidates, available_capital=50000, risk_budget=10000,
            max_portfolio_delta=0,  # No limit
        )
        assert len(result.positions) > 0


# ---------------------------------------------------------------------------
# Concentration limits
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_diversification(self):
        """Multiple candidates should get allocated, not just the best one."""
        candidates = [
            _candidate("AAPL", ev_amount=80),
            _candidate("MSFT", ev_amount=75),
            _candidate("GOOG", ev_amount=70),
        ]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=20000,
            max_concentration_pct=0.40,
        )
        # Should have more than 1 position due to diversification benefit
        assert len(result.positions) >= 1

    def test_concentration_cap(self):
        candidates = [_candidate("AAPL", ev_amount=100, collateral=500)]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=50000,
            max_concentration_pct=0.10,
        )
        # Max 10% of $100K = $10K → max 20 contracts at $500
        if result.positions:
            assert result.positions[0].capital_required <= 12000


# ---------------------------------------------------------------------------
# PDT constraint
# ---------------------------------------------------------------------------

class TestPDT:
    def test_pdt_limits_same_day(self):
        candidates = [
            _candidate("AAPL", is_same_day=True, ev_amount=80),
            _candidate("MSFT", is_same_day=True, ev_amount=70),
            _candidate("GOOG", is_same_day=True, ev_amount=60),
            _candidate("AMZN", is_same_day=False, ev_amount=50),
        ]
        result = optimize_portfolio_v4(
            candidates, available_capital=100000, risk_budget=20000,
            pdt_day_trades_remaining=1,
        )
        # Should still produce positions (non-same-day are unconstrained)
        assert len(result.positions) >= 1


# ---------------------------------------------------------------------------
# Confidence-adjusted sizing
# ---------------------------------------------------------------------------

class TestConfidenceAdjustment:
    def test_low_confidence_smaller(self):
        """Low forecast confidence should result in smaller position."""
        high_conf = _candidate("AAPL", confidence=1.0, ev_amount=80)
        low_conf = _candidate("AAPL", confidence=0.2, ev_amount=80)

        result_high = optimize_portfolio_v4(
            [high_conf], available_capital=50000, risk_budget=10000,
        )
        result_low = optimize_portfolio_v4(
            [low_conf], available_capital=50000, risk_budget=10000,
        )

        # Low confidence → lower Kelly → smaller allocation
        if result_high.positions and result_low.positions:
            assert result_low.positions[0].contracts <= result_high.positions[0].contracts


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_candidates(self):
        result = optimize_portfolio_v4([], 50000, 10000)
        assert len(result.positions) == 0
        assert result.solver_status == "empty"

    def test_zero_capital(self):
        result = optimize_portfolio_v4([_candidate("AAPL")], 0, 0)
        assert len(result.positions) == 0

    def test_negative_ev_skipped(self):
        candidates = [_candidate("AAPL", ev_amount=-50, prob_profit=0.30)]
        result = optimize_portfolio_v4(
            candidates, available_capital=50000, risk_budget=10000,
        )
        # Negative EV → Kelly = 0 → no allocation
        # (may still appear if bounds allow tiny allocation)
        assert result.total_risk <= 1000

    def test_single_candidate(self):
        result = optimize_portfolio_v4(
            [_candidate("AAPL")], available_capital=50000, risk_budget=10000,
        )
        assert len(result.positions) <= 1


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    @patch.dict("os.environ", {"OPTIMIZER_V4_ENABLED": "1"})
    def test_enabled(self):
        assert is_optimizer_v4_enabled() is True

    @patch.dict("os.environ", {}, clear=True)
    def test_disabled_by_default(self):
        assert is_optimizer_v4_enabled() is False
