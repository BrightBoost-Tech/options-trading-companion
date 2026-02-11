"""
Tests for trade_suggestions missing column stripping logic.

Verifies:
1. _extract_missing_column correctly parses PostgREST error messages
2. DROPPABLE_SUGGESTION_COLUMNS contains expected columns
3. Bounded retry strips columns one at a time
4. Non-droppable columns cause insert failure
"""

import pytest
import re
from typing import Optional, Dict, Any, Tuple


# Mirror the production constants and functions
DROPPABLE_SUGGESTION_COLUMNS = {
    "agent_signals", "agent_summary", "source", "marketdata_quality",
    "blocked_reason", "blocked_detail", "execution_cost_soft_gate",
    "execution_cost_soft_penalty", "execution_cost_ev_ratio",
}


def _extract_missing_column(err_msg: str) -> Optional[str]:
    """
    Extract missing column name from PostgREST error message.
    Example: "Could not find the 'agent_signals' column"
    """
    m = re.search(r"could not find the '([^']+)' column", err_msg.lower())
    return m.group(1) if m else None


def simulate_bounded_retry_insert(
    payload: Dict[str, Any],
    failing_columns: list,
    max_retries: int = 3
) -> Tuple[Optional[Dict[str, Any]], list]:
    """
    Simulate the bounded retry insert logic.

    Args:
        payload: The original payload to insert
        failing_columns: List of columns that will cause insert failure (in order)
        max_retries: Maximum number of retries

    Returns:
        (final_payload or None if failed, list of stripped columns)
    """
    current_payload = payload.copy()
    stripped_columns = []
    fail_index = 0

    for retry_num in range(max_retries + 1):  # +1 for initial attempt
        if fail_index >= len(failing_columns):
            # No more failures, success
            return current_payload, stripped_columns

        # Simulate failure
        missing_col = failing_columns[fail_index]
        error_msg = f"Could not find the '{missing_col}' column"

        extracted = _extract_missing_column(error_msg)
        if extracted and extracted in DROPPABLE_SUGGESTION_COLUMNS:
            current_payload = {k: v for k, v in current_payload.items() if k != extracted}
            stripped_columns.append(extracted)
            fail_index += 1
        else:
            # Non-droppable or not a column error
            return None, stripped_columns

    # Max retries exceeded
    return None, stripped_columns


class TestExtractMissingColumn:
    """Tests for _extract_missing_column function."""

    def test_extracts_agent_signals(self):
        """Should extract 'agent_signals' from error message."""
        err = "Could not find the 'agent_signals' column of 'trade_suggestions'"
        assert _extract_missing_column(err) == "agent_signals"

    def test_extracts_agent_summary(self):
        """Should extract 'agent_summary' from error message."""
        err = "Could not find the 'agent_summary' column"
        assert _extract_missing_column(err) == "agent_summary"

    def test_extracts_execution_cost_soft_gate(self):
        """Should extract 'execution_cost_soft_gate' from error message."""
        err = "Could not find the 'execution_cost_soft_gate' column"
        assert _extract_missing_column(err) == "execution_cost_soft_gate"

    def test_case_insensitive_matching(self):
        """Should match regardless of case."""
        err = "COULD NOT FIND THE 'source' COLUMN"
        assert _extract_missing_column(err) == "source"

    def test_returns_none_for_non_matching_error(self):
        """Should return None for non-column errors."""
        err = "Connection timeout after 30s"
        assert _extract_missing_column(err) is None

    def test_returns_none_for_different_error_format(self):
        """Should return None for different error formats."""
        err = "column 'agent_signals' does not exist"
        assert _extract_missing_column(err) is None

    def test_extracts_from_full_postgrest_error(self):
        """Should extract from full PostgREST error message."""
        err = ("{'code': 'PGRST204', 'details': None, 'hint': None, "
               "'message': \"Could not find the 'agent_signals' column of 'trade_suggestions' "
               "in the schema cache\"}")
        assert _extract_missing_column(err) == "agent_signals"


class TestDroppableSuggestionColumns:
    """Tests for DROPPABLE_SUGGESTION_COLUMNS set."""

    def test_contains_agent_signals(self):
        """Should contain agent_signals."""
        assert "agent_signals" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_agent_summary(self):
        """Should contain agent_summary."""
        assert "agent_summary" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_source(self):
        """Should contain source."""
        assert "source" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_marketdata_quality(self):
        """Should contain marketdata_quality."""
        assert "marketdata_quality" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_blocked_reason(self):
        """Should contain blocked_reason."""
        assert "blocked_reason" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_blocked_detail(self):
        """Should contain blocked_detail."""
        assert "blocked_detail" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_execution_cost_soft_gate(self):
        """Should contain execution_cost_soft_gate."""
        assert "execution_cost_soft_gate" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_execution_cost_soft_penalty(self):
        """Should contain execution_cost_soft_penalty."""
        assert "execution_cost_soft_penalty" in DROPPABLE_SUGGESTION_COLUMNS

    def test_contains_execution_cost_ev_ratio(self):
        """Should contain execution_cost_ev_ratio."""
        assert "execution_cost_ev_ratio" in DROPPABLE_SUGGESTION_COLUMNS

    def test_does_not_contain_core_fields(self):
        """Should not contain core required fields."""
        core_fields = ["ticker", "strategy", "ev", "trace_id", "user_id", "status"]
        for field in core_fields:
            assert field not in DROPPABLE_SUGGESTION_COLUMNS


