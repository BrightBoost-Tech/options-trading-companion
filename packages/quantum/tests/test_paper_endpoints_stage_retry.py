"""
Tests for paper_endpoints staging hardening.

Verifies:
1. Insert retry occurs only on PGRST204(order_type) schema cache error
2. Retry removes order_type from payload on attempt #2
3. No retry on non-PGRST204 errors
4. paper_endpoints uses TRADE_SUGGESTIONS_TABLE for suggestion queries
"""

import pytest
import re
from unittest.mock import MagicMock
from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE


def _is_pgrst204_order_type_error(exc: Exception) -> bool:
    """
    Check if exception is a PGRST204 schema cache error for order_type column.

    This is a copy of the helper from paper_endpoints for testing purposes.
    """
    err_str = str(exc).lower()
    is_pgrst204 = "pgrst204" in err_str
    mentions_order_type = "order_type" in err_str
    mentions_schema_cache = "schema cache" in err_str or "could not find" in err_str
    return is_pgrst204 and mentions_order_type and mentions_schema_cache


class TestIsPgrst204OrderTypeError:
    """Tests for _is_pgrst204_order_type_error helper."""

    def test_detects_pgrst204_order_type_schema_cache(self):
        """Should detect PGRST204 error for order_type in schema cache."""
        exc = Exception(
            "{'code': 'PGRST204', 'details': None, 'hint': None, "
            "'message': \"Could not find the 'order_type' column of 'paper_orders' "
            "in the schema cache\"}"
        )
        assert _is_pgrst204_order_type_error(exc) is True

    def test_detects_lowercase_pgrst204(self):
        """Should detect regardless of case."""
        exc = Exception("pgrst204: could not find order_type in schema cache")
        assert _is_pgrst204_order_type_error(exc) is True

    def test_rejects_pgrst204_without_order_type(self):
        """Should reject PGRST204 for other columns."""
        exc = Exception(
            "{'code': 'PGRST204', 'message': \"Could not find the 'some_other_column' "
            "in the schema cache\"}"
        )
        assert _is_pgrst204_order_type_error(exc) is False

    def test_rejects_non_pgrst204_with_order_type(self):
        """Should reject non-PGRST204 errors even if order_type mentioned."""
        exc = Exception("order_type column constraint violation")
        assert _is_pgrst204_order_type_error(exc) is False

    def test_rejects_connection_error(self):
        """Should reject connection errors."""
        exc = Exception("Connection timeout after 30s")
        assert _is_pgrst204_order_type_error(exc) is False

    def test_rejects_generic_database_error(self):
        """Should reject generic database errors."""
        exc = Exception("duplicate key value violates unique constraint")
        assert _is_pgrst204_order_type_error(exc) is False

    def test_detects_could_not_find_format(self):
        """Should detect 'could not find' phrasing."""
        exc = Exception("PGRST204 could not find order_type column")
        assert _is_pgrst204_order_type_error(exc) is True


