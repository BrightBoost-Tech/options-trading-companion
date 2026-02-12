"""
Tests for user_id propagation in paper trading fill commits.

Verifies:
1. PaperLedgerEvent model includes user_id field
2. PaperLedgerService.emit() includes user_id in payload
3. emit_fill and emit_partial_fill accept and pass user_id
4. pos_payload in _commit_fill includes user_id
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestPaperLedgerEventModel:
    """Tests for PaperLedgerEvent model user_id field."""

    def test_model_has_user_id_field(self):
        """PaperLedgerEvent should have user_id field."""
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerEvent,
            PaperLedgerEventType
        )

        event = PaperLedgerEvent(
            portfolio_id="port-123",
            user_id="user-456",
            event_type=PaperLedgerEventType.FILL,
            amount=-1000.0,
            balance_after=9000.0,
            description="Test fill"
        )

        assert event.user_id == "user-456"

    def test_model_user_id_optional(self):
        """user_id should be optional for backwards compatibility."""
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerEvent,
            PaperLedgerEventType
        )

        event = PaperLedgerEvent(
            portfolio_id="port-123",
            event_type=PaperLedgerEventType.FILL,
            amount=-1000.0,
            balance_after=9000.0,
            description="Test fill"
        )

        assert event.user_id is None


class TestPaperLedgerServiceEmit:
    """Tests for PaperLedgerService.emit() user_id handling."""

    def test_emit_includes_user_id_in_payload(self):
        """emit() should include user_id in the database payload."""
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerService,
            PaperLedgerEvent,
            PaperLedgerEventType
        )

        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "ledger-1"}]
        )

        ledger = PaperLedgerService(mock_client)
        event = PaperLedgerEvent(
            portfolio_id="port-123",
            user_id="user-456",
            event_type=PaperLedgerEventType.FILL,
            amount=-1000.0,
            balance_after=9000.0,
            description="Test fill"
        )

        ledger.emit(event)

        # Verify insert was called with user_id in payload
        mock_client.table.assert_called_with("paper_ledger")
        insert_call = mock_client.table.return_value.insert.call_args
        payload = insert_call[0][0]

        assert payload["user_id"] == "user-456"
        assert payload["portfolio_id"] == "port-123"

    def test_emit_fill_accepts_user_id(self):
        """emit_fill should accept and pass user_id."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "ledger-1"}]
        )

        ledger = PaperLedgerService(mock_client)
        ledger.emit_fill(
            portfolio_id="port-123",
            amount=-5000.0,
            balance_after=95000.0,
            order_id="order-789",
            user_id="user-456",
            metadata={"side": "buy", "qty": 1, "price": 50.0, "symbol": "SPY"}
        )

        insert_call = mock_client.table.return_value.insert.call_args
        payload = insert_call[0][0]

        assert payload["user_id"] == "user-456"

    def test_emit_partial_fill_accepts_user_id(self):
        """emit_partial_fill should accept and pass user_id."""
        from packages.quantum.services.paper_ledger_service import PaperLedgerService

        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "ledger-1"}]
        )

        ledger = PaperLedgerService(mock_client)
        ledger.emit_partial_fill(
            portfolio_id="port-123",
            amount=-2500.0,
            balance_after=97500.0,
            order_id="order-789",
            user_id="user-456",
            metadata={"side": "buy", "qty": 1, "price": 25.0, "symbol": "AAPL"}
        )

        insert_call = mock_client.table.return_value.insert.call_args
        payload = insert_call[0][0]

        assert payload["user_id"] == "user-456"


class TestCommitFillUserIdPropagation:
    """Tests for _commit_fill user_id propagation via source inspection."""

    def test_commit_fill_function_signature_has_user_id(self):
        """_commit_fill should accept user_id parameter."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Verify _commit_fill function signature includes user_id parameter
        import re
        sig_match = re.search(
            r'def _commit_fill\([^)]*user_id[^)]*\):',
            source
        )

        assert sig_match is not None, "_commit_fill should have user_id parameter"

    def test_pos_payload_construction_includes_user_id(self):
        """Verify pos_payload construction includes user_id by inspecting source."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Find pos_payload construction and verify user_id is present
        # The pattern is: pos_payload = { ... "user_id": user_id ... }
        import re
        pos_payload_match = re.search(
            r'pos_payload\s*=\s*\{[^}]*"user_id":\s*user_id[^}]*\}',
            source,
            re.DOTALL
        )

        assert pos_payload_match is not None, "pos_payload should include user_id"


class TestSourceCodeVerification:
    """Verify source code changes are in place."""

    def test_paper_ledger_event_has_user_id(self):
        """Verify PaperLedgerEvent model has user_id field."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_ledger_service.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "user_id: Optional[str]" in source

    def test_emit_payload_includes_user_id(self):
        """Verify emit() payload includes user_id."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_ledger_service.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"user_id": event.user_id' in source

    def test_pos_payload_includes_user_id(self):
        """Verify pos_payload includes user_id."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # Should have user_id in pos_payload
        assert '"user_id": user_id' in source

    def test_ledger_emit_calls_include_user_id(self):
        """Verify ledger emit calls include user_id parameter."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "user_id=user_id" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