class TestBoundedRetryLogic:
    """Tests for bounded retry insert logic."""

    def test_strips_single_droppable_column(self):
        """Should strip single droppable column and succeed."""
        payload = {"ticker": "SPY", "agent_signals": {}, "ev": 10.0}

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["agent_signals"]
        )

        assert result is not None
        assert "agent_signals" not in result
        assert "ticker" in result
        assert stripped == ["agent_signals"]

    def test_strips_multiple_droppable_columns(self):
        """Should strip multiple columns in sequence."""
        payload = {
            "ticker": "SPY",
            "agent_signals": {},
            "agent_summary": "test",
            "source": "scanner",
            "ev": 10.0
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["agent_signals", "agent_summary"]
        )

        assert result is not None
        assert "agent_signals" not in result
        assert "agent_summary" not in result
        assert "ticker" in result
        assert stripped == ["agent_signals", "agent_summary"]

    def test_fails_after_max_retries(self):
        """Should fail after max retries exceeded."""
        payload = {
            "ticker": "SPY",
            "agent_signals": {},
            "agent_summary": "test",
            "source": "scanner",
            "marketdata_quality": "good",
            "blocked_reason": "test",
            "ev": 10.0
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["agent_signals", "agent_summary", "source", "marketdata_quality", "blocked_reason"],
            max_retries=3
        )

        # Initial + 3 retries = 4 strips max, then fail on 5th column
        assert result is None
        assert len(stripped) == 4

    def test_fails_on_non_droppable_column(self):
        """Should fail when non-droppable column is missing."""
        payload = {"ticker": "SPY", "custom_field": "test", "ev": 10.0}

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["custom_field"]
        )

        assert result is None
        assert stripped == []

    def test_succeeds_with_no_failures(self):
        """Should succeed immediately with no failures."""
        payload = {"ticker": "SPY", "ev": 10.0}

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=[]
        )

        assert result is not None
        assert result == payload
        assert stripped == []

    def test_preserves_core_fields(self):
        """Should preserve core fields after stripping droppable ones."""
        payload = {
            "ticker": "AAPL",
            "strategy": "iron_condor",
            "ev": 25.5,
            "trace_id": "abc-123",
            "agent_signals": {"signal": "buy"},
            "source": "scanner"
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["agent_signals", "source"]
        )

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["strategy"] == "iron_condor"
        assert result["ev"] == 25.5
        assert result["trace_id"] == "abc-123"


class TestIntegrationScenarios:
    """Real-world scenario tests."""

    def test_typical_new_column_rollout(self):
        """Typical scenario: new column added to code but not DB yet."""
        payload = {
            "ticker": "SPY",
            "strategy": "iron_condor",
            "ev": 15.0,
            "execution_cost_soft_gate": True,  # New column
            "execution_cost_soft_penalty": 10.0,  # New column
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["execution_cost_soft_gate"]
        )

        assert result is not None
        assert "execution_cost_soft_gate" not in result
        assert "execution_cost_soft_penalty" in result  # Still present

    def test_multiple_new_columns_rollout(self):
        """Multiple new columns missing from DB."""
        payload = {
            "ticker": "SPY",
            "strategy": "iron_condor",
            "ev": 15.0,
            "execution_cost_soft_gate": True,
            "execution_cost_soft_penalty": 10.0,
            "execution_cost_ev_ratio": 1.2,
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=[
                "execution_cost_soft_gate",
                "execution_cost_soft_penalty",
                "execution_cost_ev_ratio"
            ]
        )

        assert result is not None
        assert len(stripped) == 3
        # Only core fields remain
        assert result == {"ticker": "SPY", "strategy": "iron_condor", "ev": 15.0}

    def test_agent_columns_fallback(self):
        """Legacy scenario: agent columns not in DB."""
        payload = {
            "ticker": "AAPL",
            "strategy": "vertical",
            "ev": 20.0,
            "agent_signals": {"momentum": 0.7},
            "agent_summary": "Bullish momentum",
        }

        result, stripped = simulate_bounded_retry_insert(
            payload,
            failing_columns=["agent_signals", "agent_summary"]
        )

        assert result is not None
        assert stripped == ["agent_signals", "agent_summary"]
        assert result == {"ticker": "AAPL", "strategy": "vertical", "ev": 20.0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
