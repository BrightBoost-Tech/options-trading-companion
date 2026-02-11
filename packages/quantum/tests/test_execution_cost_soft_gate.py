"""
Tests for soft execution cost gate.

Verifies:
1. Hard reject mode (default) returns None when cost >= EV
2. Soft mode allows candidate with badge + penalty when cost >= EV
3. Soft mode still rejects when cost is extremely high (>= EV * max_mult)
4. Badge and penalty are correctly applied
"""

import pytest
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class MockUnifiedScore:
    """Mock UnifiedScore for testing."""
    score: float
    badges: list = field(default_factory=list)
    execution_cost_dollars: float = 0.0
    components: Any = None

    def __post_init__(self):
        if self.components is None:
            self.components = MockComponents()


@dataclass
class MockComponents:
    """Mock components for UnifiedScore."""
    def model_dump(self):
        return {}


def simulate_execution_cost_gate(
    expected_execution_cost: float,
    total_ev: float,
    unified_score: MockUnifiedScore,
    hard_reject: bool = True,
    max_mult: float = 1.5,
    soft_penalty: float = 10.0
) -> tuple[Optional[Dict[str, Any]], bool]:
    """
    Simulate the execution cost gate logic.

    Returns:
        (candidate_dict or None, was_soft_gate_triggered)
    """
    execution_cost_soft_gate_triggered = False

    if expected_execution_cost >= total_ev:
        if hard_reject:
            return None, False

        # Soft mode: still reject if cost is way too high
        if total_ev > 0 and expected_execution_cost >= (total_ev * max_mult):
            return None, False

        # Soft mode: allow candidate but with badge + penalty
        unified_score.score = max(0.0, unified_score.score - soft_penalty)
        unified_score.badges.append("HIGH_EXECUTION_COST")
        execution_cost_soft_gate_triggered = True

    # Build candidate
    candidate = {
        "symbol": "TEST",
        "ev": total_ev,
        "score": unified_score.score,
        "badges": unified_score.badges,
        "execution_drag_estimate": expected_execution_cost,
    }

    if execution_cost_soft_gate_triggered:
        candidate["execution_cost_soft_gate"] = True
        candidate["execution_cost_soft_penalty"] = soft_penalty
        candidate["execution_cost_ev_ratio"] = round(
            expected_execution_cost / max(1e-9, total_ev), 4
        )

    return candidate, execution_cost_soft_gate_triggered


class TestHardRejectMode:
    """Tests for hard reject mode (default behavior)."""

    def test_rejects_when_cost_exceeds_ev(self):
        """Should reject when execution cost >= EV in hard mode."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=True
        )

        assert result is None
        assert triggered is False

    def test_rejects_when_cost_equals_ev(self):
        """Should reject when execution cost == EV in hard mode."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=25.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=True
        )

        assert result is None
        assert triggered is False

    def test_allows_when_cost_less_than_ev(self):
        """Should allow when execution cost < EV."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=10.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=True
        )

        assert result is not None
        assert triggered is False
        assert result["score"] == 50.0
        assert "HIGH_EXECUTION_COST" not in result["badges"]


class TestSoftRejectMode:
    """Tests for soft reject mode."""

    def test_allows_with_badge_when_cost_exceeds_ev(self):
        """Should allow candidate with badge when cost >= EV in soft mode."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=10.0
        )

        assert result is not None
        assert triggered is True
        assert "HIGH_EXECUTION_COST" in result["badges"]

    def test_applies_score_penalty(self):
        """Should reduce score by soft_penalty amount."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=10.0
        )

        assert result is not None
        assert result["score"] == 40.0  # 50 - 10

    def test_score_does_not_go_negative(self):
        """Score should be clamped to 0 minimum."""
        unified_score = MockUnifiedScore(score=5.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=10.0
        )

        assert result is not None
        assert result["score"] == 0.0  # max(0, 5-10)

    def test_includes_soft_gate_fields(self):
        """Should include soft gate metadata in candidate."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=10.0
        )

        assert result is not None
        assert result["execution_cost_soft_gate"] is True
        assert result["execution_cost_soft_penalty"] == 10.0
        assert result["execution_cost_ev_ratio"] == 1.2  # 30/25

    def test_still_rejects_extreme_cost(self):
        """Should still reject when cost >= EV * max_mult even in soft mode."""
        unified_score = MockUnifiedScore(score=50.0)

        # cost = 40, EV = 25, max_mult = 1.5
        # threshold = 25 * 1.5 = 37.5
        # 40 >= 37.5 -> reject
        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=40.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            max_mult=1.5
        )

        assert result is None
        assert triggered is False

    def test_allows_just_under_extreme_threshold(self):
        """Should allow when cost is just under EV * max_mult."""
        unified_score = MockUnifiedScore(score=50.0)

        # cost = 36, EV = 25, max_mult = 1.5
        # threshold = 37.5
        # 36 < 37.5 -> allow with badge
        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=36.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            max_mult=1.5,
            soft_penalty=10.0
        )

        assert result is not None
        assert triggered is True
        assert "HIGH_EXECUTION_COST" in result["badges"]


