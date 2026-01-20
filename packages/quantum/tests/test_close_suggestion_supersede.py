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


# =============================================================================
# Wave 1.3 Tests: Audit & Analytics Events on Supersede
# =============================================================================

class TestWave13SupersedeEventEmission:
    """Wave 1.3: Test that supersede emits audit and analytics events."""

    def test_supersede_emits_audit_event(self):
        """
        Wave 1.3: supersede_prior_close_suggestions should call AuditLogService.log_audit_event.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return a matching suggestion with trace_id
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "sugg-old-123",
                "strategy": "take_profit_limit",
                "status": "pending",
                "trace_id": "trace-abc-456"
            }
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            supersede_prior_close_suggestions(
                mock_client,
                user_id="user-123",
                cycle_date="2026-01-19",
                window="morning_limit",
                ticker="KURA",
                legs_fingerprint="fp-123",
                new_strategy="salvage_exit",
                reason="superseded_by_salvage_exit"
            )

            # Verify AuditLogService was instantiated and log_audit_event was called
            mock_audit_cls.assert_called_once_with(mock_client)
            mock_audit_service.log_audit_event.assert_called_once()

            # Verify the call arguments
            call_kwargs = mock_audit_service.log_audit_event.call_args[1]
            assert call_kwargs["user_id"] == "user-123"
            assert call_kwargs["event_name"] == "suggestion_superseded"
            assert call_kwargs["suggestion_id"] == "sugg-old-123"
            assert call_kwargs["trace_id"] == "trace-abc-456"
            assert call_kwargs["strategy"] == "take_profit_limit"
            # Verify payload contains expected fields
            assert "superseded_suggestion_id" in call_kwargs["payload"]
            assert call_kwargs["payload"]["old_strategy"] == "take_profit_limit"
            assert call_kwargs["payload"]["new_strategy"] == "salvage_exit"

    def test_supersede_emits_analytics_event(self):
        """
        Wave 1.3: supersede_prior_close_suggestions should call AnalyticsService.log_event.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return a matching suggestion
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "sugg-old-456",
                "strategy": "salvage_exit",
                "status": "pending",
                "trace_id": "trace-xyz-789"
            }
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService"):
            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-456",
                    new_strategy="lottery_trap",
                    reason="superseded_by_lottery_trap"
                )

                # Verify AnalyticsService was instantiated and log_event was called
                mock_analytics_cls.assert_called_once_with(mock_client)
                mock_analytics_service.log_event.assert_called_once()

                # Verify the call arguments
                call_kwargs = mock_analytics_service.log_event.call_args[1]
                assert call_kwargs["user_id"] == "user-123"
                assert call_kwargs["event_name"] == "suggestion_superseded"
                assert call_kwargs["category"] == "system"
                assert call_kwargs["trace_id"] == "trace-xyz-789"
                # Wave 1.3: Should have idempotency_payload for trace-scoped idempotency
                assert "idempotency_payload" in call_kwargs
                # Verify properties (note: key is "suggestion_id" in properties)
                assert call_kwargs["properties"]["suggestion_id"] == "sugg-old-456"
                assert call_kwargs["properties"]["old_strategy"] == "salvage_exit"
                assert call_kwargs["properties"]["new_strategy"] == "lottery_trap"

    def test_supersede_emits_events_for_each_superseded_suggestion(self):
        """
        Wave 1.3: When multiple suggestions are superseded, each should emit events.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return multiple suggestions
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "sugg-1", "strategy": "take_profit_limit", "status": "pending", "trace_id": "trace-1"},
            {"id": "sugg-2", "strategy": "take_profit_limit", "status": "staged", "trace_id": "trace-2"},
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                result = supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-multi",
                    new_strategy="lottery_trap"
                )

                assert result == 2

                # Verify audit event was called twice (once per suggestion)
                assert mock_audit_service.log_audit_event.call_count == 2

                # Verify analytics event was called twice
                assert mock_analytics_service.log_event.call_count == 2

    def test_supersede_no_events_when_no_suggestions_found(self):
        """
        Wave 1.3: No audit/analytics events should be emitted when no suggestions are superseded.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain to return empty results
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[])

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                result = supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-none",
                    new_strategy="salvage_exit"
                )

                assert result == 0

                # Verify no events were emitted
                mock_audit_service.log_audit_event.assert_not_called()
                mock_analytics_service.log_event.assert_not_called()

    def test_supersede_analytics_uses_idempotency_payload(self):
        """
        Wave 1.3: Analytics log_event should use idempotency_payload for trace-scoped idempotency.
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
                "id": "sugg-idem-123",
                "strategy": "take_profit_limit",
                "status": "pending",
                "trace_id": "trace-idem-456"
            }
        ])

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService"):
            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-idem",
                    new_strategy="salvage_exit",
                    reason="mode_change"
                )

                # Verify idempotency_payload was passed
                call_kwargs = mock_analytics_service.log_event.call_args[1]
                idempotency_payload = call_kwargs.get("idempotency_payload")

                assert idempotency_payload is not None
                assert idempotency_payload["superseded_suggestion_id"] == "sugg-idem-123"
                assert idempotency_payload["old_strategy"] == "take_profit_limit"
                assert idempotency_payload["new_strategy"] == "salvage_exit"
                assert idempotency_payload["reason"] == "mode_change"


# =============================================================================
# Wave 1.3 Tests: NULL Fingerprint Handling in insert_or_get_suggestion
# =============================================================================

class TestWave13InsertOrGetSuggestionNullFingerprint:
    """Wave 1.3: Test NULL fingerprint handling in insert_or_get_suggestion."""

    def test_insert_or_get_suggestion_with_null_fingerprint_uses_order_by(self):
        """
        Wave 1.3: When fingerprint is None/falsy and insert fails with unique violation,
        the fallback query should use order by created_at desc instead of .is_(null).
        """
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup insert to fail with unique violation (triggers fallback query)
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.side_effect = Exception("duplicate key value violates unique constraint")

        # Setup query chain for fallback
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.order.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "existing-123", "trace_id": "trace-existing"}
        ])

        suggestion = {
            "user_id": "user-123",
            "ticker": "KURA",
            "cycle_date": "2026-01-19",
            "window": "morning_limit",
            "strategy": "take_profit_limit",
            "legs_fingerprint": None,  # NULL fingerprint
        }

        unique_fields = ("user-123", "morning_limit", "2026-01-19", "KURA", "take_profit_limit", None)

        result = insert_or_get_suggestion(mock_client, suggestion, unique_fields)

        # Should return the existing suggestion
        assert result == ("existing-123", "trace-existing", False)

        # Verify that .order() was called (Wave 1.3 behavior for null fingerprint)
        mock_select.order.assert_called_once_with("created_at", desc=True)

    def test_insert_or_get_suggestion_with_valid_fingerprint_uses_eq(self):
        """
        Wave 1.3: When fingerprint is valid and insert fails with unique violation,
        the fallback query should use .eq() filter for fingerprint.
        """
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup insert to fail with unique violation (triggers fallback query)
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.side_effect = Exception("23505: duplicate key")

        # Setup query chain for fallback
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "existing-456", "trace_id": "trace-existing-456"}
        ])

        suggestion = {
            "user_id": "user-123",
            "ticker": "KURA",
            "cycle_date": "2026-01-19",
            "window": "morning_limit",
            "strategy": "take_profit_limit",
            "legs_fingerprint": "fp-valid-123",  # Valid fingerprint
        }

        unique_fields = ("user-123", "morning_limit", "2026-01-19", "KURA", "take_profit_limit", "fp-valid-123")

        result = insert_or_get_suggestion(mock_client, suggestion, unique_fields)

        # Should return the existing suggestion
        assert result == ("existing-456", "trace-existing-456", False)

        # Verify .eq() was called for legs_fingerprint
        eq_calls = mock_select.eq.call_args_list
        fingerprint_eq_call = [c for c in eq_calls if c[0][0] == "legs_fingerprint"]
        assert len(fingerprint_eq_call) == 1
        assert fingerprint_eq_call[0][0][1] == "fp-valid-123"


# =============================================================================
# Wave 1.3.1 Tests: Deterministic Trace ID Helpers
# =============================================================================

class TestWave131DeterministicTraceId:
    """Wave 1.3.1: Test deterministic trace ID generation."""

    def test_deterministic_supersede_trace_id_same_inputs_same_output(self):
        """Same inputs should always produce the same UUID."""
        from packages.quantum.services.workflow_orchestrator import deterministic_supersede_trace_id

        trace_id_1 = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        trace_id_2 = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        assert trace_id_1 == trace_id_2

    def test_deterministic_supersede_trace_id_different_strategy_different_output(self):
        """Different new_strategy should produce different UUID."""
        from packages.quantum.services.workflow_orchestrator import deterministic_supersede_trace_id

        trace_id_salvage = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        trace_id_lottery = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            old_strategy="take_profit_limit",
            new_strategy="lottery_trap"
        )

        assert trace_id_salvage != trace_id_lottery

    def test_deterministic_supersede_trace_id_valid_uuid_format(self):
        """Should return a valid UUID string."""
        from packages.quantum.services.workflow_orchestrator import deterministic_supersede_trace_id
        import uuid

        trace_id = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint="fp-abc123",
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        # Should be valid UUID format
        parsed = uuid.UUID(trace_id)
        assert str(parsed) == trace_id

    def test_deterministic_supersede_trace_id_handles_none_fingerprint(self):
        """Should handle None fingerprint gracefully with 'nofp' fallback."""
        from packages.quantum.services.workflow_orchestrator import deterministic_supersede_trace_id

        trace_id_1 = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint=None,  # None fingerprint
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        trace_id_2 = deterministic_supersede_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            legs_fingerprint=None,
            old_strategy="take_profit_limit",
            new_strategy="salvage_exit"
        )

        # Should be stable even with None fingerprint
        assert trace_id_1 == trace_id_2
        # Should be valid UUID
        import uuid
        uuid.UUID(trace_id_1)

    def test_deterministic_integrity_trace_id_same_inputs_same_output(self):
        """Integrity trace ID should be deterministic."""
        from packages.quantum.services.workflow_orchestrator import deterministic_integrity_trace_id

        trace_id_1 = deterministic_integrity_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            strategy="take_profit_limit"
        )

        trace_id_2 = deterministic_integrity_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            strategy="take_profit_limit"
        )

        assert trace_id_1 == trace_id_2


# =============================================================================
# Wave 1.3.1 Tests: Supersede Uses Deterministic Trace ID
# =============================================================================

class TestWave131SupersedeDeterministicTraceId:
    """Wave 1.3.1: Test that supersede uses deterministic trace_id when missing."""

    def test_supersede_uses_deterministic_trace_id_when_row_has_none(self):
        """
        When row.trace_id is None, supersede should use deterministic fallback,
        not a random UUID.
        """
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup query chain - row has NO trace_id
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "sugg-no-trace",
                "strategy": "take_profit_limit",
                "status": "pending",
                "trace_id": None  # Missing trace_id
            }
        ])

        # Setup update chain
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService"):
                # Call supersede twice with same parameters
                supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-123",
                    new_strategy="salvage_exit"
                )

                # Get the trace_id used in the first call
                first_call_trace_id = mock_audit_service.log_audit_event.call_args[1]["trace_id"]

        # Reset mocks and call again
        mock_audit_service.reset_mock()
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "sugg-no-trace",
                "strategy": "take_profit_limit",
                "status": "pending",
                "trace_id": None
            }
        ])

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService"):
                supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-123",
                    new_strategy="salvage_exit"
                )

                second_call_trace_id = mock_audit_service.log_audit_event.call_args[1]["trace_id"]

        # Both calls should have the SAME trace_id (deterministic, not random)
        assert first_call_trace_id == second_call_trace_id

        # Verify it's a valid UUID
        import uuid
        uuid.UUID(first_call_trace_id)

    def test_supersede_uses_row_trace_id_when_present(self):
        """When row has trace_id, supersede should use it (not generate)."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.in_.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {
                "id": "sugg-with-trace",
                "strategy": "take_profit_limit",
                "status": "pending",
                "trace_id": "existing-trace-uuid-123"  # Has trace_id
            }
        ])

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                supersede_prior_close_suggestions(
                    mock_client,
                    user_id="user-123",
                    cycle_date="2026-01-19",
                    window="morning_limit",
                    ticker="KURA",
                    legs_fingerprint="fp-123",
                    new_strategy="salvage_exit"
                )

                # Should use the existing trace_id from the row
                audit_trace_id = mock_audit_service.log_audit_event.call_args[1]["trace_id"]
                analytics_trace_id = mock_analytics_service.log_event.call_args[1]["trace_id"]

                assert audit_trace_id == "existing-trace-uuid-123"
                assert analytics_trace_id == "existing-trace-uuid-123"


