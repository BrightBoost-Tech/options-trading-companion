"""
Paper Ledger Service - Phase 2.1 Structured Events

Provides authoritative event stream for paper trading with structured event types:
- deposit: Cash added to portfolio
- withdraw: Cash removed from portfolio
- order_submit: Order staged/submitted
- fill: Complete fill of an order
- partial_fill: Partial fill of an order
- close: Position closed
- fee: Fee charged

Events include metadata JSONB column with structured contextual data.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Literal
from enum import Enum
from pydantic import BaseModel


logger = logging.getLogger(__name__)


# =============================================================================
# Event Types
# =============================================================================

class PaperLedgerEventType(str, Enum):
    """Structured event types for paper ledger."""
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    ORDER_SUBMIT = "order_submit"
    FILL = "fill"
    PARTIAL_FILL = "partial_fill"
    CLOSE = "close"
    FEE = "fee"
    ADJUSTMENT = "adjustment"  # For corrections


class PaperLedgerEvent(BaseModel):
    """Structured paper ledger event."""
    portfolio_id: str
    event_type: PaperLedgerEventType
    amount: float  # Positive = credit, Negative = debit
    balance_after: float
    description: str

    # Required for DB constraint
    user_id: Optional[str] = None

    # Linkage (optional)
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    trace_id: Optional[str] = None

    # Metadata JSONB
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        use_enum_values = True


# =============================================================================
# Paper Ledger Service
# =============================================================================

class PaperLedgerService:
    """
    Service for emitting structured paper ledger events.

    Usage:
        ledger = PaperLedgerService(supabase_client)
        ledger.emit_fill(
            portfolio_id="...",
            amount=-5000.0,
            balance_after=95000.0,
            order_id="...",
            metadata={"side": "buy", "qty": 1, "price": 50.0, "symbol": "SPY"}
        )
    """

    def __init__(self, supabase_client):
        self.client = supabase_client

    def emit(self, event: PaperLedgerEvent) -> Optional[Dict[str, Any]]:
        """
        Emit a structured ledger event to the database.

        Args:
            event: PaperLedgerEvent instance

        Returns:
            Inserted record or None on failure
        """
        try:
            payload = {
                "portfolio_id": event.portfolio_id,
                "user_id": event.user_id,
                "event_type": event.event_type,
                "amount": event.amount,
                "balance_after": event.balance_after,
                "description": event.description,
                "order_id": event.order_id,
                "position_id": event.position_id,
                "trace_id": event.trace_id,
                "metadata": event.metadata,
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            result = self.client.table("paper_ledger").insert(payload).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to emit paper ledger event: {e}")
            return None

    # =========================================================================
    # Convenience Methods for Common Event Types
    # =========================================================================

    def emit_deposit(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Emit a deposit event (cash added)."""
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            event_type=PaperLedgerEventType.DEPOSIT,
            amount=abs(amount),  # Always positive for deposit
            balance_after=balance_after,
            description=description or f"Deposit ${abs(amount):,.2f}",
            metadata=metadata
        ))

    def emit_withdraw(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Emit a withdraw event (cash removed)."""
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            event_type=PaperLedgerEventType.WITHDRAW,
            amount=-abs(amount),  # Always negative for withdraw
            balance_after=balance_after,
            description=description or f"Withdraw ${abs(amount):,.2f}",
            metadata=metadata
        ))

    def emit_order_submit(
        self,
        portfolio_id: str,
        order_id: str,
        trace_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Emit an order submission event (no cash movement, just audit)."""
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            event_type=PaperLedgerEventType.ORDER_SUBMIT,
            amount=0.0,  # No cash movement on submit
            balance_after=0.0,  # Will be set by caller or default
            description=description or f"Order submitted: {order_id[:8]}",
            order_id=order_id,
            trace_id=trace_id,
            metadata=metadata
        ))

    def emit_fill(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Emit a complete fill event.

        Args:
            amount: Cash delta (negative for buys, positive for sells)
            balance_after: Cash balance after this fill
            user_id: User ID (required by DB constraint)
            metadata: Should include {side, qty, price, symbol, fees}
        """
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            user_id=user_id,
            event_type=PaperLedgerEventType.FILL,
            amount=amount,
            balance_after=balance_after,
            description=description or self._build_fill_description(metadata),
            order_id=order_id,
            position_id=position_id,
            trace_id=trace_id,
            metadata=metadata
        ))

    def emit_partial_fill(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Emit a partial fill event.

        Args:
            amount: Cash delta for this partial fill
            balance_after: Cash balance after this partial fill
            user_id: User ID (required by DB constraint)
            metadata: Should include {side, qty, price, symbol, fees, filled_so_far, total_qty}
        """
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            user_id=user_id,
            event_type=PaperLedgerEventType.PARTIAL_FILL,
            amount=amount,
            balance_after=balance_after,
            description=description or self._build_partial_fill_description(metadata),
            order_id=order_id,
            position_id=position_id,
            trace_id=trace_id,
            metadata=metadata
        ))

    def emit_close(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        position_id: Optional[str] = None,
        order_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Emit a position close event.

        Args:
            amount: Final cash delta from closing
            metadata: Should include {symbol, pnl_realized, entry_price, exit_price}
        """
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            event_type=PaperLedgerEventType.CLOSE,
            amount=amount,
            balance_after=balance_after,
            description=description or self._build_close_description(metadata),
            position_id=position_id,
            order_id=order_id,
            trace_id=trace_id,
            metadata=metadata
        ))

    def emit_fee(
        self,
        portfolio_id: str,
        amount: float,
        balance_after: float,
        order_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Emit a fee event (separate from fill for detailed tracking).

        Args:
            amount: Fee amount (always negative)
            metadata: Should include {fee_type, order_id}
        """
        return self.emit(PaperLedgerEvent(
            portfolio_id=portfolio_id,
            event_type=PaperLedgerEventType.FEE,
            amount=-abs(amount),  # Fees are always debits
            balance_after=balance_after,
            description=description or f"Fee: ${abs(amount):.2f}",
            order_id=order_id,
            trace_id=trace_id,
            metadata=metadata
        ))

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _build_fill_description(self, metadata: Optional[Dict[str, Any]]) -> str:
        """Build human-readable description for fill event."""
        if not metadata:
            return "Fill executed"

        side = metadata.get("side", "").upper()
        qty = metadata.get("qty", 0)
        price = metadata.get("price", 0)
        symbol = metadata.get("symbol", "")
        fees = metadata.get("fees", 0)

        desc = f"{side} {qty} {symbol} @ ${price:.4f}"
        if fees:
            desc += f" (fees: ${fees:.2f})"
        return desc

    def _build_partial_fill_description(self, metadata: Optional[Dict[str, Any]]) -> str:
        """Build human-readable description for partial fill event."""
        if not metadata:
            return "Partial fill"

        side = metadata.get("side", "").upper()
        qty = metadata.get("qty", 0)
        price = metadata.get("price", 0)
        symbol = metadata.get("symbol", "")
        filled_so_far = metadata.get("filled_so_far", qty)
        total_qty = metadata.get("total_qty", qty)

        return f"Partial {side} {qty} {symbol} @ ${price:.4f} ({filled_so_far}/{total_qty})"

    def _build_close_description(self, metadata: Optional[Dict[str, Any]]) -> str:
        """Build human-readable description for close event."""
        if not metadata:
            return "Position closed"

        symbol = metadata.get("symbol", "")
        pnl = metadata.get("pnl_realized", 0)

        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        return f"Closed {symbol} | PnL: {pnl_str}"

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_events(
        self,
        portfolio_id: str,
        event_types: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Query ledger events for a portfolio.

        Args:
            portfolio_id: Portfolio to query
            event_types: Filter to specific event types
            limit: Max records to return
            offset: Pagination offset

        Returns:
            List of ledger event records
        """
        try:
            query = self.client.table("paper_ledger") \
                .select("*") \
                .eq("portfolio_id", portfolio_id) \
                .order("created_at", desc=True) \
                .range(offset, offset + limit - 1)

            if event_types:
                query = query.in_("event_type", event_types)

            result = query.execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to query paper ledger: {e}")
            return []

    def get_fill_events(
        self,
        portfolio_id: str,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get fill and partial_fill events for a portfolio."""
        try:
            query = self.client.table("paper_ledger") \
                .select("*") \
                .eq("portfolio_id", portfolio_id) \
                .in_("event_type", [
                    PaperLedgerEventType.FILL.value,
                    PaperLedgerEventType.PARTIAL_FILL.value
                ]) \
                .order("created_at", desc=True) \
                .limit(limit)

            if since:
                query = query.gte("created_at", since.isoformat())

            result = query.execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to query fill events: {e}")
            return []