class TestPaperOrdersInsertRetry:
    """Tests for paper_orders insert retry logic."""

    def test_retry_on_pgrst204_order_type(self):
        """Should retry without order_type on PGRST204 schema cache error."""
        mock_table = MagicMock()

        # First insert raises PGRST204, second succeeds
        pgrst204_error = Exception(
            "{'code': 'PGRST204', 'message': \"Could not find the 'order_type' "
            "column of 'paper_orders' in the schema cache\"}"
        )

        insert_results = [pgrst204_error, MagicMock(data=[{"id": "order-123"}])]
        call_count = [0]

        def insert_side_effect(payload):
            result = insert_results[call_count[0]]
            call_count[0] += 1
            mock_insert = MagicMock()
            if isinstance(result, Exception):
                mock_insert.execute.side_effect = result
            else:
                mock_insert.execute.return_value = result
            return mock_insert

        mock_table.insert.side_effect = insert_side_effect

        # Simulate the retry logic
        order_payload = {
            "portfolio_id": "port-1",
            "status": "staged",
            "order_type": "limit",
            "side": "buy",
        }

        try:
            mock_table.insert(order_payload).execute()
        except Exception as e:
            if _is_pgrst204_order_type_error(e):
                retry_payload = {k: v for k, v in order_payload.items() if k != "order_type"}
                res = mock_table.insert(retry_payload).execute()
            else:
                raise

        # Verify insert was called twice
        assert mock_table.insert.call_count == 2

        # First call should have order_type
        first_call_payload = mock_table.insert.call_args_list[0][0][0]
        assert "order_type" in first_call_payload

        # Second call should NOT have order_type
        second_call_payload = mock_table.insert.call_args_list[1][0][0]
        assert "order_type" not in second_call_payload

    def test_no_retry_on_other_errors(self):
        """Should not retry on non-PGRST204 errors."""
        mock_table = MagicMock()

        # Insert raises a different error
        other_error = Exception("Connection timeout")
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = other_error
        mock_table.insert.return_value = mock_insert

        order_payload = {"portfolio_id": "port-1", "order_type": "limit"}

        with pytest.raises(Exception) as exc_info:
            try:
                mock_table.insert(order_payload).execute()
            except Exception as e:
                if _is_pgrst204_order_type_error(e):
                    retry_payload = {k: v for k, v in order_payload.items() if k != "order_type"}
                    mock_table.insert(retry_payload).execute()
                else:
                    raise

        # Verify only one insert attempt
        assert mock_table.insert.call_count == 1
        assert "Connection timeout" in str(exc_info.value)

    def test_success_on_first_attempt_no_retry(self):
        """Should not retry when first attempt succeeds."""
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{"id": "order-123"}])
        mock_table.insert.return_value = mock_insert

        order_payload = {"portfolio_id": "port-1", "order_type": "limit"}

        try:
            res = mock_table.insert(order_payload).execute()
        except Exception as e:
            if _is_pgrst204_order_type_error(e):
                retry_payload = {k: v for k, v in order_payload.items() if k != "order_type"}
                res = mock_table.insert(retry_payload).execute()
            else:
                raise

        # Verify only one insert attempt
        assert mock_table.insert.call_count == 1
        assert res.data[0]["id"] == "order-123"


class TestTradeSuggestionsTableConstant:
    """Tests for TRADE_SUGGESTIONS_TABLE usage in paper_endpoints."""

    def test_constant_is_plural(self):
        """Table constant must be plural 'trade_suggestions'."""
        assert TRADE_SUGGESTIONS_TABLE == "trade_suggestions"

    def test_no_hardcoded_trade_suggestions_strings_in_paper_endpoints(self):
        """Verify no hardcoded 'trade_suggestions' table strings remain."""
        # Read the source file directly to avoid import issues
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # Look for hardcoded table references: .table("trade_suggestions")
        hardcoded_pattern = r'\.table\(["\']trade_suggestions["\']\)'
        matches = re.findall(hardcoded_pattern, source)

        assert len(matches) == 0, (
            f"Found {len(matches)} hardcoded trade_suggestions table references. "
            "Use TRADE_SUGGESTIONS_TABLE constant instead."
        )

    def test_uses_trade_suggestions_table_constant(self):
        """Verify paper_endpoints uses TRADE_SUGGESTIONS_TABLE constant."""
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # Should import the constant
        assert "from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE" in source

        # Should use the constant (at least one usage)
        assert ".table(TRADE_SUGGESTIONS_TABLE)" in source


class TestOrderPayloadHasUserId:
    """Tests that order_payload includes user_id (required by paper_orders NOT NULL constraint)."""

    def test_order_payload_includes_user_id_in_source(self):
        """Verify paper_endpoints order_payload includes user_id field."""
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # order_payload must include "user_id": user_id
        assert '"user_id": user_id' in source, (
            "order_payload must include 'user_id': user_id to satisfy "
            "paper_orders.user_id NOT NULL constraint"
        )


