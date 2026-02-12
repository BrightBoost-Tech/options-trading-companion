"""
Tests for paper order processing state transitions.

Verifies:
1. Orders transition staged->working even with unexpected fill_status
2. Invalid quotes (0/0) are treated as None
3. Diagnostics are recorded for each order
4. Errors include unexpected_fill_status entries
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestIsValidQuote:
    """Tests for _is_valid_quote helper function."""

    def test_valid_bid_ask_quote(self):
        """Should return True for valid bid/ask quote."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid": 100.50, "ask": 100.55}
        assert _is_valid_quote(quote) is True

    def test_valid_bid_price_ask_price_quote(self):
        """Should return True for valid bid_price/ask_price format."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid_price": 100.50, "ask_price": 100.55}
        assert _is_valid_quote(quote) is True

    def test_valid_price_only_quote(self):
        """Should return True for quote with only price field."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"price": 100.50}
        assert _is_valid_quote(quote) is True

    def test_valid_last_price_quote(self):
        """Should return True for quote with 'last' price field."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"last": 100.50}
        assert _is_valid_quote(quote) is True

    def test_invalid_zero_bid_ask(self):
        """Should return False for zero bid/ask."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid": 0, "ask": 0}
        assert _is_valid_quote(quote) is False

    def test_invalid_zero_bid_only(self):
        """Should return False when only bid is zero."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid": 0, "ask": 100.55}
        assert _is_valid_quote(quote) is False

    def test_invalid_none_values(self):
        """Should return False for None bid/ask."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid": None, "ask": None}
        assert _is_valid_quote(quote) is False

    def test_invalid_empty_quote(self):
        """Should return False for empty quote dict."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        assert _is_valid_quote({}) is False

    def test_invalid_none_quote(self):
        """Should return False for None quote."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        assert _is_valid_quote(None) is False

    def test_invalid_non_dict_quote(self):
        """Should return False for non-dict quote."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        assert _is_valid_quote("not a dict") is False
        assert _is_valid_quote(123) is False

    def test_string_numbers_converted(self):
        """Should handle string numbers correctly."""
        from packages.quantum.paper_endpoints import _is_valid_quote

        quote = {"bid": "100.50", "ask": "100.55"}
        assert _is_valid_quote(quote) is True


class TestProcessOrdersUnexpectedFillStatus:
    """Tests for handling unexpected fill_status values."""

    def test_unknown_status_transitions_staged_to_working(self):
        """When simulate_fill returns unknown, staged order should transition to working."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        # Setup portfolio query
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "port-1", "cash_balance": 10000}]
        )

        # Setup orders query - return one staged order
        staged_order = {
            "id": "order-123",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "SPY"},
        }

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 10000}]
                )
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        # Mock quote fetch to return invalid quote
        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.TransactionCostModel") as mock_tcm, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            # Return invalid quote (0/0)
            mock_fetch.return_value = {"bid": 0, "ask": 0}

            # simulate_fill returns unknown status
            mock_tcm.simulate_fill.return_value = {
                "status": "unknown",
                "last_fill_qty": 0,
            }

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify staged->working transition was attempted
        update_calls = [
            call for call in mock_supabase.table.return_value.update.call_args_list
            if call[0][0].get("status") == "working"
        ]
        # The update should have been called
        assert mock_supabase.table.return_value.update.called

        # Verify diagnostics include the order
        assert len(result["diagnostics"]) == 1
        assert result["diagnostics"][0]["order_id"] == "order-123"
        assert result["diagnostics"][0]["fill_status"] == "unknown"

        # Verify errors include unexpected_fill_status
        assert len(result["errors"]) == 1
        assert result["errors"][0]["reason"] == "unexpected_fill_status"
        assert result["errors"][0]["order_id"] == "order-123"

    def test_rejected_status_transitions_staged_to_working(self):
        """When simulate_fill returns 'rejected', staged order should still transition."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-456",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "AAPL"},
        }

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 10000}]
                )
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.TransactionCostModel") as mock_tcm, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            mock_fetch.return_value = {"bid": 100, "ask": 101}
            mock_tcm.simulate_fill.return_value = {
                "status": "rejected",
                "last_fill_qty": 0,
            }

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify error recorded with reason
        assert len(result["errors"]) == 1
        assert result["errors"][0]["reason"] == "unexpected_fill_status"
        assert result["errors"][0]["fill_status"] == "rejected"


class TestProcessOrdersInvalidQuote:
    """Tests for handling invalid quotes (0/0)."""

    def test_zero_quote_treated_as_none(self):
        """Invalid quote (0/0) should be treated as None."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-789",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "SPY"},
        }

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 10000}]
                )
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.TransactionCostModel") as mock_tcm, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            # Return invalid quote
            mock_fetch.return_value = {"bid": 0, "ask": 0}

            # Mock will receive None quote due to validation
            mock_tcm.simulate_fill.return_value = {
                "status": "working",
                "last_fill_qty": 0,
            }

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify diagnostic shows quote_present=False (invalid treated as missing)
        assert len(result["diagnostics"]) == 1
        assert result["diagnostics"][0]["quote_present"] is False

        # Verify no errors for working status
        assert len(result["errors"]) == 0


