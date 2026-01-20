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

        # Setup suggestion with traceability fields
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

        # Verify ledger was called
        mock_ledger.record_fill.assert_called_once()

        call_args = mock_ledger.record_fill.call_args
        self.assertEqual(call_args.kwargs["user_id"], self.user_id)
        self.assertIsNotNone(call_args.kwargs["trade_execution_id"])

        fill_data = call_args.kwargs["fill_data"]
        self.assertEqual(fill_data["symbol"], "AAPL")
        self.assertEqual(fill_data["qty"], 1)
        self.assertEqual(fill_data["price"], 2.50)

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

        # Multi-leg order
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

        # Verify legs_fingerprint was computed and passed
        call_args = mock_ledger.record_fill.call_args
        context = call_args.kwargs["context"]

        self.assertIsNotNone(context.get("legs_fingerprint"))
        # Fingerprint should be consistent
        expected_fingerprint = _build_legs_fingerprint(suggestion["order_json"])
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


if __name__ == "__main__":
    unittest.main()
