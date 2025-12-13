import pytest
from unittest.mock import MagicMock
from packages.quantum.services.paper_execution_service import PaperExecutionService
from packages.quantum.models import TradeTicket

def test_paper_execution_lifecycle():
    mock_supabase = MagicMock()

    # Mock Data
    staged_order = {
        "id": "order-1",
        "status": "staged",
        "portfolio_id": "port-1",
        "order_json": {"limit_price": 100.0, "quantity": 10, "symbol": "TEST", "action": "Buy"}
    }

    portfolio_data = {"id": "port-1", "cash_balance": 100000.0}

    # Specific Mocks per table
    orders_mock = MagicMock()
    portfolios_mock = MagicMock()
    positions_mock = MagicMock()

    def table_side_effect(name):
        if name == "paper_orders": return orders_mock
        if name == "paper_portfolios": return portfolios_mock
        if name == "paper_positions": return positions_mock
        return MagicMock()

    mock_supabase.table.side_effect = table_side_effect

    # 1. Stage Order Setup
    orders_mock.insert.return_value.execute.return_value.data = [staged_order]

    svc = PaperExecutionService(mock_supabase)
    ticket = TradeTicket(symbol="TEST", quantity=10, limit_price=100.0, order_type="limit", action="Buy")

    # Act 1
    order, ctx = svc.stage_order("user-1", ticket, "port-1")
    assert order["status"] == "staged"
    assert ctx.trace_id is not None

    # 2. Process Order Setup
    # Fetch order
    orders_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = staged_order

    # Update order (return value doesn't matter much but nice to have)
    orders_mock.update.return_value.eq.return_value.execute.return_value.data = [{**staged_order, "status": "filled"}]

    # Fetch portfolio
    portfolios_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = portfolio_data

    # Fetch positions (empty)
    positions_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    # Act 2
    result = svc.process_order(order["id"], "user-1")

    assert result["status"] == "filled"
    assert result["filled_quantity"] == 10
    # Slippage should be applied
    assert result["slippage"] >= 0
    # Commission should be applied
    assert result["commission"] > 0

    # Verify calls
    # Should have updated portfolio cash
    portfolios_mock.update.assert_called()
    # Should have inserted position
    positions_mock.insert.assert_called()
