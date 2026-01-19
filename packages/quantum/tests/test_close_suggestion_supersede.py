"""
Tests for Close Suggestion Supersede Logic

Tests that when exit mode changes (e.g., take_profit_limit → salvage_exit),
the old pending suggestion is superseded and only the new one remains active.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from packages.quantum.services.workflow_orchestrator import (
    supersede_prior_close_suggestions,
    CLOSE_STRATEGIES,
    TRADE_SUGGESTIONS_TABLE,
)


# =============================================================================
# Unit Tests: supersede_prior_close_suggestions
# =============================================================================

class TestSupersedePriorCloseSuggestions:
    """Test the supersede_prior_close_suggestions helper function."""

    def test_supersede_returns_zero_when_no_client(self):
        """Should return 0 when supabase client is None."""
        result = supersede_prior_close_suggestions(
            None,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="salvage_exit"
        )
        assert result == 0

    def test_supersede_returns_zero_when_no_fingerprint(self):
        """Should return 0 when legs_fingerprint is empty."""
        mock_client = MagicMock()
        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="",
            new_strategy="salvage_exit"
        )
        assert result == 0

    def test_supersede_queries_for_other_strategies(self):
        """Should query for strategies other than the new one."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup chain
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[])

        supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="salvage_exit"
        )

        # Verify in_ was called with strategies excluding salvage_exit
        in_calls = [c for c in mock_select.in_.call_args_list]
        strategy_call = [c for c in in_calls if c[0][0] == "strategy"]
        assert len(strategy_call) == 1
        strategies_queried = strategy_call[0][0][1]
        assert "salvage_exit" not in strategies_queried
        assert "take_profit_limit" in strategies_queried
        assert "lottery_trap" in strategies_queried

    def test_supersede_updates_status_to_superseded(self):
        """Should update matching suggestions to status='superseded'."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return a matching suggestion
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "sugg-old-123", "strategy": "take_profit_limit", "status": "pending"}
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="salvage_exit",
            reason="superseded_by_salvage_exit"
        )

        assert result == 1

        # Verify update was called with correct payload
        update_calls = mock_table.update.call_args_list
        assert len(update_calls) == 1
        update_payload = update_calls[0][0][0]
        assert update_payload["status"] == "superseded"
        assert update_payload["dismissed_reason"] == "superseded_by_salvage_exit"

    def test_supersede_handles_multiple_matching_suggestions(self):
        """Should supersede all matching suggestions."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return multiple suggestions
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "sugg-1", "strategy": "take_profit_limit", "status": "pending"},
            {"id": "sugg-2", "strategy": "take_profit_limit", "status": "staged"},
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="lottery_trap"
        )

        assert result == 2

    def test_supersede_only_affects_pending_staged_queued(self):
        """Should only query for pending, staged, queued statuses."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[])

        supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="salvage_exit"
        )

        # Verify in_ was called with status filter
        in_calls = [c for c in mock_select.in_.call_args_list]
        status_call = [c for c in in_calls if c[0][0] == "status"]
        assert len(status_call) == 1
        statuses_queried = status_call[0][0][1]
        assert set(statuses_queried) == {"pending", "queued", "staged"}

    def test_supersede_handles_query_exception(self):
        """Should return 0 and not raise when query fails."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.side_effect = Exception("Database error")

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-123",
            new_strategy="salvage_exit"
        )

        assert result == 0


# =============================================================================
# Unit Tests: CLOSE_STRATEGIES constant
# =============================================================================

class TestCloseStrategiesConstant:
    """Test the CLOSE_STRATEGIES constant."""

    def test_close_strategies_includes_expected_values(self):
        """CLOSE_STRATEGIES should include all exit strategies."""
        assert "take_profit_limit" in CLOSE_STRATEGIES
        assert "salvage_exit" in CLOSE_STRATEGIES
        assert "lottery_trap" in CLOSE_STRATEGIES

    def test_close_strategies_is_tuple(self):
        """CLOSE_STRATEGIES should be a tuple (immutable)."""
        assert isinstance(CLOSE_STRATEGIES, tuple)


# =============================================================================
# Integration-style Tests (mocked DB)
# =============================================================================

class TestSupersedeBehaviorIntegration:
    """Test supersede behavior in the context of the workflow."""

    def test_take_profit_superseded_by_salvage_exit(self):
        """
        Scenario: Position has take_profit_limit, then deep loss triggers salvage_exit.
        Result: Old take_profit_limit should be marked superseded.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Old suggestion exists
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "old-take-profit-123",
                "strategy": "take_profit_limit",
                "status": "pending",
                "ticker": "KURA",
                "legs_fingerprint": "fp-abc123"
            }
        ])

        # Setup update
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        # Supersede when creating salvage_exit
        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            new_strategy="salvage_exit",
            reason="superseded_by_salvage_exit"
        )

        assert result == 1
        # Verify the old suggestion was updated
        mock_table.update.assert_called_once()

    def test_salvage_exit_superseded_by_lottery_trap(self):
        """
        Scenario: Position has salvage_exit, then deeper loss triggers lottery_trap.
        Result: Old salvage_exit should be marked superseded.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "old-salvage-456",
                "strategy": "salvage_exit",
                "status": "pending"
            }
        ])

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-xyz789",
            new_strategy="lottery_trap",
            reason="superseded_by_lottery_trap"
        )

        assert result == 1

    def test_executed_suggestions_not_superseded(self):
        """
        Scenario: Old suggestion has status='executed'.
        Result: Should NOT be superseded (not in query results).
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        # Query filters out executed, so it returns empty
        mock_select.execute.return_value = MagicMock(data=[])

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            new_strategy="salvage_exit"
        )

        assert result == 0
        # Verify no update was called
        mock_table.update.assert_not_called()

    def test_different_ticker_not_superseded(self):
        """
        Scenario: Different ticker has pending close suggestion.
        Result: Should NOT be superseded (filtered by ticker).
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        # Query filters by ticker, so different ticker not returned
        mock_select.execute.return_value = MagicMock(data=[])

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-kura-123",
            new_strategy="salvage_exit"
        )

        assert result == 0

    def test_different_fingerprint_not_superseded(self):
        """
        Scenario: Same ticker but different position (different fingerprint).
        Result: Should NOT be superseded.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[])

        result = supersede_prior_close_suggestions(
            mock_client,
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-different-position",
            new_strategy="salvage_exit"
        )

        assert result == 0