class TestEdgeCases:
    """Edge case tests for execution cost gate."""

    def test_zero_ev_in_soft_mode(self):
        """Should handle zero EV gracefully."""
        unified_score = MockUnifiedScore(score=50.0)

        # When EV = 0, cost >= EV triggers but max_mult check uses total_ev > 0
        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=10.0,
            total_ev=0.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=5.0
        )

        # EV = 0, so total_ev > 0 check fails, goes to soft gate
        assert result is not None
        assert triggered is True

    def test_negative_ev_in_soft_mode(self):
        """Should handle negative EV (cost always >= EV)."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=5.0,
            total_ev=-10.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=5.0
        )

        # cost >= EV (5 >= -10), but total_ev <= 0 so max_mult check skipped
        assert result is not None
        assert triggered is True

    def test_custom_penalty_amount(self):
        """Should use custom penalty amount."""
        unified_score = MockUnifiedScore(score=100.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=25.0  # Custom penalty
        )

        assert result is not None
        assert result["score"] == 75.0  # 100 - 25
        assert result["execution_cost_soft_penalty"] == 25.0

    def test_custom_max_mult(self):
        """Should use custom max_mult threshold."""
        unified_score = MockUnifiedScore(score=50.0)

        # cost = 30, EV = 25, max_mult = 1.1
        # threshold = 25 * 1.1 = 27.5
        # 30 >= 27.5 -> reject
        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=30.0,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            max_mult=1.1  # Stricter threshold
        )

        assert result is None
        assert triggered is False

    def test_cost_ratio_calculation(self):
        """Should correctly calculate cost/EV ratio."""
        unified_score = MockUnifiedScore(score=50.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=15.0,
            total_ev=10.0,
            unified_score=unified_score,
            hard_reject=False,
            max_mult=2.0,  # Allow this ratio
            soft_penalty=5.0
        )

        assert result is not None
        assert result["execution_cost_ev_ratio"] == 1.5  # 15/10


class TestIntegrationScenarios:
    """Real-world scenario tests."""

    def test_typical_condor_high_exec_cost(self):
        """Typical condor with high execution cost in soft mode."""
        # Scenario: EV = $20, execution cost = $22
        unified_score = MockUnifiedScore(score=65.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=22.0,
            total_ev=20.0,
            unified_score=unified_score,
            hard_reject=False,
            max_mult=1.5,
            soft_penalty=10.0
        )

        assert result is not None
        assert triggered is True
        assert result["score"] == 55.0  # 65 - 10
        assert "HIGH_EXECUTION_COST" in result["badges"]
        assert result["execution_cost_ev_ratio"] == 1.1

    def test_borderline_cost_passes_in_soft_mode(self):
        """Cost barely exceeding EV should pass in soft mode."""
        unified_score = MockUnifiedScore(score=70.0)

        result, triggered = simulate_execution_cost_gate(
            expected_execution_cost=25.01,
            total_ev=25.0,
            unified_score=unified_score,
            hard_reject=False,
            soft_penalty=10.0
        )

        assert result is not None
        assert triggered is True
        assert result["score"] == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
