"""
Alpaca Broker Client

Wraps the alpaca-py SDK for order submission, position tracking, and account
queries. Supports both paper and live modes via endpoint configuration.

Environment variables:
    ALPACA_API_KEY      — API key ID
    ALPACA_SECRET_KEY   — Secret key
    ALPACA_PAPER        — "true" for paper trading (default), "false" for live
"""

import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol translation helpers (Polygon ↔ Alpaca)
# ---------------------------------------------------------------------------

def polygon_to_alpaca(symbol: str) -> str:
    """O:AAPL260417P00200000 → AAPL260417P00200000"""
    return symbol.replace("O:", "") if symbol.startswith("O:") else symbol


def alpaca_to_polygon(symbol: str) -> str:
    """AAPL260417P00200000 → O:AAPL260417P00200000"""
    return f"O:{symbol}" if not symbol.startswith("O:") else symbol


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AlpacaError(Exception):
    """Base Alpaca error."""

class AlpacaAuthError(AlpacaError):
    """Authentication failure."""

class AlpacaOrderError(AlpacaError):
    """Order submission/query failure."""

class AlpacaRateLimitError(AlpacaError):
    """Rate limit hit — caller should retry."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AlpacaClient:
    """
    Wrapper around alpaca-py TradingClient.

    Provides typed methods for account, order, and position operations
    with retry logic, logging, and OCC symbol translation.
    """

    MAX_RETRIES = 3
    BASE_DELAY = 0.5  # seconds

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: Optional[bool] = None,
    ):
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self.paper = paper if paper is not None else (
            os.environ.get("ALPACA_PAPER", "true").lower() in ("true", "1")
        )

        if not self.api_key or not self.secret_key:
            raise AlpacaAuthError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set"
            )

        from alpaca.trading.client import TradingClient
        self._client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=self.paper,
        )

        mode_label = "PAPER" if self.paper else "LIVE"
        logger.info(f"[ALPACA] Client initialized in {mode_label} mode")

    # ── Retry helper ──────────────────────────────────────────────────

    def _call_with_retry(self, fn, *args, **kwargs) -> Any:
        """Call fn with exponential backoff on transient errors."""
        last_err = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                is_transient = any(k in err_str for k in ("429", "500", "502", "503", "timeout"))
                if is_transient and attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"[ALPACA] Transient error (attempt {attempt + 1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    break
        raise AlpacaError(f"Alpaca API call failed after {self.MAX_RETRIES} attempts: {last_err}")

    # ── Account ───────────────────────────────────────────────────────

    def get_account(self) -> Dict[str, Any]:
        """Account summary: balance, buying power, equity, PDT status."""
        acct = self._call_with_retry(self._client.get_account)
        return {
            "account_id": str(acct.id),
            "status": str(acct.status),
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "pattern_day_trader": acct.pattern_day_trader,
            "daytrade_count": int(acct.daytrade_count),
            "daytrading_buying_power": float(acct.daytrading_buying_power or 0),
            "paper": self.paper,
        }

    def get_buying_power(self) -> float:
        """Available buying power for new trades."""
        return float(self._call_with_retry(self._client.get_account).buying_power)

    def is_pdt_restricted(self) -> bool:
        """Check if account has PDT flag set."""
        return self._call_with_retry(self._client.get_account).pattern_day_trader

    def get_day_trade_count(self) -> int:
        """Rolling 5-day trade count from Alpaca."""
        return int(self._call_with_retry(self._client.get_account).daytrade_count)

    # ── Orders ────────────────────────────────────────────────────────

    def submit_option_order(self, order_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a single-leg or multi-leg option order.

        order_request: {
            symbol: str           — underlying (e.g. "AAPL")
            legs: [{symbol, side, qty}, ...]
            order_type: "limit" | "market"
            limit_price: float    — required for limit orders
            time_in_force: "day" | "gtc"
        }

        Returns dict with alpaca_order_id, status, submitted_at, etc.
        """
        from alpaca.trading.requests import (
            OptionLegRequest,
            LimitOrderRequest,
        )
        from alpaca.trading.enums import (
            OrderSide,
            TimeInForce,
            OrderType,
            OrderClass,
        )

        legs = order_request.get("legs", [])
        limit_price = order_request.get("limit_price")
        tif_str = order_request.get("time_in_force", "day").upper()
        tif = TimeInForce.DAY if tif_str == "DAY" else TimeInForce.GTC

        if not legs:
            raise AlpacaOrderError("Order must have at least one leg")

        # Build typed leg requests
        alpaca_legs = []
        for leg in legs:
            leg_symbol = polygon_to_alpaca(leg["symbol"])
            side = OrderSide.BUY if leg["side"].lower() in ("buy", "buy_to_open") else OrderSide.SELL
            alpaca_legs.append(OptionLegRequest(
                symbol=leg_symbol,
                side=side,
                ratio_qty=int(leg.get("qty", 1)),
            ))

        # Build request — qty is always required by the SDK validator.
        # For multi-leg spreads qty = number of spreads (leg ratio_qty).
        # For single-leg, qty = contract count from that leg.
        qty = float(alpaca_legs[0].ratio_qty or 1)
        is_multi = len(legs) >= 2
        # Options must always be limit orders — Alpaca rejects market orders
        # outside market hours.
        if not limit_price or limit_price <= 0:
            raise AlpacaOrderError(
                f"Cannot submit options order without limit_price (got {limit_price})"
            )

        common = dict(
            legs=alpaca_legs,
            qty=qty,
            time_in_force=tif,
            order_class=OrderClass.MLEG if is_multi else None,
            symbol=alpaca_legs[0].symbol if not is_multi else None,
            side=alpaca_legs[0].side if not is_multi else None,
        )

        req = LimitOrderRequest(
            type=OrderType.LIMIT,
            limit_price=limit_price,
            **common,
        )

        logger.info(
            f"[ALPACA] Submitting order: {len(legs)} legs, "
            f"type={order_request.get('order_type')}, limit={limit_price}"
        )

        order = self._call_with_retry(self._client.submit_order, req)
        result = self._serialize_order(order)
        logger.info(f"[ALPACA] Order submitted: id={result['alpaca_order_id']} status={result['status']}")
        return result

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get order status by Alpaca order ID."""
        order = self._call_with_retry(self._client.get_order_by_id, order_id)
        return self._serialize_order(order)

    def get_orders(
        self,
        status: str = "open",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List orders by status."""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }
        req = GetOrdersRequest(
            status=status_map.get(status, QueryOrderStatus.OPEN),
            limit=limit,
        )
        orders = self._call_with_retry(self._client.get_orders, req)
        return [self._serialize_order(o) for o in orders]

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        logger.info(f"[ALPACA] Cancelling order: {order_id}")
        self._call_with_retry(self._client.cancel_order_by_id, order_id)
        return {"status": "cancelled", "alpaca_order_id": order_id}

    # ── Positions ─────────────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        """All current positions."""
        positions = self._call_with_retry(self._client.get_all_positions)
        return [self._serialize_position(p) for p in positions]

    def get_option_positions(self) -> List[Dict[str, Any]]:
        """Filter to option positions only (symbol length > 10 heuristic)."""
        all_pos = self.get_positions()
        return [p for p in all_pos if len(p.get("symbol", "")) > 10]

    def close_position(self, symbol_or_id: str, qty: Optional[int] = None) -> Dict[str, Any]:
        """Close a position (full or partial)."""
        from alpaca.trading.requests import ClosePositionRequest
        logger.info(f"[ALPACA] Closing position: {symbol_or_id} qty={qty}")
        req = ClosePositionRequest(qty=str(qty)) if qty else None
        result = self._call_with_retry(
            self._client.close_position, symbol_or_id, close_options=req,
        )
        return self._serialize_order(result)

    # ── Serializers ───────────────────────────────────────────────────

    @staticmethod
    def _serialize_order(order) -> Dict[str, Any]:
        """Convert Alpaca Order object to plain dict."""
        return {
            "alpaca_order_id": str(order.id),
            "client_order_id": str(order.client_order_id) if order.client_order_id else None,
            "status": str(order.status.value) if hasattr(order.status, "value") else str(order.status),
            "symbol": str(order.symbol) if order.symbol else None,
            "qty": float(order.qty) if order.qty else None,
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "order_type": str(order.type.value) if hasattr(order.type, "value") else str(order.type),
            "side": str(order.side.value) if hasattr(order.side, "value") else str(order.side),
            "limit_price": float(order.limit_price) if order.limit_price else None,
            "time_in_force": str(order.time_in_force.value) if hasattr(order.time_in_force, "value") else str(order.time_in_force),
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "legs": [
                {
                    "symbol": alpaca_to_polygon(str(leg.symbol)),
                    "side": str(leg.side.value) if hasattr(leg.side, "value") else str(leg.side),
                    "qty": float(leg.qty) if leg.qty else None,
                    "filled_qty": float(leg.filled_qty) if leg.filled_qty else 0,
                    "filled_avg_price": float(leg.filled_avg_price) if leg.filled_avg_price else None,
                }
                for leg in (order.legs or [])
            ] if order.legs else [],
        }

    @staticmethod
    def _serialize_position(pos) -> Dict[str, Any]:
        """Convert Alpaca Position object to plain dict."""
        symbol = str(pos.symbol)
        return {
            "symbol": alpaca_to_polygon(symbol) if len(symbol) > 10 else symbol,
            "symbol_alpaca": symbol,
            "qty": float(pos.qty),
            "side": str(pos.side.value) if hasattr(pos.side, "value") else str(pos.side),
            "avg_entry_price": float(pos.avg_entry_price),
            "current_price": float(pos.current_price) if pos.current_price else None,
            "market_value": float(pos.market_value) if pos.market_value else None,
            "unrealized_pl": float(pos.unrealized_pl) if pos.unrealized_pl else None,
            "unrealized_plpc": float(pos.unrealized_plpc) if pos.unrealized_plpc else None,
            "asset_class": str(pos.asset_class.value) if hasattr(pos.asset_class, "value") else str(pos.asset_class),
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_alpaca_client: Optional[AlpacaClient] = None


def get_alpaca_client() -> Optional[AlpacaClient]:
    """
    Get or create singleton AlpacaClient.
    Returns None if ALPACA_API_KEY is not configured (internal paper mode).
    """
    global _alpaca_client
    if _alpaca_client is not None:
        return _alpaca_client

    if not os.environ.get("ALPACA_API_KEY"):
        return None

    try:
        _alpaca_client = AlpacaClient()
        return _alpaca_client
    except AlpacaAuthError:
        logger.warning("[ALPACA] Client initialization failed — missing credentials")
        return None