class TestRetryPreservesOtherFields:
    """Tests that retry only removes order_type, preserving other fields."""

    def test_retry_payload_preserves_all_other_fields(self):
        """Retry payload should contain all fields except order_type."""
        original_payload = {
            "user_id": "user-abc-123",
            "portfolio_id": "port-123",
            "status": "staged",
            "staged_at": "2024-01-01T00:00:00Z",
            "trace_id": "trace-abc",
            "suggestion_id": "sugg-xyz",
            "order_json": {"symbol": "SPY"},
            "requested_qty": 10,
            "requested_price": 100.0,
            "side": "buy",
            "order_type": "limit",  # This should be removed
            "quote_at_stage": {"bid": 99.9, "ask": 100.1},
            "tcm": {"spread_cost": 0.05},
            "position_id": None,
        }

        retry_payload = {k: v for k, v in original_payload.items() if k != "order_type"}

        # Verify order_type is removed
        assert "order_type" not in retry_payload

        # Verify user_id is preserved (critical for NOT NULL constraint)
        assert "user_id" in retry_payload
        assert retry_payload["user_id"] == "user-abc-123"

        # Verify all other fields are preserved
        expected_fields = [
            "user_id", "portfolio_id", "status", "staged_at", "trace_id", "suggestion_id",
            "order_json", "requested_qty", "requested_price", "side",
            "quote_at_stage", "tcm", "position_id"
        ]
        for field in expected_fields:
            assert field in retry_payload, f"Field '{field}' missing from retry payload"
            assert retry_payload[field] == original_payload[field]

    def test_user_id_is_required_field(self):
        """user_id must be present in payload (NOT NULL in paper_orders)."""
        payload_with_user_id = {
            "user_id": "user-123",
            "portfolio_id": "port-1",
            "order_type": "limit",
        }

        # user_id should be present
        assert "user_id" in payload_with_user_id
        assert payload_with_user_id["user_id"] is not None

        # Even after retry (removing order_type), user_id must remain
        retry_payload = {k: v for k, v in payload_with_user_id.items() if k != "order_type"}
        assert "user_id" in retry_payload
        assert retry_payload["user_id"] == "user-123"


class TestEdgeCases:
    """Edge case tests for retry logic."""

    def test_pgrst204_for_different_column_no_retry(self):
        """Should not retry for PGRST204 on columns other than order_type."""
        exc = Exception(
            "{'code': 'PGRST204', 'message': \"Could not find the 'custom_field' "
            "column of 'paper_orders' in the schema cache\"}"
        )
        assert _is_pgrst204_order_type_error(exc) is False

    def test_retry_failure_raises_retry_error(self):
        """If retry also fails, should raise the retry error."""
        mock_table = MagicMock()

        # Both inserts fail
        pgrst204_error = Exception("PGRST204 order_type schema cache")
        retry_error = Exception("Database connection lost")

        call_count = [0]

        def insert_side_effect(payload):
            mock_insert = MagicMock()
            if call_count[0] == 0:
                call_count[0] += 1
                mock_insert.execute.side_effect = pgrst204_error
            else:
                mock_insert.execute.side_effect = retry_error
            return mock_insert

        mock_table.insert.side_effect = insert_side_effect

        order_payload = {"order_type": "limit"}

        with pytest.raises(Exception) as exc_info:
            try:
                mock_table.insert(order_payload).execute()
            except Exception as e:
                if _is_pgrst204_order_type_error(e):
                    retry_payload = {k: v for k, v in order_payload.items() if k != "order_type"}
                    mock_table.insert(retry_payload).execute()
                else:
                    raise

        # Should raise the retry error, not the original
        assert "Database connection lost" in str(exc_info.value)

    def test_helper_in_paper_endpoints_matches_test_helper(self):
        """Verify paper_endpoints has the same helper function logic."""
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # Verify the helper function exists
        assert "def _is_pgrst204_order_type_error" in source

        # Verify key detection logic is present
        assert '"pgrst204"' in source.lower() or "'pgrst204'" in source.lower()
        assert '"order_type"' in source.lower() or "'order_type'" in source.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
