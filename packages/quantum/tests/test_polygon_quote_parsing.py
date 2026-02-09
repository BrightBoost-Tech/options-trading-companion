"""
Tests for Polygon option quote parsing with multi-key support.

Verifies:
1. _get_first() helper returns first non-None value
2. _extract_last_quote_fields() handles all key variants
3. _extract_last_trade_fields() handles all key variants with session fallback
4. provider_ts is computed from multiple timestamp sources
"""

import pytest
from typing import Dict, Any, Optional, List, Tuple


# Replicate helper functions for testing
def _get_first(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    """Return first non-None value from dict using ordered list of keys."""
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _extract_last_quote_fields(last_quote: Optional[Dict]) -> Tuple[Optional[float], Optional[float], Optional[int], Optional[int], Optional[int]]:
    """
    Extract quote fields from Polygon last_quote with multi-key support.

    Returns: (bid, ask, quote_ts, bid_size, ask_size)
    """
    if not last_quote:
        return (None, None, None, None, None)

    # Extract with fallback keys
    ask_raw = _get_first(last_quote, ["a", "ask", "P", "ap", "ask_price"])
    bid_raw = _get_first(last_quote, ["b", "bid", "p", "bp", "bid_price"])
    ts_raw = _get_first(last_quote, ["t", "timestamp", "quote_ts", "updated", "last_updated"])
    bid_size_raw = _get_first(last_quote, ["bx", "bid_size", "bs"])
    ask_size_raw = _get_first(last_quote, ["ax", "ask_size", "as"])

    def to_float(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def to_int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return (
        to_float(bid_raw),
        to_float(ask_raw),
        to_int(ts_raw),
        to_int(bid_size_raw),
        to_int(ask_size_raw)
    )


def _extract_last_trade_fields(last_trade: Optional[Dict], session: Optional[Dict] = None) -> Tuple[Optional[float], Optional[int]]:
    """
    Extract trade fields from Polygon last_trade with multi-key support.

    Returns: (last_price, trade_ts)
    """
    if not last_trade:
        last_trade = {}

    price_raw = _get_first(last_trade, ["p", "price", "last", "c", "close"])
    ts_raw = _get_first(last_trade, ["t", "timestamp", "trade_ts", "updated"])

    # Fallback to session close if no trade price
    if price_raw is None and session:
        price_raw = session.get("close")

    def to_float(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def to_int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return (to_float(price_raw), to_int(ts_raw))


class TestGetFirst:
    """Test _get_first helper function."""

    def test_returns_first_key(self):
        """Returns value of first key in list."""
        d = {"a": 1.0, "b": 2.0}
        result = _get_first(d, ["a", "b"])
        assert result == 1.0

    def test_skips_missing_keys(self):
        """Skips keys that don't exist."""
        d = {"b": 2.0}
        result = _get_first(d, ["a", "b"])
        assert result == 2.0

    def test_skips_none_values(self):
        """Skips keys with None values."""
        d = {"a": None, "b": 2.0}
        result = _get_first(d, ["a", "b"])
        assert result == 2.0

    def test_returns_none_if_all_missing(self):
        """Returns None if no keys match."""
        d = {"x": 1.0}
        result = _get_first(d, ["a", "b"])
        assert result is None

    def test_returns_none_for_empty_dict(self):
        """Returns None for empty dict."""
        result = _get_first({}, ["a", "b"])
        assert result is None

    def test_returns_none_for_none_dict(self):
        """Returns None for None input."""
        result = _get_first(None, ["a", "b"])
        assert result is None

    def test_returns_zero_not_none(self):
        """Zero is a valid value, not treated as None."""
        d = {"a": 0, "b": 1.0}
        result = _get_first(d, ["a", "b"])
        assert result == 0


class TestExtractLastQuoteFields:
    """Test _extract_last_quote_fields with various key formats."""

    def test_standard_polygon_keys(self):
        """Standard Polygon format with a/b keys."""
        quote = {"a": 1.60, "b": 1.50, "t": 1700000000000, "ax": 100, "bx": 200}
        bid, ask, ts, bid_size, ask_size = _extract_last_quote_fields(quote)
        assert bid == 1.50
        assert ask == 1.60
        assert ts == 1700000000000
        assert bid_size == 200
        assert ask_size == 100

    def test_alternative_keys_ask_bid(self):
        """Alternative ask/bid keys."""
        quote = {"ask": 2.50, "bid": 2.40, "timestamp": 1700000000000}
        bid, ask, ts, _, _ = _extract_last_quote_fields(quote)
        assert bid == 2.40
        assert ask == 2.50
        assert ts == 1700000000000

    def test_uppercase_p_keys(self):
        """Uppercase P for ask (some option formats)."""
        quote = {"P": 3.50, "p": 3.40, "updated": 1700000000000}
        bid, ask, ts, _, _ = _extract_last_quote_fields(quote)
        assert bid == 3.40
        assert ask == 3.50
        assert ts == 1700000000000

    def test_ask_price_bid_price_keys(self):
        """Full ask_price/bid_price keys."""
        quote = {"ask_price": 4.50, "bid_price": 4.40}
        bid, ask, _, _, _ = _extract_last_quote_fields(quote)
        assert bid == 4.40
        assert ask == 4.50

    def test_none_quote_returns_all_none(self):
        """None quote returns tuple of None."""
        bid, ask, ts, bid_size, ask_size = _extract_last_quote_fields(None)
        assert bid is None
        assert ask is None
        assert ts is None
        assert bid_size is None
        assert ask_size is None

    def test_empty_quote_returns_all_none(self):
        """Empty quote returns tuple of None."""
        bid, ask, ts, bid_size, ask_size = _extract_last_quote_fields({})
        assert bid is None
        assert ask is None
        assert ts is None

    def test_string_values_converted(self):
        """String values are converted to proper types."""
        quote = {"a": "1.60", "b": "1.50", "t": "1700000000000"}
        bid, ask, ts, _, _ = _extract_last_quote_fields(quote)
        assert bid == 1.50
        assert ask == 1.60
        assert ts == 1700000000000

    def test_invalid_values_return_none(self):
        """Invalid values return None instead of raising."""
        quote = {"a": "invalid", "b": [1, 2, 3], "t": {"nested": True}}
        bid, ask, ts, _, _ = _extract_last_quote_fields(quote)
        assert bid is None
        assert ask is None
        assert ts is None


class TestExtractLastTradeFields:
    """Test _extract_last_trade_fields with various key formats."""

    def test_standard_p_key(self):
        """Standard Polygon format with p key."""
        trade = {"p": 100.50, "t": 1700000000000}
        price, ts = _extract_last_trade_fields(trade)
        assert price == 100.50
        assert ts == 1700000000000

    def test_price_key(self):
        """Alternative price key."""
        trade = {"price": 101.50, "timestamp": 1700000000000}
        price, ts = _extract_last_trade_fields(trade)
        assert price == 101.50
        assert ts == 1700000000000

    def test_last_key(self):
        """Alternative last key."""
        trade = {"last": 102.50}
        price, ts = _extract_last_trade_fields(trade)
        assert price == 102.50
        assert ts is None

    def test_close_key(self):
        """Close key (sometimes used in summaries)."""
        trade = {"c": 103.50, "updated": 1700000000000}
        price, ts = _extract_last_trade_fields(trade)
        assert price == 103.50
        assert ts == 1700000000000

    def test_session_fallback(self):
        """Falls back to session.close if no trade price."""
        trade = {}
        session = {"close": 104.50}
        price, ts = _extract_last_trade_fields(trade, session)
        assert price == 104.50

    def test_session_fallback_only_when_no_trade(self):
        """Session fallback only used when trade price missing."""
        trade = {"p": 100.50}
        session = {"close": 104.50}
        price, ts = _extract_last_trade_fields(trade, session)
        assert price == 100.50  # Trade price preferred

    def test_none_trade_returns_none(self):
        """None trade returns None tuple (no session)."""
        price, ts = _extract_last_trade_fields(None)
        assert price is None
        assert ts is None

    def test_none_trade_with_session_fallback(self):
        """None trade with session fallback."""
        session = {"close": 105.50}
        price, ts = _extract_last_trade_fields(None, session)
        assert price == 105.50
        assert ts is None


class TestProviderTimestampLogic:
    """Test provider_ts computed from multiple sources."""

    def test_quote_ts_preferred(self):
        """Quote timestamp preferred when available."""
        quote = {"a": 1.0, "b": 1.0, "t": 1700000001000}
        trade = {"p": 1.0, "t": 1700000002000}

        _, _, quote_ts, _, _ = _extract_last_quote_fields(quote)
        _, trade_ts = _extract_last_trade_fields(trade)

        # Simulate provider_ts logic: prefer quote_ts
        provider_ts = quote_ts or trade_ts
        assert provider_ts == 1700000001000

    def test_trade_ts_fallback(self):
        """Trade timestamp used when quote timestamp missing."""
        quote = {"a": 1.0, "b": 1.0}  # No timestamp
        trade = {"p": 1.0, "t": 1700000002000}

        _, _, quote_ts, _, _ = _extract_last_quote_fields(quote)
        _, trade_ts = _extract_last_trade_fields(trade)

        provider_ts = quote_ts or trade_ts
        assert provider_ts == 1700000002000

    def test_none_when_no_timestamps(self):
        """None when no timestamps available."""
        quote = {"a": 1.0, "b": 1.0}
        trade = {"p": 1.0}

        _, _, quote_ts, _, _ = _extract_last_quote_fields(quote)
        _, trade_ts = _extract_last_trade_fields(trade)

        provider_ts = quote_ts or trade_ts
        assert provider_ts is None


class TestRealWorldPolygonPayloads:
    """Test with real-world Polygon API payload shapes."""

    def test_option_snapshot_payload(self):
        """Test parsing real option snapshot format."""
        # Real Polygon option snapshot shape
        item = {
            "last_quote": {
                "a": 2.15,
                "b": 2.05,
                "t": 1699390800000,
                "ax": 50,
                "bx": 100
            },
            "last_trade": {
                "p": 2.10,
                "t": 1699390750000
            }
        }

        bid, ask, quote_ts, bid_size, ask_size = _extract_last_quote_fields(item["last_quote"])
        last_price, trade_ts = _extract_last_trade_fields(item["last_trade"])

        assert bid == 2.05
        assert ask == 2.15
        assert quote_ts == 1699390800000
        assert bid_size == 100
        assert ask_size == 50
        assert last_price == 2.10
        assert trade_ts == 1699390750000

    def test_stock_snapshot_payload(self):
        """Test parsing stock snapshot format."""
        item = {
            "last_quote": {
                "bid": 150.50,
                "ask": 150.55,
                "bid_size": 1000,
                "ask_size": 500,
                "timestamp": 1699390800000
            },
            "last_trade": {
                "price": 150.52,
                "timestamp": 1699390799000
            }
        }

        bid, ask, quote_ts, bid_size, ask_size = _extract_last_quote_fields(item["last_quote"])
        last_price, trade_ts = _extract_last_trade_fields(item["last_trade"])

        assert bid == 150.50
        assert ask == 150.55
        assert quote_ts == 1699390800000
        assert last_price == 150.52

    def test_sparse_option_payload(self):
        """Test parsing sparse option data (missing fields)."""
        # Sometimes options have sparse quote data
        item = {
            "last_quote": {
                "a": 0.05,  # Only ask
                # bid missing
            },
            "last_trade": {
                # No trade data
            },
            "session": {
                "close": 0.04
            }
        }

        bid, ask, _, _, _ = _extract_last_quote_fields(item["last_quote"])
        last_price, _ = _extract_last_trade_fields(item["last_trade"], item["session"])

        assert bid is None
        assert ask == 0.05
        assert last_price == 0.04  # Fell back to session.close


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
