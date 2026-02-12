"""
Tests for TCM simulate_fill missing-quote fallback behavior.

Verifies:
1. Missing/invalid quotes never return status="staged"
2. Deterministic fill draw based on order_id + date bucket
3. TCM precomputed values (fill_probability, expected_fill_price) are used
4. Processing transitions staged->working and commits fills correctly
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestDeterministicFillDraw:
    """Tests for _compute_deterministic_fill_draw helper."""

    def test_same_order_same_day_same_result(self):
        """Same order_id + date should produce same draw."""
        from packages.quantum.execution.transaction_cost_model import _compute_deterministic_fill_draw

        draw1 = _compute_deterministic_fill_draw("order-123", "2025-01-15")
        draw2 = _compute_deterministic_fill_draw("order-123", "2025-01-15")

        assert draw1 == draw2

    def test_different_order_different_result(self):
        """Different order_ids should produce different draws."""
        from packages.quantum.execution.transaction_cost_model import _compute_deterministic_fill_draw

        draw1 = _compute_deterministic_fill_draw("order-123", "2025-01-15")
        draw2 = _compute_deterministic_fill_draw("order-456", "2025-01-15")

        assert draw1 != draw2

    def test_different_day_different_result(self):
        """Same order on different days should produce different draws."""
        from packages.quantum.execution.transaction_cost_model import _compute_deterministic_fill_draw

        draw1 = _compute_deterministic_fill_draw("order-123", "2025-01-15")
        draw2 = _compute_deterministic_fill_draw("order-123", "2025-01-16")

        assert draw1 != draw2

    def test_draw_in_valid_range(self):
        """Draw should be in [0, 1) range."""
        from packages.quantum.execution.transaction_cost_model import _compute_deterministic_fill_draw

        for i in range(100):
            draw = _compute_deterministic_fill_draw(f"order-{i}", "2025-01-15")
            assert 0 <= draw < 1


class TestSimulateFillMissingQuoteFallback:
    """Tests for simulate_fill with missing/invalid quotes using fallback."""

    def test_none_quote_never_returns_staged(self):
        """When quote is None, status must be 'working' or 'filled', never 'staged'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-test-1",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 0.5,
                "expected_fill_price": 99.50,
            },
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] in ("working", "filled"), f"Got status={result['status']}, expected working or filled"
        assert result["status"] != "staged"
        assert result.get("reason") == "missing_quote_fallback"

    def test_invalid_quote_never_returns_staged(self):
        """When quote has 0/0 bid/ask, status must be 'working' or 'filled'."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-test-2",
            "status": "staged",
            "requested_qty": 5,
            "filled_qty": 0,
            "order_type": "market",
            "side": "buy",
            "tcm": {
                "fill_probability": 0.8,
                "expected_fill_price": 150.0,
            },
        }

        quote = {"bid_price": 0, "ask_price": 0, "price": None}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] in ("working", "filled")
        assert result["status"] != "staged"
        assert result.get("reason") == "missing_quote_fallback"
        assert result.get("fallback_source") == "invalid_quote"

    def test_high_fill_probability_results_in_filled(self):
        """With high fill_probability, deterministic draw should result in filled."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        # Use a known order_id that will produce a low draw value
        # We set fill_probability=1.0 to guarantee fill
        order = {
            "id": "order-high-prob",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 1.0,  # 100% fill
                "expected_fill_price": 99.50,
            },
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        assert result["filled_qty"] == 10
        assert result["avg_fill_price"] == 99.50
        assert result["last_fill_qty"] == 10

    def test_zero_fill_probability_results_in_working(self):
        """With zero fill_probability, should always return working."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-zero-prob",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 0.0,  # 0% fill
                "expected_fill_price": 99.50,
            },
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "working"
        assert result["last_fill_qty"] == 0

    def test_uses_tcm_expected_fill_price(self):
        """Should use tcm.expected_fill_price for fill price."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-price-test",
            "status": "staged",
            "requested_qty": 5,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 100.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 1.0,
                "expected_fill_price": 98.75,  # Specific price
            },
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        assert result["avg_fill_price"] == 98.75
        assert result["last_fill_price"] == 98.75

    def test_fallback_to_requested_price_when_tcm_missing(self):
        """Should fallback to requested_price if tcm.expected_fill_price is missing."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-no-tcm",
            "status": "staged",
            "requested_qty": 5,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 105.50,
            "side": "buy",
            "tcm": {
                "fill_probability": 1.0,
                # No expected_fill_price
            },
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        assert result["avg_fill_price"] == 105.50

    def test_includes_deterministic_draw_in_response(self):
        """Response should include the deterministic draw value for debugging."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-draw-test",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "tcm": {"fill_probability": 0.5, "expected_fill_price": 100.0},
        }

        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert "deterministic_draw" in result
        assert 0 <= result["deterministic_draw"] < 1
        assert "fill_probability_used" in result

    def test_error_quote_uses_fallback(self):
        """Quote with status='error' should use fallback logic."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-error-quote",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "tcm": {"fill_probability": 1.0, "expected_fill_price": 100.0},
        }

        quote = {"status": "error", "message": "Symbol not found"}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "filled"
        assert result.get("reason") == "missing_quote_fallback"
        assert result.get("fallback_source") == "missing_quote"


class TestSimulateFillValidQuoteUnchanged:
    """Tests to ensure valid quote behavior is unchanged."""

    def test_valid_quote_market_order_fills(self):
        """Valid quote with market order should fill normally."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-market",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "market",
            "side": "buy",
        }

        quote = {"bid_price": 99.0, "ask_price": 100.0}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "filled"
        assert result["filled_qty"] == 10
        # Should use ask price for buy market order (with slippage)
        assert result["avg_fill_price"] > 0

    def test_valid_quote_limit_order_no_fill(self):
        """Valid quote with unfavorable limit should return working."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "order-limit-nofill",
            "status": "staged",
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 90.0,  # Below bid, won't fill
            "side": "buy",
        }

        quote = {"bid_price": 99.0, "ask_price": 100.0}
        result = TransactionCostModel.simulate_fill(order, quote, seed=999)

        assert result["status"] == "working"
        assert result["filled_qty"] == 0


class TestProcessOrdersWithFallback:
    """Integration tests for _process_orders_for_user with fallback fills."""

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_staged_order_transitions_on_missing_quote(self):
        """Staged order should transition to working or filled on missing quote."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-transition-test",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "SPY"},
            "requested_qty": 10,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 450.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 0.0,  # Force working status
                "expected_fill_price": 449.50,
            },
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

            mock_fetch.return_value = None  # Missing quote

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify transition occurred
        assert update_mock.called
        update_payload = update_mock.call_args[0][0]
        assert update_payload["status"] == "working"

        # Verify diagnostics
        assert len(result["diagnostics"]) == 1
        assert result["diagnostics"][0]["fill_status"] == "working"

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_fill_commits_position_when_deterministic_fill(self):
        """When deterministic draw results in fill, should commit and create position."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        staged_order = {
            "id": "order-fill-commit",
            "status": "staged",
            "portfolio_id": "port-1",
            "order_json": {"symbol": "AAPL"},
            "requested_qty": 5,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": 175.0,
            "side": "buy",
            "tcm": {
                "fill_probability": 1.0,  # Force fill
                "expected_fill_price": 174.50,
            },
        }

        portfolio = {"id": "port-1", "cash_balance": 100000}

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[portfolio]
                )
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_orders":
                mock_query = MagicMock()
                mock_query.select.return_value.in_.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[staged_order]
                )
                mock_table.select = mock_query.select
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_positions":
                mock_table.upsert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "pos-new"}]
                )
            elif table_name == "learning_feedback_loops":
                mock_table.insert.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch("packages.quantum.paper_endpoints._fetch_quote_with_retry") as mock_fetch, \
             patch("packages.quantum.paper_endpoints.PolygonService"):

            mock_fetch.return_value = None  # Missing quote, will use fallback

            from packages.quantum.paper_endpoints import _process_orders_for_user
            result = _process_orders_for_user(mock_supabase, mock_analytics, "user-1")

        # Verify fill was processed
        assert result["processed"] == 1

        # Verify diagnostics show filled status
        assert result["diagnostics"][0]["fill_status"] == "filled"
        assert result["diagnostics"][0]["last_fill_qty"] == 5


class TestSourceCodeVerification:
    """Verify source code changes."""

    def test_deterministic_fill_draw_exists(self):
        """Verify _compute_deterministic_fill_draw function exists."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "execution",
            "transaction_cost_model.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "_compute_deterministic_fill_draw" in source
        assert "sha256" in source
        assert "order_id" in source

    def test_fallback_logic_uses_tcm(self):
        """Verify fallback logic uses TCM precomputed values."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "execution",
            "transaction_cost_model.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "fill_probability" in source
        assert "expected_fill_price" in source
        assert "missing_quote_fallback" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