class TestProcessOrdersWorkingStatus:
    """Tests for normal working status handling."""

    def test_working_status_transitions_staged_to_working(self):
        """When simulate_fill returns working, staged order should transition."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-abc",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "MSFT"},
        }

        update_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 10000}]
                )
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update = update_mock
                update_mock.return_value.eq.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.TransactionCostModel") as mock_tcm, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            mock_fetch.return_value = {"bid": 150.50, "ask": 150.55}
            mock_tcm.simulate_fill.return_value = {
                "status": "working",
                "last_fill_qty": 0,
            }

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify update was called with working status
        assert update_mock.called
        update_payload = update_mock.call_args[0][0]
        assert update_payload["status"] == "working"
        assert "submitted_at" in update_payload

        # Verify no errors for normal working status
        assert len(result["errors"]) == 0


class TestProcessOrdersDiagnostics:
    """Tests for diagnostics in return payload."""

    def test_diagnostics_always_populated(self):
        """Diagnostics should always be a list, even when empty."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        # No portfolios = no orders to process
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        from packages.quantum.paper_endpoints import _process_orders_for_user
        result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify diagnostics is a list (not None)
        assert result["diagnostics"] == []
        assert result["errors"] == []

    def test_diagnostics_contains_all_order_fields(self):
        """Each diagnostic entry should have required fields."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-diag",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "GOOGL"},
        }

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 10000}]
                )
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.TransactionCostModel") as mock_tcm, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            mock_fetch.return_value = {"bid": 2800, "ask": 2801}
            mock_tcm.simulate_fill.return_value = {
                "status": "working",
                "last_fill_qty": 0,
            }

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify diagnostic has all required fields
        assert len(result["diagnostics"]) == 1
        diag = result["diagnostics"][0]
        assert "order_id" in diag
        assert "symbol" in diag
        assert "fill_status" in diag
        assert "quote_present" in diag
        assert "last_fill_qty" in diag

        assert diag["order_id"] == "order-diag"
        assert diag["symbol"] == "GOOGL"
        assert diag["fill_status"] == "working"
        assert diag["quote_present"] is True
        assert diag["last_fill_qty"] == 0


class TestSourceCodeVerification:
    """Source code verification tests."""

    def test_is_valid_quote_function_exists(self):
        """Verify _is_valid_quote function exists in paper_endpoints."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "def _is_valid_quote" in source
        assert "bid" in source and "ask" in source

    def test_diagnostics_field_in_result(self):
        """Verify diagnostics field is initialized in result dict."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"diagnostics": []' in source or "'diagnostics': []" in source

    def test_unexpected_fill_status_handling(self):
        """Verify unexpected fill_status handling exists."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "unexpected_fill_status" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