# =============================================================================
# Wave 1.3.1 Tests: Integrity Incident Emission
# =============================================================================

class TestWave131IntegrityIncidentEmission:
    """Wave 1.3.1: Test integrity incident telemetry for missing fingerprint."""

    def test_integrity_incident_emitted_when_fingerprint_missing(self):
        """When fingerprint is missing on unique violation fallback, emit integrity incident."""
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup insert to fail with unique violation
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.side_effect = Exception("duplicate key value violates unique constraint")

        # Setup query chain for fallback
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.order.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "existing-123", "trace_id": "trace-existing"}
        ])

        suggestion = {
            "user_id": "user-123",
            "ticker": "KURA",
            "cycle_date": "2026-01-19",
            "window": "morning_limit",
            "strategy": "take_profit_limit",
            "legs_fingerprint": None,  # Missing fingerprint
        }

        unique_fields = ("user-123", "morning_limit", "2026-01-19", "KURA", "take_profit_limit", None)

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                insert_or_get_suggestion(mock_client, suggestion, unique_fields)

                # Verify audit event was emitted with event_name="integrity_incident"
                mock_audit_service.log_audit_event.assert_called_once()
                audit_kwargs = mock_audit_service.log_audit_event.call_args[1]
                assert audit_kwargs["event_name"] == "integrity_incident"
                assert audit_kwargs["payload"]["type"] == "missing_legs_fingerprint"
                assert audit_kwargs["payload"]["ticker"] == "KURA"
                assert audit_kwargs["payload"]["strategy"] == "take_profit_limit"

                # Verify analytics event was emitted with idempotency_payload
                mock_analytics_service.log_event.assert_called_once()
                analytics_kwargs = mock_analytics_service.log_event.call_args[1]
                assert analytics_kwargs["event_name"] == "integrity_incident"
                assert analytics_kwargs["category"] == "system"
                assert "idempotency_payload" in analytics_kwargs
                assert analytics_kwargs["idempotency_payload"]["type"] == "missing_legs_fingerprint"

    def test_integrity_incident_not_emitted_when_fingerprint_present(self):
        """When fingerprint is present, no integrity incident should be emitted."""
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Setup insert to fail with unique violation
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.side_effect = Exception("23505: duplicate key")

        # Setup query chain for fallback
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[
            {"id": "existing-456", "trace_id": "trace-existing-456"}
        ])

        suggestion = {
            "user_id": "user-123",
            "ticker": "KURA",
            "cycle_date": "2026-01-19",
            "window": "morning_limit",
            "strategy": "take_profit_limit",
            "legs_fingerprint": "fp-valid-123",  # Valid fingerprint
        }

        unique_fields = ("user-123", "morning_limit", "2026-01-19", "KURA", "take_profit_limit", "fp-valid-123")

        with patch("packages.quantum.services.workflow_orchestrator._emit_integrity_incident") as mock_emit:
            insert_or_get_suggestion(mock_client, suggestion, unique_fields)

            # Should NOT emit integrity incident when fingerprint is present
            mock_emit.assert_not_called()

    def test_integrity_incident_uses_deterministic_trace_id(self):
        """Integrity incident should use deterministic trace_id for forensic continuity."""
        from packages.quantum.services.workflow_orchestrator import (
            insert_or_get_suggestion,
            deterministic_integrity_trace_id
        )

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.side_effect = Exception("duplicate key")

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.order.return_value = mock_select
        mock_select.limit.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[{"id": "x", "trace_id": "t"}])

        suggestion = {
            "user_id": "user-123",
            "ticker": "KURA",
            "cycle_date": "2026-01-19",
            "window": "morning_limit",
            "strategy": "take_profit_limit",
            "legs_fingerprint": None,
        }

        unique_fields = ("user-123", "morning_limit", "2026-01-19", "KURA", "take_profit_limit", None)

        # Compute expected deterministic trace_id
        expected_trace_id = deterministic_integrity_trace_id(
            user_id="user-123",
            cycle_date="2026-01-19",
            window="morning_limit",
            ticker="KURA",
            strategy="take_profit_limit"
        )

        with patch("packages.quantum.services.workflow_orchestrator.AuditLogService") as mock_audit_cls:
            mock_audit_service = MagicMock()
            mock_audit_cls.return_value = mock_audit_service

            with patch("packages.quantum.services.workflow_orchestrator.AnalyticsService") as mock_analytics_cls:
                mock_analytics_service = MagicMock()
                mock_analytics_cls.return_value = mock_analytics_service

                insert_or_get_suggestion(mock_client, suggestion, unique_fields)

                # Verify deterministic trace_id was used
                audit_trace_id = mock_audit_service.log_audit_event.call_args[1]["trace_id"]
                analytics_trace_id = mock_analytics_service.log_event.call_args[1]["trace_id"]

                assert audit_trace_id == expected_trace_id
                assert analytics_trace_id == expected_trace_id
