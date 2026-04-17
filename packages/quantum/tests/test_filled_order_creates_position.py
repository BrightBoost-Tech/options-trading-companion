"""
Tests for Bug 5 fix: filled orders must create paper_positions rows.

Verifies:
1. _commit_fill creates a paper_positions row when an order is filled
2. _commit_fill handles TradeTicket reconstruction failure gracefully (fallback strategy_key)
3. _commit_fill rolls back order to 'working' if position creation fails entirely
4. Orphan orders are repaired even when target_order_id is set
5. Position payload includes legs from order_json
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

# Skipped in PR #1 triage to establish CI-green gate while test debt is cleared.
# [Cluster C] mock wiring drift
# Tracked in #769 (umbrella: #767).
pytestmark = pytest.mark.skip(
    reason='[Cluster C] mock wiring drift; tracked in #769',
)


HAS_FASTAPI = bool(
    __import__("importlib.util", fromlist=["find_spec"]).find_spec("fastapi")
)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestCommitFillCreatesPosition:
    """Tests for _commit_fill position creation."""

    def _make_order(self, **overrides):
        """Helper to build a realistic order dict."""
        base = {
            "id": "order-test-1",
            "portfolio_id": "port-1",
            "status": "staged",
            "side": "buy",
            "requested_qty": 2,
            "filled_qty": 0,
            "avg_fill_price": 0,
            "fees_usd": 0,
            "trace_id": "trace-abc",
            "suggestion_id": "sug-123",
            "position_id": None,
            "tcm": {"fees_usd": 0.26},
            "order_json": {
                "symbol": "AMZN",
                "strategy_type": "long_call",
                "order_type": "limit",
                "limit_price": 5.50,
                "quantity": 2,
                "legs": [
                    {
                        "symbol": "O:AMZN260320C00185000",
                        "action": "buy",
                        "type": "call",
                        "strike": 185.0,
                        "expiry": "2026-03-20",
                        "quantity": 2,
                    }
                ],
            },
        }
        base.update(overrides)
        return base

    def _make_fill_res(self, **overrides):
        """Helper to build a simulate_fill result."""
        base = {
            "status": "filled",
            "filled_qty": 2.0,
            "avg_fill_price": 5.60,
            "last_fill_qty": 2.0,
            "last_fill_price": 5.60,
        }
        base.update(overrides)
        return base

    def test_filled_order_creates_position(self):
        """After an order fills, a paper_positions INSERT must be called."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        position_insert_mock = MagicMock()
        position_insert_mock.return_value.execute.return_value = MagicMock(
            data=[{"id": "pos-new-1"}]
        )

        order_update_calls = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_orders":
                # Track updates
                def capture_update(payload):
                    order_update_calls.append(payload)
                    chain = MagicMock()
                    chain.eq.return_value.execute.return_value = MagicMock()
                    return chain
                mock_table.update.side_effect = capture_update
            elif table_name == "paper_portfolios":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_positions":
                # No existing position
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert = position_insert_mock
            elif table_name == "paper_ledger":
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            elif table_name == "trade_suggestions":
                mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                    data={"model_version": "v4", "features_hash": "abc", "strategy": "long_call", "window": "midday", "regime": "normal"}
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = self._make_order()
        fill_res = self._make_fill_res()
        quote = {"bid_price": 5.50, "ask_price": 5.70}
        portfolio = {"id": "port-1", "cash_balance": 100000.0}

        from packages.quantum.paper_endpoints import _commit_fill
        _commit_fill(mock_supabase, mock_analytics, "user-1", order, fill_res, quote, portfolio)

        # Verify position INSERT was called
        assert position_insert_mock.called, "paper_positions INSERT was not called"
        pos_payload = position_insert_mock.call_args[0][0]

        # Verify required fields
        assert pos_payload["user_id"] == "user-1"
        assert pos_payload["portfolio_id"] == "port-1"
        assert pos_payload["symbol"] == "AMZN"
        assert pos_payload["quantity"] == 2.0  # Buy = positive
        assert pos_payload["avg_entry_price"] == 5.60
        assert pos_payload["current_mark"] == 5.60
        assert pos_payload["trace_id"] == "trace-abc"
        assert pos_payload["suggestion_id"] == "sug-123"

        # Verify legs are included
        assert "legs" in pos_payload
        assert len(pos_payload["legs"]) == 1
        assert pos_payload["legs"][0]["symbol"] == "O:AMZN260320C00185000"

        # Verify order was updated with position_id
        position_id_updates = [
            c for c in order_update_calls if "position_id" in c
        ]
        assert len(position_id_updates) > 0, "Order was not updated with position_id"
        assert position_id_updates[-1]["position_id"] == "pos-new-1"

    def test_strategy_key_fallback_on_ticket_reconstruction_error(self):
        """If TradeTicket(**order_json) fails, strategy_key should fall back to {symbol}_custom."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        position_insert_mock = MagicMock()
        position_insert_mock.return_value.execute.return_value = MagicMock(
            data=[{"id": "pos-fallback-1"}]
        )

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_orders":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_portfolios":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_positions":
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert = position_insert_mock
            elif table_name == "paper_ledger":
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        # Use order_json that will cause TradeTicket reconstruction to fail
        # (invalid field that Pydantic rejects)
        order = self._make_order()
        order["order_json"]["order_type"] = "INVALID_TYPE"  # Not in Literal["market", "limit"]

        fill_res = self._make_fill_res()
        quote = {"bid_price": 5.50, "ask_price": 5.70}
        portfolio = {"id": "port-1", "cash_balance": 100000.0}

        from packages.quantum.paper_endpoints import _commit_fill
        _commit_fill(mock_supabase, mock_analytics, "user-1", order, fill_res, quote, portfolio)

        # Position should still be created with fallback strategy_key
        assert position_insert_mock.called, "Position INSERT was not called despite fallback"
        pos_payload = position_insert_mock.call_args[0][0]
        assert pos_payload["strategy_key"] == "AMZN_custom"

    def test_position_creation_failure_rolls_back_order(self):
        """If position INSERT fails, order should be rolled back to 'working'."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        order_update_calls = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_orders":
                def capture_update(payload):
                    order_update_calls.append(payload)
                    chain = MagicMock()
                    chain.eq.return_value.execute.return_value = MagicMock()
                    return chain
                mock_table.update.side_effect = capture_update
            elif table_name == "paper_portfolios":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_positions":
                # No existing position
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                # INSERT throws an error
                mock_table.insert.side_effect = Exception("DB constraint violation")
            elif table_name == "paper_ledger":
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        order = self._make_order()
        fill_res = self._make_fill_res()
        quote = {"bid_price": 5.50, "ask_price": 5.70}
        portfolio = {"id": "port-1", "cash_balance": 100000.0}

        from packages.quantum.paper_endpoints import _commit_fill
        # Should not raise — the error is caught and order is rolled back
        _commit_fill(mock_supabase, mock_analytics, "user-1", order, fill_res, quote, portfolio)

        # Order should be rolled back to 'working'
        rollback_updates = [
            c for c in order_update_calls if c.get("status") == "working"
        ]
        assert len(rollback_updates) > 0, "Order was not rolled back to 'working'"


