"""
Tests for orphan filled paper order repair functionality.

Verifies:
1. Orphan filled orders (status='filled', position_id=None, filled_qty>0) are detected
2. Repair creates paper_positions with user_id
3. Repair updates paper_orders.position_id
4. Ledger insert is deduped by order_id (2nd run does not insert again)
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


class TestRepairFilledOrderCommit:
    """Tests for _repair_filled_order_commit helper function."""

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_creates_position_with_user_id(self):
        """Repair should create a paper_position with user_id."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        # Mock: no existing position
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        # Mock: no existing ledger entry
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        # Mock: position insert
        insert_mock = MagicMock()
        insert_mock.return_value.execute.return_value = MagicMock(
            data=[{"id": "pos-new-123"}]
        )

        # Track calls
        call_tracker = {}

        def table_side_effect(table_name):
            mock_table = MagicMock()
            call_tracker[table_name] = call_tracker.get(table_name, [])

            if table_name == "paper_positions":
                # For select (no existing position)
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                # For insert
                mock_table.insert = insert_mock
            elif table_name == "paper_orders":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_ledger":
                # For select (no existing ledger)
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                # For insert
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = {
            "id": "order-orphan-1",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 10,
            "avg_fill_price": 150.0,
            "fees_usd": 1.30,
            "side": "buy",
            "order_json": {
                "symbol": "SPY",
                "order_type": "limit",
                "quantity": 10,
                "limit_price": 150.0,
                "legs": [{"action": "buy", "symbol": "SPY", "quantity": 10}]
            },
            "trace_id": "trace-123"
        }

        portfolio = {
            "id": "port-1",
            "cash_balance": 100000.0
        }

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-456", order, portfolio)

        # Verify repair succeeded
        assert result["repaired"] is True
        assert result["position_id"] == "pos-new-123"
        assert result["ledger_inserted"] is True

        # Verify insert was called with user_id
        assert insert_mock.called
        pos_payload = insert_mock.call_args[0][0]
        assert pos_payload["user_id"] == "user-456"
        assert pos_payload["portfolio_id"] == "port-1"
        assert pos_payload["symbol"] == "SPY"
        assert pos_payload["quantity"] == 10.0  # Buy = positive

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_updates_order_position_id(self):
        """Repair should update paper_orders.position_id."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        order_update_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_positions":
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "pos-new-456"}]
                )
            elif table_name == "paper_orders":
                mock_table.update = order_update_mock
                order_update_mock.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_ledger":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = {
            "id": "order-orphan-2",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 5,
            "avg_fill_price": 175.0,
            "fees_usd": 0.65,
            "side": "buy",
            "order_json": {
                "symbol": "AAPL",
                "order_type": "limit",
                "quantity": 5,
                "limit_price": 175.0,
                "legs": [{"action": "buy", "symbol": "AAPL", "quantity": 5}]
            }
        }

        portfolio = {"id": "port-1", "cash_balance": 50000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-789", order, portfolio)

        # Verify order was updated with position_id
        assert order_update_mock.called
        update_payload = order_update_mock.call_args[0][0]
        assert update_payload["position_id"] == "pos-new-456"

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_dedupes_ledger_insert(self):
        """Repair should not insert ledger if one already exists for order_id."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        ledger_insert_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_positions":
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "pos-existing"}]
                )
            elif table_name == "paper_orders":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_ledger":
                # Return existing ledger entry
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-existing"}]
                )
                mock_table.insert = ledger_insert_mock
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = {
            "id": "order-orphan-3",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 3,
            "avg_fill_price": 200.0,
            "fees_usd": 0.39,
            "side": "sell",
            "order_json": {
                "symbol": "MSFT",
                "order_type": "limit",
                "quantity": 3,
                "limit_price": 200.0,
                "legs": [{"action": "sell", "symbol": "MSFT", "quantity": 3}]
            }
        }

        portfolio = {"id": "port-1", "cash_balance": 75000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-111", order, portfolio)

        # Verify repair succeeded
        assert result["repaired"] is True
        # Verify ledger insert was NOT called (deduped)
        assert result["ledger_inserted"] is False
        assert not ledger_insert_mock.called

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_handles_sell_order_negative_qty(self):
        """Repair should handle sell orders with negative quantity."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        insert_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_positions":
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert = insert_mock
                insert_mock.return_value.execute.return_value = MagicMock(
                    data=[{"id": "pos-sell"}]
                )
            elif table_name == "paper_orders":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_ledger":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = {
            "id": "order-sell-1",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 5,
            "avg_fill_price": 100.0,
            "fees_usd": 0.65,
            "side": "sell",  # Sell order
            "order_json": {
                "symbol": "QQQ",
                "order_type": "limit",
                "quantity": 5,
                "limit_price": 100.0,
                "legs": [{"action": "sell", "symbol": "QQQ", "quantity": 5}]
            }
        }

        portfolio = {"id": "port-1", "cash_balance": 50000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-222", order, portfolio)

        # Verify position quantity is negative for sell
        pos_payload = insert_mock.call_args[0][0]
        assert pos_payload["quantity"] == -5.0  # Sell = negative


class TestOrphanOrderDetection:
    """Tests for orphan order detection in processing loop."""

    def test_source_code_includes_orphan_query(self):
        """Verify orphan order query is in source code."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Should have query for filled orders with null position_id
        assert 'eq("status", "filled")' in source
        assert 'is_("position_id", "null")' in source

    def test_source_code_includes_repair_check(self):
        """Verify repair check is in the processing loop."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Should have check for orphan filled orders
        assert '_repair_filled_order_commit' in source
        assert 'order.get("status") == "filled"' in source
        assert 'order.get("position_id") is None' in source

    def test_source_code_includes_ledger_dedupe(self):
        """Verify ledger dedupe check is in repair function."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Should check for existing ledger before insert
        assert 'existing_ledger' in source
        assert 'eq("order_id"' in source


class TestRepairFilledOrderCommitEdgeCases:
    """Edge case tests for repair functionality."""

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_skips_zero_filled_qty(self):
        """Repair should skip orders with zero filled_qty."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        order = {
            "id": "order-zero",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 0,  # Zero
            "avg_fill_price": 150.0,
            "side": "buy",
            "order_json": {"symbol": "SPY"}
        }

        portfolio = {"id": "port-1", "cash_balance": 100000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-1", order, portfolio)

        assert result["repaired"] is False

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_skips_zero_avg_fill_price(self):
        """Repair should skip orders with zero avg_fill_price."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        order = {
            "id": "order-zero-price",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 10,
            "avg_fill_price": 0,  # Zero
            "side": "buy",
            "order_json": {"symbol": "SPY"}
        }

        portfolio = {"id": "port-1", "cash_balance": 100000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-1", order, portfolio)

        assert result["repaired"] is False

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi"),
        reason="fastapi not installed"
    )
    def test_repair_updates_existing_position(self):
        """Repair should update existing position if found by strategy_key."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        position_update_mock = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_positions":
                # Return existing position
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{
                        "id": "pos-existing",
                        "quantity": 5.0,
                        "avg_entry_price": 100.0
                    }]
                )
                mock_table.update = position_update_mock
                position_update_mock.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_orders":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_ledger":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = {
            "id": "order-update-pos",
            "status": "filled",
            "position_id": None,
            "portfolio_id": "port-1",
            "filled_qty": 5,
            "avg_fill_price": 110.0,
            "fees_usd": 0.65,
            "side": "buy",
            "order_json": {
                "symbol": "SPY",
                "order_type": "limit",
                "quantity": 5,
                "limit_price": 110.0,
                "legs": [{"action": "buy", "symbol": "SPY", "quantity": 5}]
            }
        }

        portfolio = {"id": "port-1", "cash_balance": 50000.0}

        from packages.quantum.paper_endpoints import _repair_filled_order_commit
        result = _repair_filled_order_commit(mock_supabase, mock_analytics, "user-333", order, portfolio)

        # Verify position was updated (not inserted)
        assert result["repaired"] is True
        assert result["position_id"] == "pos-existing"
        assert position_update_mock.called

        # Check update payload has correct new quantity (5 + 5 = 10)
        update_call = position_update_mock.call_args[0][0]
        assert update_call["quantity"] == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
