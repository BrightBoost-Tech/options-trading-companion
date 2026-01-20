"""
Integration tests for ExecutionService -> PositionLedgerService wiring.

Tests that:
- register_execution calls PositionLedgerService.record_fill
- Ledger failures don't break execution registration
- Context is correctly passed from suggestion to ledger
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from packages.quantum.services.execution_service import (
    ExecutionService,
    _build_legs_fingerprint,
)


class TestExecutionLedgerWiring(unittest.TestCase):
    """Tests for ExecutionService -> PositionLedgerService integration."""

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ExecutionService(self.mock_supabase)
        self.user_id = "test-user-123"

    def _setup_supabase_mocks(self, suggestion_data=None, execution_id="exec-123"):
        """Set up common Supabase mocks for register_execution tests."""

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.insert.return_value = chain
            chain.update.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain

            result = MagicMock()

            if name == "trade_suggestions":
                if suggestion_data:
                    result.data = suggestion_data
                else:
                    result.data = None
                    chain.single.return_value.execute.side_effect = Exception("Not found")

            elif name == "suggestion_logs":
                result.data = None
                chain.single.return_value.execute.side_effect = Exception("Not found")

            elif name == "trade_executions":
                result.data = [{
                    "id": execution_id,
                    "user_id": self.user_id,
                    "symbol": suggestion_data.get("symbol", "AAPL") if suggestion_data else "AAPL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trace_id": suggestion_data.get("trace_id") if suggestion_data else None,
                    "strategy": suggestion_data.get("strategy") if suggestion_data else None,
                    "window": suggestion_data.get("window") if suggestion_data else None,
                    "regime": suggestion_data.get("regime") if suggestion_data else None,
                    "model_version": suggestion_data.get("model_version") if suggestion_data else None,
                    "features_hash": suggestion_data.get("features_hash") if suggestion_data else None,
                    "order_json": suggestion_data.get("order_json") if suggestion_data else None,
                }]

            else:
                result.data = []

            chain.execute.return_value = result
            return chain

        self.mock_supabase.table.side_effect = table_side_effect

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_register_execution_calls_ledger_service(self, MockLedgerService):
        """register_execution calls PositionLedgerService.record_fill."""

        # Setup ledger mock
        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {
            "success": True,
            "group_id": "group-1",
            "fill_id": "fill-1",
            "group_status": "OPEN",
        }

        # Setup suggestion with traceability fields (single leg)
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "trace_id": "trace-abc",
            "strategy": "vertical_call",
            "window": "earnings_pre",
            "regime": "NORMAL",
            "model_version": "v3.1",
            "features_hash": "hash123",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy", "right": "C", "strike": 150},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        # Call register_execution
        result = self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={
                "symbol": "AAPL",
                "fill_price": 2.50,
                "quantity": 1,
                "fees": 0.65,
                "side": "buy",
            },
        )

        # Verify ledger was called once (single leg)
        mock_ledger.record_fill.assert_called_once()

        call_args = mock_ledger.record_fill.call_args
        self.assertEqual(call_args.kwargs["user_id"], self.user_id)
        self.assertIsNotNone(call_args.kwargs["trade_execution_id"])

        fill_data = call_args.kwargs["fill_data"]
        # With multi-leg support, symbol comes from leg directly
        self.assertEqual(fill_data["symbol"], "AAPL240119C00150000")
        self.assertEqual(fill_data["qty"], 1)
        self.assertEqual(fill_data["price"], 2.50)
        self.assertEqual(fill_data["action"], "BUY")  # Action from leg

        context = call_args.kwargs["context"]
        self.assertEqual(context["trace_id"], "trace-abc")
        self.assertEqual(context["strategy"], "vertical_call")
        self.assertEqual(context["window"], "earnings_pre")
        self.assertEqual(context["regime"], "NORMAL")

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_ledger_failure_does_not_break_execution(self, MockLedgerService):
        """Ledger failure is logged but execution registration continues."""

        # Setup ledger mock to fail
        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.side_effect = Exception("Database error")

        suggestion = {"id": "suggestion-123", "symbol": "AAPL"}
        self._setup_supabase_mocks(suggestion_data=suggestion)

        # Call register_execution - should not raise
        result = self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={
                "fill_price": 2.50,
                "quantity": 1,
            },
        )

        # Execution should still succeed
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "exec-123")

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_ledger_receives_legs_fingerprint(self, MockLedgerService):
        """Ledger receives computed legs_fingerprint from order_json."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # Multi-leg order (2 legs)
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy"},
                    {"symbol": "AAPL240119C00160000", "action": "sell"},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={"fill_price": 1.00, "quantity": 1},
        )

        # With multi-leg support, record_fill is called once per leg
        self.assertEqual(mock_ledger.record_fill.call_count, 2)

        # Verify legs_fingerprint was computed and passed to ALL legs
        expected_fingerprint = _build_legs_fingerprint(suggestion["order_json"])

        for call in mock_ledger.record_fill.call_args_list:
            context = call.kwargs["context"]
            self.assertIsNotNone(context.get("legs_fingerprint"))
            self.assertEqual(context["legs_fingerprint"], expected_fingerprint)

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_execution_without_suggestion_still_calls_ledger(self, MockLedgerService):
        """Execution without valid suggestion still attempts ledger recording."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # No suggestion found
        self._setup_supabase_mocks(suggestion_data=None)

        # Override to make execution insert work
        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.insert.return_value = chain
            chain.update.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain

            result = MagicMock()

            if name in ("trade_suggestions", "suggestion_logs"):
                chain.single.return_value.execute.side_effect = Exception("Not found")
                result.data = None
            elif name == "trade_executions":
                result.data = [{
                    "id": "exec-orphan",
                    "user_id": self.user_id,
                    "symbol": "AAPL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }]
            else:
                result.data = []

            chain.execute.return_value = result
            return chain

        self.mock_supabase.table.side_effect = table_side_effect

        result = self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="orphan-suggestion",
            fill_details={
                "symbol": "AAPL",
                "fill_price": 2.50,
                "quantity": 1,
            },
        )

        # Execution created (orphaned)
        self.assertIsNotNone(result)

        # Ledger was still called
        mock_ledger.record_fill.assert_called_once()


class TestBuildLegsFingerprint(unittest.TestCase):
    """Tests for _build_legs_fingerprint helper."""

    def test_fingerprint_from_multi_leg_order(self):
        """Builds fingerprint from multi-leg order."""

        order_json = {
            "legs": [
                {"symbol": "AAPL240119C00150000", "action": "buy"},
                {"symbol": "AAPL240119C00160000", "action": "sell"},
            ]
        }

        fingerprint = _build_legs_fingerprint(order_json)

        self.assertIsNotNone(fingerprint)
        self.assertEqual(len(fingerprint), 16)  # First 16 chars of SHA256

    def test_fingerprint_is_deterministic(self):
        """Same legs produce same fingerprint regardless of order."""

        order1 = {
            "legs": [
                {"symbol": "AAPL240119C00160000"},
                {"symbol": "AAPL240119C00150000"},
            ]
        }

        order2 = {
            "legs": [
                {"symbol": "AAPL240119C00150000"},
                {"symbol": "AAPL240119C00160000"},
            ]
        }

        # Both should produce same fingerprint (symbols are sorted)
        self.assertEqual(
            _build_legs_fingerprint(order1),
            _build_legs_fingerprint(order2),
        )

    def test_fingerprint_returns_none_for_empty(self):
        """Returns None for empty/missing order_json."""

        self.assertIsNone(_build_legs_fingerprint(None))
        self.assertIsNone(_build_legs_fingerprint({}))
        self.assertIsNone(_build_legs_fingerprint({"legs": []}))


class TestExtractUnderlying(unittest.TestCase):
    """Tests for ExecutionService._extract_underlying."""

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ExecutionService(self.mock_supabase)

    def test_extract_underlying_from_option_symbol(self):
        """Extracts underlying from standard option symbol."""

        self.assertEqual(self.service._extract_underlying("AAPL240119C00150000"), "AAPL")
        self.assertEqual(self.service._extract_underlying("TSLA240315P00200000"), "TSLA")
        self.assertEqual(self.service._extract_underlying("NVDA250117C00500000"), "NVDA")

    def test_extract_underlying_from_stock_symbol(self):
        """Returns stock symbol as-is."""

        self.assertEqual(self.service._extract_underlying("AAPL"), "AAPL")
        self.assertEqual(self.service._extract_underlying("TSLA"), "TSLA")

    def test_extract_underlying_handles_empty(self):
        """Handles empty/None gracefully."""

        self.assertEqual(self.service._extract_underlying(""), "UNKNOWN")
        self.assertEqual(self.service._extract_underlying(None), "UNKNOWN")


class TestMultiLegFillRecording(unittest.TestCase):
    """Tests for multi-leg fill recording in ExecutionService."""

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ExecutionService(self.mock_supabase)
        self.user_id = "test-user-123"

    def _setup_supabase_mocks(self, suggestion_data=None, execution_id="exec-123"):
        """Set up common Supabase mocks for register_execution tests."""

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.insert.return_value = chain
            chain.update.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain

            result = MagicMock()

            if name == "trade_suggestions":
                if suggestion_data:
                    result.data = suggestion_data
                else:
                    result.data = None
                    chain.single.return_value.execute.side_effect = Exception("Not found")

            elif name == "suggestion_logs":
                result.data = None
                chain.single.return_value.execute.side_effect = Exception("Not found")

            elif name == "trade_executions":
                result.data = [{
                    "id": execution_id,
                    "user_id": self.user_id,
                    "symbol": suggestion_data.get("symbol", "AAPL") if suggestion_data else "AAPL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trace_id": suggestion_data.get("trace_id") if suggestion_data else None,
                    "strategy": suggestion_data.get("strategy") if suggestion_data else None,
                    "window": suggestion_data.get("window") if suggestion_data else None,
                    "regime": suggestion_data.get("regime") if suggestion_data else None,
                    "model_version": suggestion_data.get("model_version") if suggestion_data else None,
                    "features_hash": suggestion_data.get("features_hash") if suggestion_data else None,
                    "order_json": suggestion_data.get("order_json") if suggestion_data else None,
                }]

            else:
                result.data = []

            chain.execute.return_value = result
            return chain

        self.mock_supabase.table.side_effect = table_side_effect

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_multi_leg_order_calls_record_fill_for_each_leg(self, MockLedgerService):
        """Multi-leg order calls record_fill for EACH leg."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {
            "success": True,
            "group_id": "group-1",
            "fill_id": "fill-1",
        }

        # Vertical spread: buy lower strike, sell higher strike
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "strategy": "vertical_call",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy", "right": "C", "strike": 150},
                    {"symbol": "AAPL240119C00160000", "action": "sell", "right": "C", "strike": 160},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={
                "fill_price": 1.50,  # Net debit for the spread
                "quantity": 1,
                "fees": 1.30,  # Total fees for both legs
            },
        )

        # Should be called twice - once per leg
        self.assertEqual(mock_ledger.record_fill.call_count, 2)

        # Verify first leg (buy lower strike)
        call_args_0 = mock_ledger.record_fill.call_args_list[0]
        fill_data_0 = call_args_0.kwargs["fill_data"]
        self.assertEqual(fill_data_0["symbol"], "AAPL240119C00150000")
        self.assertEqual(fill_data_0["action"], "BUY")
        self.assertIn("leg0", call_args_0.kwargs["trade_execution_id"])

        # Verify second leg (sell higher strike)
        call_args_1 = mock_ledger.record_fill.call_args_list[1]
        fill_data_1 = call_args_1.kwargs["fill_data"]
        self.assertEqual(fill_data_1["symbol"], "AAPL240119C00160000")
        self.assertEqual(fill_data_1["action"], "SELL")
        self.assertIn("leg1", call_args_1.kwargs["trade_execution_id"])

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_multi_leg_price_allocation_splits_evenly(self, MockLedgerService):
        """When only total price is available, it's split evenly across legs."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # Two legs, total fill price = 2.00
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy"},
                    {"symbol": "AAPL240119C00160000", "action": "sell"},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={
                "fill_price": 2.00,  # Total
                "quantity": 1,
                "fees": 1.30,  # Total fees
            },
        )

        # Both legs should get price = 2.00 / 2 = 1.00
        call_args_0 = mock_ledger.record_fill.call_args_list[0]
        self.assertEqual(call_args_0.kwargs["fill_data"]["price"], 1.00)

        call_args_1 = mock_ledger.record_fill.call_args_list[1]
        self.assertEqual(call_args_1.kwargs["fill_data"]["price"], 1.00)

        # Fees should also be split evenly
        self.assertEqual(call_args_0.kwargs["fill_data"]["fee"], 0.65)
        self.assertEqual(call_args_1.kwargs["fill_data"]["fee"], 0.65)

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_multi_leg_uses_per_leg_price_when_available(self, MockLedgerService):
        """Per-leg prices from order_json take precedence over split."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # Legs with explicit prices
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy", "price": 3.00},
                    {"symbol": "AAPL240119C00160000", "action": "sell", "price": 1.50},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={
                "fill_price": 1.50,  # Net debit (should be ignored)
                "quantity": 1,
                "fees": 1.30,
            },
        )

        # Each leg should use its own price
        call_args_0 = mock_ledger.record_fill.call_args_list[0]
        self.assertEqual(call_args_0.kwargs["fill_data"]["price"], 3.00)

        call_args_1 = mock_ledger.record_fill.call_args_list[1]
        self.assertEqual(call_args_1.kwargs["fill_data"]["price"], 1.50)

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_multi_leg_idempotency_with_leg_index(self, MockLedgerService):
        """Each leg has unique trade_execution_id for idempotency."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy"},
                    {"symbol": "AAPL240119C00160000", "action": "sell"},
                    {"symbol": "AAPL240119C00170000", "action": "buy"},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion, execution_id="exec-multi")

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={"fill_price": 0.50, "quantity": 1},
        )

        # All three legs should have unique execution IDs
        exec_ids = [
            call.kwargs["trade_execution_id"]
            for call in mock_ledger.record_fill.call_args_list
        ]

        self.assertEqual(len(exec_ids), 3)
        self.assertEqual(len(set(exec_ids)), 3)  # All unique

        self.assertIn("leg0", exec_ids[0])
        self.assertIn("leg1", exec_ids[1])
        self.assertIn("leg2", exec_ids[2])

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_multi_leg_uses_per_leg_quantity(self, MockLedgerService):
        """Uses per-leg quantity when specified in order_json."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # Ratio spread: 1x buy, 2x sell
        suggestion = {
            "id": "suggestion-123",
            "symbol": "AAPL",
            "order_json": {
                "legs": [
                    {"symbol": "AAPL240119C00150000", "action": "buy", "quantity": 1},
                    {"symbol": "AAPL240119C00160000", "action": "sell", "quantity": 2},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={"fill_price": 1.00, "quantity": 3},
        )

        call_args_0 = mock_ledger.record_fill.call_args_list[0]
        self.assertEqual(call_args_0.kwargs["fill_data"]["qty"], 1)

        call_args_1 = mock_ledger.record_fill.call_args_list[1]
        self.assertEqual(call_args_1.kwargs["fill_data"]["qty"], 2)

    @patch("packages.quantum.services.position_ledger_service.PositionLedgerService")
    def test_iron_condor_four_legs(self, MockLedgerService):
        """Iron condor with 4 legs records all legs correctly."""

        mock_ledger = MockLedgerService.return_value
        mock_ledger.record_fill.return_value = {"success": True}

        # Iron condor: sell put spread + sell call spread
        suggestion = {
            "id": "suggestion-123",
            "symbol": "SPY",
            "strategy": "iron_condor",
            "order_json": {
                "legs": [
                    {"symbol": "SPY240119P00450000", "action": "buy", "right": "P", "strike": 450},
                    {"symbol": "SPY240119P00455000", "action": "sell", "right": "P", "strike": 455},
                    {"symbol": "SPY240119C00470000", "action": "sell", "right": "C", "strike": 470},
                    {"symbol": "SPY240119C00475000", "action": "buy", "right": "C", "strike": 475},
                ]
            },
        }

        self._setup_supabase_mocks(suggestion_data=suggestion)

        self.service.register_execution(
            user_id=self.user_id,
            suggestion_id="suggestion-123",
            fill_details={"fill_price": 1.50, "quantity": 1, "fees": 2.60},
        )

        # Should be called 4 times
        self.assertEqual(mock_ledger.record_fill.call_count, 4)

        # Verify actions match order_json
        actions = [
            call.kwargs["fill_data"]["action"]
            for call in mock_ledger.record_fill.call_args_list
        ]
        self.assertEqual(actions, ["BUY", "SELL", "SELL", "BUY"])

        # Verify all share the same legs_fingerprint
        fingerprints = [
            call.kwargs["context"]["legs_fingerprint"]
            for call in mock_ledger.record_fill.call_args_list
        ]
        self.assertEqual(len(set(fingerprints)), 1)  # All same


class TestResolveLegAction(unittest.TestCase):
    """Tests for _resolve_leg_action helper."""

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ExecutionService(self.mock_supabase)

    def test_resolve_buy_actions(self):
        """Resolves various buy action formats."""

        self.assertEqual(self.service._resolve_leg_action({"action": "buy"}), "BUY")
        self.assertEqual(self.service._resolve_leg_action({"action": "BUY"}), "BUY")
        self.assertEqual(self.service._resolve_leg_action({"action": "buy_to_open"}), "BUY")
        self.assertEqual(self.service._resolve_leg_action({"action": "buy_to_close"}), "BUY")

    def test_resolve_sell_actions(self):
        """Resolves various sell action formats."""

        self.assertEqual(self.service._resolve_leg_action({"action": "sell"}), "SELL")
        self.assertEqual(self.service._resolve_leg_action({"action": "SELL"}), "SELL")
        self.assertEqual(self.service._resolve_leg_action({"action": "sell_to_open"}), "SELL")
        self.assertEqual(self.service._resolve_leg_action({"action": "sell_to_close"}), "SELL")

    def test_resolve_legacy_side_field(self):
        """Falls back to legacy 'side' field."""

        self.assertEqual(self.service._resolve_leg_action({"side": "buy"}), "BUY")
        self.assertEqual(self.service._resolve_leg_action({"side": "sell"}), "SELL")

    def test_resolve_defaults_to_buy(self):
        """Defaults to BUY when action can't be determined."""

        self.assertEqual(self.service._resolve_leg_action({}), "BUY")
        self.assertEqual(self.service._resolve_leg_action({"action": "unknown"}), "BUY")


if __name__ == "__main__":
    unittest.main()
