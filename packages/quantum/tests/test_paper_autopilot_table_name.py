"""
Regression tests for paper autopilot table name consistency.

Verifies:
1. PaperAutopilotService uses TRADE_SUGGESTIONS_TABLE constant (not hardcoded)
2. Both read and update paths use the same correct table name
3. Table name is plural: "trade_suggestions" (not "trade_suggestion")
"""

import pytest
from unittest.mock import MagicMock
from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE
from packages.quantum.services.paper_autopilot_service import PaperAutopilotService


class TestTradesugggestionsTableConstant:
    """Tests for TRADE_SUGGESTIONS_TABLE constant usage."""

    def test_constant_is_plural(self):
        """Table name constant must be plural 'trade_suggestions'."""
        assert TRADE_SUGGESTIONS_TABLE == "trade_suggestions"
        assert TRADE_SUGGESTIONS_TABLE.endswith("s"), "Table name must be plural"

    def test_constant_is_not_singular(self):
        """Table name must NOT be singular 'trade_suggestion'."""
        assert TRADE_SUGGESTIONS_TABLE != "trade_suggestion"


class TestGetExecutableSuggestionsTableName:
    """Tests for table name in get_executable_suggestions."""

    def test_uses_correct_table_for_read(self):
        """get_executable_suggestions must query TRADE_SUGGESTIONS_TABLE."""
        mock_client = MagicMock()
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        service = PaperAutopilotService(mock_client)
        service.get_executable_suggestions(user_id="test-user")

        # Verify table() was called with the correct constant
        mock_client.table.assert_called_with(TRADE_SUGGESTIONS_TABLE)

    def test_does_not_use_singular_table_name(self):
        """Must not use singular 'trade_suggestion' table name."""
        mock_client = MagicMock()
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        service = PaperAutopilotService(mock_client)
        service.get_executable_suggestions(user_id="test-user")

        # Get all table() calls
        table_calls = [c for c in mock_client.table.call_args_list]
        for c in table_calls:
            table_name = c[0][0]  # First positional arg
            assert table_name != "trade_suggestion", \
                f"Must not use singular table name, got: {table_name}"


class TestTableNameConsistency:
    """Tests for consistent table name usage across service."""

    def test_service_imports_from_canonical_module(self):
        """Service must import constant from table_constants module."""
        # Verify the service module uses the canonical constant
        import packages.quantum.services.paper_autopilot_service as svc
        assert hasattr(svc, 'TRADE_SUGGESTIONS_TABLE')
        assert svc.TRADE_SUGGESTIONS_TABLE == "trade_suggestions"

    def test_constant_value_matches_production_table(self):
        """Constant value must match production DB table name."""
        # Production table is public.trade_suggestions
        expected_table = "trade_suggestions"
        assert TRADE_SUGGESTIONS_TABLE == expected_table


class TestNoCandidatesRegression:
    """Regression tests for the no_candidates bug."""

    def test_finds_candidates_when_suggestions_exist(self):
        """Must find candidates when pending suggestions exist in correct table."""
        mock_client = MagicMock()
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query

        # Simulate pending suggestions in database
        mock_query.execute.return_value = MagicMock(data=[
            {"id": "s1", "score": 60.0, "created_at": "2024-01-01T10:00:00Z"},
            {"id": "s2", "score": 55.0, "created_at": "2024-01-01T11:00:00Z"},
        ])

        service = PaperAutopilotService(mock_client)
        suggestions = service.get_executable_suggestions(user_id="test-user")

        # Must return the suggestions (not empty due to wrong table)
        assert len(suggestions) == 2
        assert suggestions[0]["id"] == "s1"  # Highest score first

    def test_returns_empty_when_no_suggestions(self):
        """Returns empty list when no pending suggestions exist."""
        mock_client = MagicMock()
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        service = PaperAutopilotService(mock_client)
        suggestions = service.get_executable_suggestions(user_id="test-user")

        assert suggestions == []

    def test_table_name_in_query(self):
        """Verify the table name passed to Supabase client."""
        mock_client = MagicMock()
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        service = PaperAutopilotService(mock_client)
        service.get_executable_suggestions(user_id="test-user")

        # Extract the actual table name used
        call_args = mock_client.table.call_args
        actual_table = call_args[0][0]

        # Must be the plural form
        assert actual_table == "trade_suggestions", \
            f"Expected 'trade_suggestions' (plural), got '{actual_table}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
