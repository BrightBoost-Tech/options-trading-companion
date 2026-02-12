"""
Tests for simulate_fill behavior with missing/invalid quotes.

Verifies:
1. simulate_fill returns status="working" (not order's current status) when quote is None
2. simulate_fill returns status="working" when quote has 0/0 bid/ask
3. simulate_fill includes reason field for missing/invalid quotes
4. _process_orders_for_user transitions staged->working when simulate_fill returns "working"
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSimulateFillMissingQuote:
    """Tests for simulate_fill with missing quotes."""

    def test_none_quote_returns_working_status(self):
        """When quote is None, should return status='working', not order's status."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "working", f"Expected 'working', got '{result['status']}'"
        assert result["last_fill_qty"] == 0
        assert result["filled_qty"] == 0
        assert result.get("reason") == "missing_quote"

    def test_error_quote_returns_working_status(self):
        """When quote has error status, should return status='working'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        quote = {"status": "error", "message": "Symbol not found"}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "working"
        assert result["last_fill_qty"] == 0
        assert result.get("reason") == "missing_quote"

    def test_zero_bid_ask_returns_working_status(self):
        """When quote has 0/0 bid/ask, should return status='working'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        quote = {"bid_price": 0, "ask_price": 0}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "working"
        assert result["last_fill_qty"] == 0
        assert result.get("reason") == "invalid_quote"

    def test_zero_bid_only_returns_working_status(self):
        """When quote has 0 bid, should return status='working'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        quote = {"bid_price": 0, "ask_price": 100.5}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "working"
        assert result.get("reason") == "invalid_quote"

    def test_preserves_existing_filled_qty(self):
        """When quote is missing, should preserve existing filled_qty."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "partial",
            "requested_qty": 10,
            "filled_qty": 5,
            "avg_fill_price": 99.50,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "working"
        assert result["filled_qty"] == 5
        assert result["avg_fill_price"] == 99.50

    def test_no_fill_with_valid_quote_returns_working(self):
        """When quote is valid but no fill occurs, should return 'working' not order status."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        # Limit buy at 90 when ask is 100 - no fill expected
        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "order_type": "limit",
            "requested_price": 90.0,  # Below bid, unlikely to fill
            "side": "buy",
        }

        quote = {"bid_price": 99.0, "ask_price": 100.0}
        result = TransactionCostModel.simulate_fill(order, quote, seed=42)

        # Even if no fill, status should be "working", not "staged"
        assert result["status"] == "working", f"Expected 'working', got '{result['status']}'"

    def test_handles_alternative_quote_field_names(self):
        """Should handle 'bid'/'ask' field names in addition to 'bid_price'/'ask_price'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
        }

        # Quote with alternative field names but still 0/0
        quote = {"bid": 0, "ask": 0}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "working"
        assert result.get("reason") == "invalid_quote"


class TestProcessOrdersIntegration:
    """Integration-style tests for _process_orders_for_user with missing quotes."""

    def test_staged_order_transitions_to_working_with_none_quote(self):
        """Staged order should transition to working when quote is None."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-abc",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "SPY"},
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 450.0,
            "side": "buy",
        }

        update_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 100000}]
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
             patch("packages.quantum.paper_endpoints.PolygonService"):

            # Return None quote
            mock_fetch.return_value = None

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify update was called with working status
        assert update_mock.called, "Expected update to be called for staged->working transition"
        update_payload = update_mock.call_args[0][0]
        assert update_payload["status"] == "working"
        assert "submitted_at" in update_payload

        # Verify diagnostics show fill_status=working
        assert len(result["diagnostics"]) == 1
        assert result["diagnostics"][0]["fill_status"] == "working"

    def test_staged_order_transitions_to_working_with_invalid_quote(self):
        """Staged order should transition to working when quote is 0/0."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-xyz",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "AAPL"},
            "requested_qty": 5,
            "filled_qty": 0,
            "order_type": "market",
            "side": "buy",
        }

        update_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 100000}]
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
             patch("packages.quantum.paper_endpoints.PolygonService"):

            # Return invalid quote (0/0)
            mock_fetch.return_value = {"bid": 0, "ask": 0, "price": None}

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify update was called with working status
        assert update_mock.called
        update_payload = update_mock.call_args[0][0]
        assert update_payload["status"] == "working"

        # Verify no errors (working status is expected, not an error)
        # Note: invalid quote causes quote_present=False in diagnostics
        assert result["diagnostics"][0]["quote_present"] is False


class TestSourceCodeVerification:
    """Verify source code changes are in place."""

    def test_simulate_fill_returns_working_for_missing_quote(self):
        """Verify source code returns 'working' for missing quote."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "execution",
            "transaction_cost_model.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Should NOT have order.get("status", "working") for missing quote case
        # Should have explicit "status": "working"
        assert '"status": "working"' in source or "'status': 'working'" in source
        assert "missing_quote" in source
        assert "invalid_quote" in source

    def test_reason_field_included(self):
        """Verify reason field is included in missing/invalid quote responses."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "execution",
            "transaction_cost_model.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"reason": "missing_quote"' in source or "'reason': 'missing_quote'" in source
        assert '"reason": "invalid_quote"' in source or "'reason': 'invalid_quote'" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
