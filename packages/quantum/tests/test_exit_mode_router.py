"""
Tests for Exit Mode Router and Deep Loser Exit Pricing

Tests the logic that prevents absurd take-profit targets for deep losing positions.
"""

import pytest
from unittest.mock import patch, MagicMock

# Import the functions we're testing
from packages.quantum.services.workflow_orchestrator import (
    compute_exit_mode,
    clamp_take_profit_limit,
    LOSS_EXIT_THRESHOLD,
    MAX_TAKE_PROFIT_MULTIPLIER,
)
from packages.quantum.analytics.loss_minimizer import LossMinimizer, LossAnalysisResult


class TestComputeExitMode:
    """Test the Exit Mode Router logic."""

    def test_deep_loser_triggers_salvage_mode(self):
        """
        Position down 90%+ should trigger salvage/lottery mode, not normal.

        Example: unit_cost=300, unit_price=2 (99.3% loss)
        """
        unit_cost = 300.0
        unit_price = 2.0  # 99.3% loss

        result = compute_exit_mode(unit_price, unit_cost)

        assert result["mode"] in ("salvage", "lottery_trap"), \
            f"Expected salvage or lottery_trap mode, got {result['mode']}"
        assert result["limit_price"] is not None
        assert result["rationale_prefix"] != ""

    def test_deep_loser_limit_price_is_reasonable(self):
        """
        For deep loser (cost=300, price=2), limit should be near bid/mid or trap,
        NOT the absurd 875 from EV model.
        """
        unit_cost = 300.0
        unit_price = 2.0

        # Simulate with market data (bid/ask around current price)
        market_data = {"bid": 1.8, "ask": 2.2}

        result = compute_exit_mode(unit_price, unit_cost, market_data)

        # For salvage: should be near mid (~2.0)
        # For lottery trap: should be ~3-4x current (~6-8)
        if result["mode"] == "salvage":
            assert result["limit_price"] <= 2.5, \
                f"Salvage limit {result['limit_price']} too high (expected <= 2.5)"
        elif result["mode"] == "lottery_trap":
            assert result["limit_price"] <= 10.0, \
                f"Lottery trap limit {result['limit_price']} too high (expected <= 10)"

        # Most importantly, it should NEVER be the absurd 875
        assert result["limit_price"] < 100, \
            f"Limit price {result['limit_price']} is absurdly high"

    def test_normal_position_stays_normal(self):
        """
        Position with only 20% loss should stay in normal mode.
        """
        unit_cost = 100.0
        unit_price = 80.0  # 20% loss, above 50% threshold

        result = compute_exit_mode(unit_price, unit_cost)

        assert result["mode"] == "normal"
        assert result["limit_price"] is None  # Normal mode doesn't set limit

    def test_warning_included_for_deep_loser(self):
        """
        Deep loser modes should include a warning about unrealistic targets.
        """
        unit_cost = 300.0
        unit_price = 2.0

        result = compute_exit_mode(unit_price, unit_cost)

        assert result["warning"] is not None
        assert "take-profit" in result["warning"].lower() or "875" in result["warning"]


class TestClampTakeProfitLimit:
    """Test the take-profit limit clamping logic."""

    def test_absurd_limit_gets_clamped(self):
        """
        Limit of 875 for a $2 position should be clamped to 3x = $6.
        """
        limit_price = 875.0
        unit_price = 2.0

        clamped, reason = clamp_take_profit_limit(limit_price, unit_price, "normal")

        expected_max = unit_price * MAX_TAKE_PROFIT_MULTIPLIER  # 6.0 by default

        assert clamped <= expected_max, \
            f"Clamped price {clamped} exceeds {MAX_TAKE_PROFIT_MULTIPLIER}x current ({expected_max})"
        assert reason is not None
        assert "Clamped" in reason

    def test_reasonable_limit_not_clamped(self):
        """
        Limit that's within multiplier should not be clamped.
        """
        limit_price = 5.0
        unit_price = 2.0  # 5.0 is 2.5x, within 3x

        clamped, reason = clamp_take_profit_limit(limit_price, unit_price, "normal")

        assert clamped == limit_price
        assert reason is None

    def test_salvage_mode_not_clamped(self):
        """
        Salvage/lottery modes should not be clamped (they have their own logic).
        """
        limit_price = 10.0
        unit_price = 2.0

        clamped, reason = clamp_take_profit_limit(limit_price, unit_price, "salvage")

        assert clamped == limit_price
        assert reason is None


class TestLossMinimizerIntegration:
    """Test LossMinimizer behavior for deep losers."""

    def test_salvage_scenario_with_meaningful_value(self):
        """
        Position with >$100 remaining value should get salvage recommendation.
        """
        position = {
            "current_price": 2.0,  # $200 remaining value
            "quantity": 1,
            "cost_basis": 300.0
        }
        market_data = {"bid": 1.8, "ask": 2.2}

        result = LossMinimizer.analyze_position(position, market_data=market_data)

        assert "Salvage" in result.scenario
        assert result.limit_price is not None
        # Should be near mid (2.0), not some crazy number
        assert result.limit_price <= 3.0, \
            f"Salvage limit {result.limit_price} too high"

    def test_lottery_scenario_with_worthless_position(self):
        """
        Position with <$100 remaining value should get lottery trap recommendation.
        """
        position = {
            "current_price": 0.05,  # $5 remaining value
            "quantity": 1,
            "cost_basis": 300.0
        }
        market_data = {"bid": 0.03, "ask": 0.07}

        result = LossMinimizer.analyze_position(position, market_data=market_data)

        assert "Lottery" in result.scenario or "Worthless" in result.scenario
        assert result.limit_price is not None
        # Should be 3-4x current (~0.15-0.20)
        assert result.limit_price <= 1.0, \
            f"Lottery trap limit {result.limit_price} too high for worthless position"

    def test_warning_always_present(self):
        """
        LossMinimizer should always include a warning about high take-profit targets.
        """
        position = {
            "current_price": 2.0,
            "quantity": 1,
            "cost_basis": 300.0
        }

        result = LossMinimizer.analyze_position(position)

        assert result.warning is not None
        assert len(result.warning) > 0


class TestEndToEndScenario:
    """
    End-to-end test of the example scenario:
    unit_cost=300, unit_price=2 → exit limit should be <= ~2.5 (salvage) or <= ~8 (trap)
    """

    def test_example_scenario_never_produces_875(self):
        """
        The specific bug case: cost=300, price=2 should NEVER produce limit=875.
        """
        unit_cost = 300.0
        unit_price = 2.0
        market_data = {"bid": 1.8, "ask": 2.2}

        # Test exit mode router
        result = compute_exit_mode(unit_price, unit_cost, market_data)

        # The limit price should be reasonable
        assert result["limit_price"] < 20.0, \
            f"FAIL: Limit price {result['limit_price']} is way too high for a deep loser"

        # If somehow we got to clamping (which we shouldn't for deep losers)
        if result["mode"] == "normal":
            clamped, _ = clamp_take_profit_limit(875.0, unit_price, "normal")
            assert clamped <= unit_price * MAX_TAKE_PROFIT_MULTIPLIER

    def test_deep_loser_rationale_is_clear(self):
        """
        Rationale for deep loser should clearly indicate SALVAGE or LOTTERY.
        """
        unit_cost = 300.0
        unit_price = 2.0

        result = compute_exit_mode(unit_price, unit_cost)

        prefix = result.get("rationale_prefix", "")
        assert "SALVAGE" in prefix.upper() or "LOTTERY" in prefix.upper(), \
            f"Rationale prefix '{prefix}' should clearly indicate exit mode"
