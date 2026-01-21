"""
Tests for Phase 2.1 Paper Ledger Service - Structured Events.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestPaperLedgerEventTypes(unittest.TestCase):
    """Tests for paper ledger event type enum."""

    def test_all_event_types_defined(self):
        """All required event types are defined."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerEventType

        expected_types = [
            "deposit",
            "withdraw",
            "order_submit",
            "fill",
            "partial_fill",
            "close",
            "fee",
            "adjustment"
        ]

        for event_type in expected_types:
            self.assertTrue(
                hasattr(PaperLedgerEventType, event_type.upper()),
                f"Missing event type: {event_type}"
            )

    def test_event_type_values(self):
        """Event type values are lowercase strings."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerEventType

        self.assertEqual(PaperLedgerEventType.DEPOSIT.value, "deposit")
        self.assertEqual(PaperLedgerEventType.FILL.value, "fill")
        self.assertEqual(PaperLedgerEventType.PARTIAL_FILL.value, "partial_fill")


class TestPaperLedgerEvent(unittest.TestCase):
    """Tests for PaperLedgerEvent model."""

    def test_event_model_required_fields(self):
        """Event model requires essential fields."""
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerEvent,
            PaperLedgerEventType
        )

        event = PaperLedgerEvent(
            portfolio_id="test-portfolio",
            event_type=PaperLedgerEventType.FILL,
            amount=-5000.0,
            balance_after=95000.0,
            description="Test fill"
        )

        self.assertEqual(event.portfolio_id, "test-portfolio")
        self.assertEqual(event.event_type, "fill")  # Enum converted to value
        self.assertEqual(event.amount, -5000.0)
        self.assertEqual(event.balance_after, 95000.0)

    def test_event_model_optional_fields(self):
        """Event model accepts optional linkage fields."""
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerEvent,
            PaperLedgerEventType
        )

        event = PaperLedgerEvent(
            portfolio_id="test-portfolio",
            event_type=PaperLedgerEventType.FILL,
            amount=-5000.0,
            balance_after=95000.0,
            description="Test fill",
            order_id="order-123",
            position_id="position-456",
            trace_id="trace-789",
            metadata={"side": "buy", "qty": 1}
        )

        self.assertEqual(event.order_id, "order-123")
        self.assertEqual(event.position_id, "position-456")
        self.assertEqual(event.trace_id, "trace-789")
        self.assertEqual(event.metadata["side"], "buy")


class TestPaperLedgerService(unittest.TestCase):
    """Tests for PaperLedgerService."""

    def setUp(self):
        """Set up mock supabase client."""
        self.mock_client = MagicMock()
        self.mock_insert_result = MagicMock()
        self.mock_insert_result.data = [{"id": "ledger-event-1"}]

        self.mock_client.table.return_value.insert.return_value.execute.return_value = self.mock_insert_result

    def test_emit_fill_creates_structured_event(self):
        """emit_fill creates a structured fill event."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        result = service.emit_fill(
            portfolio_id="port-123",
            amount=-5000.0,
            balance_after=95000.0,
            order_id="order-456",
            metadata={"side": "buy", "qty": 1, "price": 50.0, "symbol": "SPY"}
        )

        self.assertIsNotNone(result)

        # Verify insert was called
        self.mock_client.table.assert_called_with("paper_ledger")

        # Verify payload structure
        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["portfolio_id"], "port-123")
        self.assertEqual(call_args["event_type"], "fill")
        self.assertEqual(call_args["amount"], -5000.0)
        self.assertEqual(call_args["balance_after"], 95000.0)
        self.assertEqual(call_args["order_id"], "order-456")
        self.assertEqual(call_args["metadata"]["side"], "buy")

    def test_emit_partial_fill_creates_partial_event(self):
        """emit_partial_fill creates a partial_fill event."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        result = service.emit_partial_fill(
            portfolio_id="port-123",
            amount=-2500.0,
            balance_after=97500.0,
            order_id="order-456",
            metadata={"side": "buy", "qty": 0.5, "price": 50.0, "filled_so_far": 0.5, "total_qty": 1}
        )

        self.assertIsNotNone(result)

        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["event_type"], "partial_fill")

    def test_emit_deposit_positive_amount(self):
        """emit_deposit ensures positive amount."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        # Even if passed negative, should be positive
        service.emit_deposit(
            portfolio_id="port-123",
            amount=-1000.0,
            balance_after=101000.0
        )

        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["event_type"], "deposit")
        self.assertEqual(call_args["amount"], 1000.0)  # Positive

    def test_emit_withdraw_negative_amount(self):
        """emit_withdraw ensures negative amount."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        # Even if passed positive, should be negative
        service.emit_withdraw(
            portfolio_id="port-123",
            amount=1000.0,
            balance_after=99000.0
        )

        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["event_type"], "withdraw")
        self.assertEqual(call_args["amount"], -1000.0)  # Negative

    def test_emit_fee_negative_amount(self):
        """emit_fee ensures negative amount (debit)."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        service.emit_fee(
            portfolio_id="port-123",
            amount=5.0,
            balance_after=99995.0
        )

        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["event_type"], "fee")
        self.assertEqual(call_args["amount"], -5.0)  # Always negative

    def test_emit_close_with_metadata(self):
        """emit_close includes PnL metadata."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(self.mock_client)

        service.emit_close(
            portfolio_id="port-123",
            amount=500.0,  # Profit
            balance_after=100500.0,
            position_id="pos-789",
            metadata={"symbol": "SPY", "pnl_realized": 500.0, "entry_price": 400.0, "exit_price": 405.0}
        )

        call_args = self.mock_client.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_args["event_type"], "close")
        self.assertEqual(call_args["position_id"], "pos-789")
        self.assertEqual(call_args["metadata"]["pnl_realized"], 500.0)


class TestPaperLedgerDescriptions(unittest.TestCase):
    """Tests for auto-generated descriptions."""

    def test_fill_description_generation(self):
        """Fill description includes key details."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(MagicMock())

        desc = service._build_fill_description({
            "side": "buy",
            "qty": 10,
            "price": 5.25,
            "symbol": "SPY",
            "fees": 1.50
        })

        self.assertIn("BUY", desc)
        self.assertIn("10", desc)
        self.assertIn("SPY", desc)
        self.assertIn("5.25", desc)
        self.assertIn("1.50", desc)

    def test_partial_fill_description_progress(self):
        """Partial fill description shows progress."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(MagicMock())

        desc = service._build_partial_fill_description({
            "side": "sell",
            "qty": 5,
            "price": 10.0,
            "symbol": "QQQ",
            "filled_so_far": 5,
            "total_qty": 10
        })

        self.assertIn("Partial", desc)
        self.assertIn("SELL", desc)
        self.assertIn("5/10", desc)

    def test_close_description_shows_pnl(self):
        """Close description shows PnL."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        service = PaperLedgerService(MagicMock())

        # Profit
        desc = service._build_close_description({
            "symbol": "AAPL",
            "pnl_realized": 250.0
        })
        self.assertIn("AAPL", desc)
        self.assertIn("+", desc)
        self.assertIn("250", desc)

        # Loss
        desc = service._build_close_description({
            "symbol": "MSFT",
            "pnl_realized": -100.0
        })
        self.assertIn("MSFT", desc)
        self.assertIn("-", desc)
        self.assertIn("100", desc)


if __name__ == "__main__":
    unittest.main()
