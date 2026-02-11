"""
Tests for midday risk_budget extraction from RiskBudgetReport.

Verifies:
1. Correct extraction from RiskBudgetReport object (global_allocation.remaining)
2. Fallback extraction from dict-like object
3. Graceful handling of None/missing values
"""

import pytest
from typing import Optional
from dataclasses import dataclass


@dataclass
class MockGlobalAllocation:
    """Mock GlobalAllocation for testing."""
    remaining: float
    used: float = 0.0
    max_limit: float = 1000.0


@dataclass
class MockRiskBudgetReport:
    """Mock RiskBudgetReport for testing."""
    global_allocation: Optional[MockGlobalAllocation] = None
    regime: str = "neutral"
    diagnostics: Optional[dict] = None


def extract_remaining_global_budget(budgets) -> float:
    """
    Extract remaining global budget from RiskBudgetReport or dict.

    This mirrors the logic in workflow_orchestrator.run_midday_cycle.
    """
    # Preferred: RiskBudgetReport object with global_allocation.remaining
    remaining_global_budget = None
    try:
        if hasattr(budgets, "global_allocation") and budgets.global_allocation:
            remaining_global_budget = float(budgets.global_allocation.remaining or 0.0)
    except Exception:
        remaining_global_budget = None

    # Fallback: dict-like access (backward compatibility)
    if remaining_global_budget is None:
        try:
            ga = budgets.get("global_allocation") if hasattr(budgets, "get") else None
            if isinstance(ga, dict):
                remaining_global_budget = float(ga.get("remaining") or 0.0)
            else:
                remaining_global_budget = 0.0
        except Exception:
            remaining_global_budget = 0.0

    return remaining_global_budget


class TestExtractFromRiskBudgetReport:
    """Tests for extracting remaining budget from RiskBudgetReport object."""

    def test_extracts_remaining_from_global_allocation(self):
        """Should extract remaining from global_allocation.remaining."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(remaining=1234.56)
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 1234.56

    def test_extracts_zero_when_remaining_is_zero(self):
        """Should return 0 when remaining is 0."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(remaining=0.0)
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_none_global_allocation(self):
        """Should return 0 when global_allocation is None."""
        budgets = MockRiskBudgetReport(global_allocation=None)

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_none_remaining(self):
        """Should return 0 when remaining is None."""
        ga = MockGlobalAllocation(remaining=500.0)
        ga.remaining = None  # Set to None after creation
        budgets = MockRiskBudgetReport(global_allocation=ga)

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_large_remaining_value(self):
        """Should handle large remaining values."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(remaining=100000.00)
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 100000.00


class TestExtractFromDict:
    """Tests for fallback extraction from dict-like objects."""

    def test_extracts_from_dict_global_allocation(self):
        """Should extract from dict with global_allocation key."""
        budgets = {
            "global_allocation": {
                "remaining": 500.0,
                "used": 200.0,
                "max_limit": 700.0
            }
        }

        result = extract_remaining_global_budget(budgets)

        assert result == 500.0

    def test_handles_empty_dict(self):
        """Should return 0 for empty dict."""
        budgets = {}

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_dict_without_global_allocation(self):
        """Should return 0 when global_allocation key missing."""
        budgets = {"regime": "neutral", "other_key": 123}

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_dict_with_none_global_allocation(self):
        """Should return 0 when global_allocation is None in dict."""
        budgets = {"global_allocation": None}

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_handles_dict_global_allocation_without_remaining(self):
        """Should return 0 when remaining key missing from global_allocation."""
        budgets = {
            "global_allocation": {
                "used": 200.0,
                "max_limit": 700.0
            }
        }

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0


class TestEdgeCases:
    """Edge case tests for budget extraction."""

    def test_handles_string_remaining_value(self):
        """Should handle string remaining value (converts to float)."""
        budgets = {
            "global_allocation": {
                "remaining": "750.50"
            }
        }

        result = extract_remaining_global_budget(budgets)

        assert result == 750.50

    def test_handles_int_remaining_value(self):
        """Should handle int remaining value."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(remaining=1000)
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 1000.0

    def test_prefers_object_over_dict_fallback(self):
        """Object extraction should be preferred over dict fallback."""
        # Create object that also has .get() method
        class HybridBudgets:
            def __init__(self):
                self.global_allocation = MockGlobalAllocation(remaining=999.0)

            def get(self, key, default=None):
                # Would return different value if dict fallback used
                if key == "global_allocation":
                    return {"remaining": 111.0}
                return default

        budgets = HybridBudgets()

        result = extract_remaining_global_budget(budgets)

        # Should use object path (999) not dict fallback (111)
        assert result == 999.0

    def test_handles_negative_remaining(self):
        """Should handle negative remaining value (overdraft scenario)."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(remaining=-50.0)
        )

        result = extract_remaining_global_budget(budgets)

        assert result == -50.0


class TestIntegrationScenarios:
    """Real-world scenario tests."""

    def test_typical_midday_budget_report(self):
        """Typical midday scenario with partial budget used."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(
                remaining=1500.0,
                used=500.0,
                max_limit=2000.0
            ),
            regime="neutral",
            diagnostics={"reason": "within_limits"}
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 1500.0

    def test_fully_allocated_budget(self):
        """Scenario where budget is fully allocated."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(
                remaining=0.0,
                used=2000.0,
                max_limit=2000.0
            ),
            regime="risk_off"
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 0.0

    def test_fresh_account_full_budget(self):
        """Fresh account with full budget available."""
        budgets = MockRiskBudgetReport(
            global_allocation=MockGlobalAllocation(
                remaining=5000.0,
                used=0.0,
                max_limit=5000.0
            ),
            regime="risk_on"
        )

        result = extract_remaining_global_budget(budgets)

        assert result == 5000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
