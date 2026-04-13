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
import random
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
    with production-grade retry logic, logging, and OCC symbol translation.
    """

    # Retry config: exponential backoff with jitter
    MAX_RETRIES = 10
    BASE_DELAY = 0.5   # seconds
    MAX_DELAY = 60.0    # seconds — cap for exponential backoff
    JITTER_RANGE = 0.25 # ±25% jitter on each delay

    # Transient error keywords (checked case-insensitively in error strings)
    _TRANSIENT_KEYWORDS = (
        "429", "500", "502", "503", "504",
        "timeout", "timed out", "connection reset",
        "connection refused", "connection aborted",
        "temporary failure", "name resolution",
        "broken pipe", "eof occurred",
    )

    # Auth error keywords — trigger re-auth instead of immediate failure
    _AUTH_KEYWORDS = ("401", "403", "unauthorized", "forbidden")

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

        self._init_trading_client()
        self._init_data_client()
        mode_label = "PAPER" if self.paper else "LIVE"
        logger.info(f"[ALPACA] Client initialized in {mode_label} mode")

    def _init_trading_client(self):
        """(Re-)initialize the underlying alpaca-py TradingClient."""
        from alpaca.trading.client import TradingClient
        self._client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=self.paper,
        )

    def _init_data_client(self):
        """Initialize the alpaca-py StockHistoricalDataClient for equity market data."""
        from alpaca.data.historical import StockHistoricalDataClient
        self._data_client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
        )

    def _refresh_auth(self) -> bool:
        """
        Re-initialize the trading client to refresh auth state.
        Returns True if re-auth succeeded, False otherwise.
        """
        try:
            logger.warning("[ALPACA] Refreshing auth — re-initializing client")
            self._init_trading_client()
            self._init_data_client()
            # Validate by fetching account
            self._client.get_account()
            logger.info("[ALPACA] Auth refresh succeeded")
            return True
        except Exception as e:
            logger.error(f"[ALPACA] Auth refresh failed: {e}")
            return False

    # ── Retry helper ──────────────────────────────────────────────────

    def _call_with_retry(self, fn, *args, **kwargs) -> Any:
        """
        Call fn with exponential backoff + jitter on transient errors.

        - Base 500ms, max 60s, up to 10 retries
        - Auto re-auth on 401/403 (once per call chain)
        - Broad transient detection: 429, 5xx, timeout, connection errors
        """
        last_err = None
        auth_refreshed = False  # Only attempt re-auth once per call chain

        for attempt in range(self.MAX_RETRIES):
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                last_err = e
                err_str = str(e).lower()

                # Check for auth errors first — try re-auth once
                is_auth_error = any(k in err_str for k in self._AUTH_KEYWORDS)
                if is_auth_error and not auth_refreshed:
                    auth_refreshed = True
                    logger.warning(
                        f"[ALPACA] Auth error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Attempting re-auth..."
                    )
                    if self._refresh_auth():
                        # Re-auth succeeded, retry immediately (no backoff)
                        continue
                    else:
                        # Re-auth failed — this is fatal
                        raise AlpacaAuthError(
                            f"Auth error and re-auth failed: {last_err}"
                        )

                # Check for transient errors
                is_transient = any(k in err_str for k in self._TRANSIENT_KEYWORDS)
                if is_transient and attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff with jitter, capped at MAX_DELAY
                    base = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
                    jitter = base * random.uniform(-self.JITTER_RANGE, self.JITTER_RANGE)
                    delay = max(0.1, base + jitter)
                    logger.warning(
                        f"[ALPACA] Transient error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                else:
                    # Non-transient, non-auth error — fail immediately
                    break

        raise AlpacaError(
            f"Alpaca API call failed after {self.MAX_RETRIES} attempts: {last_err}"
        )

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
            PositionIntent,
        )

        legs = order_request.get("legs", [])
        limit_price = round(float(order_request.get("limit_price") or 0), 2) or None
        tif_str = order_request.get("time_in_force", "day").upper()
        tif = TimeInForce.DAY if tif_str == "DAY" else TimeInForce.GTC

        if not legs:
            raise AlpacaOrderError("Order must have at least one leg")

        # Build typed leg requests with position_intent (required for mleg)
        # ratio_qty is always 1 per leg — contract count goes on parent qty.
        # Alpaca requires leg ratios to be relatively prime (GCD must be 1).
        alpaca_legs = []
        for i, leg in enumerate(legs):
            leg_symbol = polygon_to_alpaca(leg["symbol"])
            is_buy = leg["side"].lower() in ("buy", "buy_to_open", "buy_to_close")
            side = OrderSide.BUY if is_buy else OrderSide.SELL

            # Use position_intent from leg if provided (close orders set this),
            # otherwise default to open intent
            leg_intent = leg.get("position_intent", "").lower()
            intent_map = {
                "buy_to_open": PositionIntent.BUY_TO_OPEN,
                "buy_to_close": PositionIntent.BUY_TO_CLOSE,
                "sell_to_open": PositionIntent.SELL_TO_OPEN,
                "sell_to_close": PositionIntent.SELL_TO_CLOSE,
            }
            intent = intent_map.get(leg_intent,
                                    PositionIntent.BUY_TO_OPEN if is_buy else PositionIntent.SELL_TO_OPEN)
            logger.info(
                f"[ALPACA_SUBMIT] leg[{i}] symbol={leg_symbol[:20]} "
                f"side_raw={leg['side']!r} → OrderSide={side.value} "
                f"intent_raw={leg.get('position_intent')!r} → PositionIntent={intent.value}"
            )
            alpaca_legs.append(OptionLegRequest(
                symbol=leg_symbol,
                side=side,
                ratio_qty=1,
                position_intent=intent,
            ))

        # Parent qty = number of contracts (spreads). Leg ratio_qty is always 1.
        qty = float(order_request.get("qty") or order_request.get("quantity") or legs[0].get("qty", 1))
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

        try:
            order = self._call_with_retry(self._client.submit_order, req)
        except Exception as e:
            err_str = str(e)
            # Log the full Alpaca error for debugging
            logger.error(
                f"[ALPACA] Submission rejected: {len(legs)} legs, "
                f"limit={limit_price}, error={err_str}"
            )
            raise

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

    def cancel_open_orders_for_symbols(self, symbols: List[str]) -> List[str]:
        """
        Cancel all open orders that involve any of the given contract symbols.

        Used before submitting close orders to avoid Alpaca's held_for_orders
        rejection when an existing open order locks the contract.

        Returns list of cancelled Alpaca order IDs.
        """
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        if not symbols:
            return []

        # Alpaca GetOrdersRequest.symbols filters by these exact symbols
        alpaca_symbols = [polygon_to_alpaca(s) for s in symbols]
        req = GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=alpaca_symbols,
        )

        try:
            open_orders = self._call_with_retry(self._client.get_orders, req)
        except Exception as e:
            logger.warning(f"[ALPACA] Failed to fetch open orders for cancel: {e}")
            return []

        cancelled = []
        for order in open_orders:
            oid = str(order.id)
            try:
                self._call_with_retry(self._client.cancel_order_by_id, oid)
                cancelled.append(oid)
                logger.info(f"[ALPACA] Cancelled conflicting order {oid} for close submission")
            except Exception as e:
                logger.warning(f"[ALPACA] Failed to cancel order {oid}: {e}")

        if cancelled:
            # Brief pause for Alpaca to process cancellations
            time.sleep(0.5)

        return cancelled

    # ── Positions ─────────────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        """All current positions."""
        positions = self._call_with_retry(self._client.get_all_positions)
        return [self._serialize_position(p) for p in positions]

    def get_option_positions(self) -> List[Dict[str, Any]]:
        """Filter to option positions only (symbol length > 10 heuristic)."""
        all_pos = self.get_positions()
        return [p for p in all_pos if len(p.get("symbol", "")) > 10]

    # ── Equity Market Data ─────────────────────────────────────────

    def get_stock_snapshots(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Batch equity snapshots via Alpaca Data API.

        Returns dict keyed by symbol, each containing:
          quote: {bid, ask, mid, last, bid_size, ask_size, quote_ts}
          day:   {o, h, l, c, v, vwap}
          prev_day: {o, h, l, c, v, vwap}  (previous daily bar)
        """
        from alpaca.data.requests import StockSnapshotRequest

        if not symbols:
            return {}

        req = StockSnapshotRequest(symbol_or_symbols=symbols)
        raw = self._call_with_retry(self._data_client.get_stock_snapshot, req)

        results = {}
        for sym, snap in raw.items():
            quote = snap.latest_quote
            trade = snap.latest_trade
            bar = snap.daily_bar
            prev = snap.previous_daily_bar

            bid = float(quote.bid_price) if quote and quote.bid_price else None
            ask = float(quote.ask_price) if quote and quote.ask_price else None
            mid = (bid + ask) / 2.0 if bid and ask and bid > 0 and ask > 0 else None

            quote_ts = int(quote.timestamp.timestamp() * 1000) if quote and quote.timestamp else None

            results[sym] = {
                "ticker": sym,
                "asset_type": "CS",
                "source": "alpaca",
                "provider_ts": quote_ts,
                "quote": {
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "last": float(trade.price) if trade and trade.price else None,
                    "quote_ts": quote_ts,
                    "bid_size": float(quote.bid_size) if quote and quote.bid_size else None,
                    "ask_size": float(quote.ask_size) if quote and quote.ask_size else None,
                },
                "day": {
                    "o": float(bar.open) if bar else None,
                    "h": float(bar.high) if bar else None,
                    "l": float(bar.low) if bar else None,
                    "c": float(bar.close) if bar else None,
                    "v": float(bar.volume) if bar else None,
                    "vwap": float(bar.vwap) if bar and bar.vwap else None,
                },
                "prev_day": {
                    "o": float(prev.open) if prev else None,
                    "h": float(prev.high) if prev else None,
                    "l": float(prev.low) if prev else None,
                    "c": float(prev.close) if prev else None,
                    "v": float(prev.volume) if prev else None,
                    "vwap": float(prev.vwap) if prev and prev.vwap else None,
                } if prev else {},
            }

        return results

    def get_stock_bars(
        self, symbol: str, start: "datetime", end: "datetime"
    ) -> List[Dict[str, Any]]:
        """
        Daily bars for an equity via Alpaca Data API.

        Returns list of dicts with: date, open, high, low, close, volume, vwap.
        """
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            adjustment="all",
        )
        raw = self._call_with_retry(self._data_client.get_stock_bars, req)
        bar_set = raw.get(symbol) or raw.get(symbol.upper()) or []

        bars = []
        for bar in bar_set:
            bars.append({
                "date": bar.timestamp.strftime("%Y-%m-%d"),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "vwap": float(bar.vwap) if bar.vwap else None,
            })
        return bars

    def get_stock_latest_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Latest NBBO quotes for equities via Alpaca Data API.

        Returns dict keyed by symbol with: bid, ask, bid_price, ask_price, price (mid).
        """
        from alpaca.data.requests import StockLatestQuoteRequest

        if not symbols:
            return {}

        req = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        raw = self._call_with_retry(self._data_client.get_stock_latest_quote, req)

        results = {}
        for sym, quote in raw.items():
            bid = float(quote.bid_price) if quote.bid_price else 0.0
            ask = float(quote.ask_price) if quote.ask_price else 0.0
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else None
            results[sym] = {
                "bid": bid,
                "ask": ask,
                "bid_price": bid,
                "ask_price": ask,
                "price": mid,
                "bid_size": float(quote.bid_size) if quote.bid_size else 0,
                "ask_size": float(quote.ask_size) if quote.ask_size else 0,
            }
        return results

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