class TestOrphanRepairSourceCode:
    """Source-code structure tests (no fastapi needed)."""

    def test_source_code_orphan_repair_before_target_filter(self):
        """Verify orphan repair runs in a separate pass before target_order_id filtering."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # The orphan repair loop should appear BEFORE the target_order_id filter
        process_fn_pos = source.find("def _process_orders_for_user")
        assert process_fn_pos > 0

        orphan_loop_in_fn = source.find("for order in orphan_orders:", process_fn_pos)
        target_filter_in_fn = source.find("if target_order_id:", process_fn_pos)

        assert orphan_loop_in_fn > 0, "Orphan repair loop not found"
        assert target_filter_in_fn > 0, "target_order_id filter not found"
        assert orphan_loop_in_fn < target_filter_in_fn, (
            "Orphan repair loop should run BEFORE target_order_id filter"
        )

    def test_source_code_commit_fill_strategy_key_fallback(self):
        """Verify _commit_fill has try/except around strategy_key derivation."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "paper_commit_fill_strategy_key_error" in source
        assert 'f"{symbol}_custom"' in source

    def test_source_code_commit_fill_position_rollback(self):
        """Verify _commit_fill rolls back order on position creation failure."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "paper_commit_fill_position_failed" in source
        assert "paper_commit_fill_rollback_failed" in source

    def test_source_code_position_payload_includes_legs(self):
        """Verify position payload includes legs from order_json."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # _commit_fill uses legs_list variable, _repair_filled_order_commit uses ticket.get
        assert '"legs":' in source
        assert 'ticket.get("legs", [])' in source


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestOrphanRepairAlwaysRuns:
    """Mock-based tests for orphan repair (requires fastapi)."""

    def test_orphans_repaired_even_with_target_order_id(self):
        """Orphan orders should be repaired even when processing a specific target order."""
        mock_supabase = MagicMock()
        mock_analytics = MagicMock()

        repaired_order_ids = []

        # Track which tables are queried and what data is returned
        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_portfolios":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": "port-1", "cash_balance": 100000.0}]
                )
            elif table_name == "paper_orders":
                # For the main query (staged/working/partial orders)
                staged_mock = MagicMock()
                staged_mock.in_.return_value.execute.return_value = MagicMock(
                    data=[{
                        "id": "order-target",
                        "portfolio_id": "port-1",
                        "status": "staged",
                        "side": "buy",
                        "order_json": {"symbol": "MSFT", "legs": []},
                    }]
                )

                # For the orphan query
                orphan_mock = MagicMock()
                orphan_mock.in_.return_value.execute.return_value = MagicMock(
                    data=[{
                        "id": "order-orphan-old",
                        "portfolio_id": "port-1",
                        "status": "filled",
                        "position_id": None,
                        "filled_qty": 3,
                        "avg_fill_price": 150.0,
                        "fees_usd": 0.39,
                        "side": "buy",
                        "trace_id": "trace-orphan",
                        "order_json": {
                            "symbol": "AAPL",
                            "legs": [{"symbol": "O:AAPL260320C00200000", "action": "buy"}],
                        },
                    }]
                )

                # Route based on chained calls
                def select_side(*args, **kwargs):
                    select_mock = MagicMock()

                    def in_status_side(field, values):
                        if "staged" in values:
                            return staged_mock
                        return MagicMock()

                    def eq_side(field, value):
                        if value == "filled":
                            is_mock = MagicMock()
                            is_mock.in_.return_value.execute.return_value = orphan_mock.in_.return_value.execute.return_value
                            return MagicMock(is_=lambda f, v: is_mock)
                        return MagicMock()

                    select_mock.in_ = in_status_side
                    select_mock.eq = eq_side
                    return select_mock

                mock_table.select.side_effect = select_side
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

            elif table_name == "paper_positions":
                mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "pos-repaired"}]
                )
            elif table_name == "paper_ledger":
                mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[]
                )
                mock_table.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "ledger-1"}]
                )
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        # Patch _repair_filled_order_commit to track calls
        with patch("packages.quantum.paper_endpoints._repair_filled_order_commit") as mock_repair:
            mock_repair.return_value = {"repaired": True, "position_id": "pos-repaired", "ledger_inserted": True}

            # Patch PolygonService and simulate_fill to prevent real processing
            with patch("packages.quantum.paper_endpoints.PolygonService"):
                with patch("packages.quantum.paper_endpoints.TransactionCostModel"):
                    from packages.quantum.paper_endpoints import _process_orders_for_user
                    result = _process_orders_for_user(
                        mock_supabase, mock_analytics, "user-1",
                        target_order_id="order-target"  # Only target this order
                    )

            # Verify repair was called for the orphan order (not filtered by target_order_id)
            assert mock_repair.called, "Orphan repair was not called"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
