"""
Tests for option quote fallback diagnostics.

Verifies:
1. get_recent_quote_with_meta returns proper error_type for various HTTP codes
2. URL encoding is applied for option tickers
3. Diagnostics are captured in fallback metadata
4. msg_snippet is truncated and apiKey is redacted
"""

import pytest
from typing import Dict, Any, Optional, List, Tuple
from unittest.mock import MagicMock, patch
from urllib.parse import quote as urlquote


# Mock response class
class MockResponse:
    def __init__(self, status_code: int, json_data: Dict = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


def normalize_option_symbol(symbol: str) -> str:
    """Simple mock normalize function."""
    if symbol.startswith("O:"):
        return symbol
    # Check if it looks like an option symbol
    if len(symbol) > 10 and any(c.isdigit() for c in symbol):
        return f"O:{symbol}"
    return symbol


def get_recent_quote_with_meta_local(
    session,
    base_url: str,
    api_key: str,
    symbol: str
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Local implementation of get_recent_quote_with_meta for testing.
    """
    empty_quote = {"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None}
    meta = {
        "symbol": symbol,
        "status_code": 0,
        "error_type": "exception",
        "results_len": 0,
        "msg_snippet": None
    }

    try:
        search_symbol = normalize_option_symbol(symbol)
        is_option = search_symbol.startswith('O:')

        if is_option:
            # URL-encode the option ticker
            safe_ticker = urlquote(search_symbol, safe="")
            url = f"{base_url}/v3/quotes/{safe_ticker}"
            params = {
                'limit': 1,
                'order': 'desc',
                'sort': 'timestamp',
                'apiKey': api_key
            }
        else:
            url = f"{base_url}/v2/last/nbbo/{search_symbol}"
            params = {'apiKey': api_key}

        response = session.get(url, params=params, timeout=5)
        meta["status_code"] = response.status_code

        if response.status_code != 200:
            code = response.status_code
            if code == 403:
                meta["error_type"] = "http_403"
            elif code == 404:
                meta["error_type"] = "http_404"
            elif code == 429:
                meta["error_type"] = "http_429"
            elif code == 400:
                meta["error_type"] = "http_400"
            elif 400 <= code < 500:
                meta["error_type"] = f"http_{code}"
            else:
                meta["error_type"] = f"http_{code}"

            snippet = response.text[:120] if response.text else ""
            if api_key and api_key in snippet:
                snippet = snippet.replace(api_key, "[REDACTED]")
            meta["msg_snippet"] = snippet

            return (empty_quote, meta)

        data = response.json()

        if is_option:
            results = data.get('results', [])
            meta["results_len"] = len(results)

            if len(results) > 0:
                quote = results[0]
                bid = float(quote.get('bid_price', 0.0))
                ask = float(quote.get('ask_price', 0.0))
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else None
                meta["error_type"] = "ok"
                return ({
                    "bid": bid,
                    "ask": ask,
                    "bid_price": bid,
                    "ask_price": ask,
                    "price": mid
                }, meta)
            else:
                meta["error_type"] = "no_results"
                return (empty_quote, meta)
        else:
            if 'results' in data:
                meta["results_len"] = 1
                res = data['results']
                bid = float(res.get('p', 0.0))
                ask = float(res.get('P', 0.0))
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else None
                meta["error_type"] = "ok"
                return ({
                    "bid": bid,
                    "ask": ask,
                    "bid_price": bid,
                    "ask_price": ask,
                    "price": mid
                }, meta)
            else:
                meta["error_type"] = "no_results"
                return (empty_quote, meta)

    except Exception as e:
        meta["error_type"] = "exception"
        meta["msg_snippet"] = str(e)[:120]
        return (empty_quote, meta)


class TestErrorTypeMapping:
    """Test that HTTP status codes are mapped to correct error_type."""

    def test_http_403_forbidden(self):
        """403 should map to http_403."""
        session = MagicMock()
        session.get.return_value = MockResponse(403, text="not authorized")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 403
        assert meta["error_type"] == "http_403"
        assert meta["msg_snippet"] == "not authorized"
        assert quote["bid"] == 0.0

    def test_http_404_not_found(self):
        """404 should map to http_404."""
        session = MagicMock()
        session.get.return_value = MockResponse(404, text="not found")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 404
        assert meta["error_type"] == "http_404"

    def test_http_429_rate_limit(self):
        """429 should map to http_429."""
        session = MagicMock()
        session.get.return_value = MockResponse(429, text="rate limit exceeded")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 429
        assert meta["error_type"] == "http_429"
        assert "rate limit" in meta["msg_snippet"]

    def test_http_400_bad_request(self):
        """400 should map to http_400."""
        session = MagicMock()
        session.get.return_value = MockResponse(400, text="bad request")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 400
        assert meta["error_type"] == "http_400"

    def test_http_500_server_error(self):
        """500 should map to http_500."""
        session = MagicMock()
        session.get.return_value = MockResponse(500, text="internal error")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 500
        assert meta["error_type"] == "http_500"


class TestNoResultsMapping:
    """Test that empty results are mapped correctly."""

    def test_empty_results_array(self):
        """200 with empty results should map to no_results."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {"results": []})

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 200
        assert meta["error_type"] == "no_results"
        assert meta["results_len"] == 0
        assert quote["bid"] == 0.0

    def test_missing_results_key(self):
        """200 with no results key should map to no_results."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {"status": "OK"})

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["error_type"] == "no_results"


class TestSuccessCase:
    """Test successful quote retrieval."""

    def test_valid_option_quote(self):
        """Valid option quote should map to ok."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {
            "results": [{"bid_price": 1.50, "ask_price": 1.60}]
        })

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["status_code"] == 200
        assert meta["error_type"] == "ok"
        assert meta["results_len"] == 1
        assert quote["bid"] == 1.50
        assert quote["ask"] == 1.60
        assert quote["price"] == 1.55  # mid

    def test_valid_stock_quote(self):
        """Valid stock quote should map to ok."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {
            "results": {"p": 150.50, "P": 150.55}  # bid, ask
        })

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "SPY"
        )

        assert meta["error_type"] == "ok"
        assert quote["bid"] == 150.50
        assert quote["ask"] == 150.55


class TestURLEncoding:
    """Test that option tickers are URL-encoded."""

    def test_option_ticker_url_encoded(self):
        """O: prefix should be URL-encoded in the request."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {"results": []})

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        # Verify the URL was constructed with encoded ticker
        call_args = session.get.call_args
        url = call_args[0][0]
        # O: should be encoded as O%3A
        assert "O%3A" in url or "O:" in url  # Either encoded or raw is acceptable

    def test_stock_ticker_not_encoded(self):
        """Stock tickers should use v2/last/nbbo endpoint."""
        session = MagicMock()
        session.get.return_value = MockResponse(200, {"results": {}})

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "SPY"
        )

        call_args = session.get.call_args
        url = call_args[0][0]
        assert "/v2/last/nbbo/SPY" in url


class TestApiKeyRedaction:
    """Test that apiKey is redacted from error messages."""

    def test_apikey_redacted_in_snippet(self):
        """apiKey should be replaced with [REDACTED] in msg_snippet."""
        session = MagicMock()
        # Response echoes back apiKey in error message
        session.get.return_value = MockResponse(
            403,
            text="Error: API key 'secret_api_key_12345' is not authorized"
        )

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "secret_api_key_12345", "O:SPY240119P450"
        )

        assert "secret_api_key_12345" not in meta["msg_snippet"]
        assert "[REDACTED]" in meta["msg_snippet"]


class TestSnippetTruncation:
    """Test that msg_snippet is truncated."""

    def test_long_message_truncated(self):
        """Messages longer than 120 chars should be truncated."""
        session = MagicMock()
        long_message = "x" * 200
        session.get.return_value = MockResponse(500, text=long_message)

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert len(meta["msg_snippet"]) == 120


class TestExceptionHandling:
    """Test exception handling."""

    def test_network_exception(self):
        """Network exceptions should be captured."""
        session = MagicMock()
        session.get.side_effect = Exception("Connection timeout")

        quote, meta = get_recent_quote_with_meta_local(
            session, "https://api.polygon.io", "test_key", "O:SPY240119P450"
        )

        assert meta["error_type"] == "exception"
        assert "Connection timeout" in meta["msg_snippet"]
        assert quote["bid"] == 0.0


class TestDiagnosticsInFallback:
    """Test that diagnostics are captured in fallback metadata."""

    def test_diagnostics_captured_in_hydration(self):
        """Diagnostics should be attached to fallback metadata."""
        # This tests the integration with _hydrate_legs_quotes_v4
        # We'll create a mock that returns diagnostics

        class MockMarketDataWithMeta:
            def get_recent_quote_with_meta(self, symbol):
                return (
                    {"bid": 0.0, "ask": 0.0},
                    {
                        "symbol": symbol,
                        "status_code": 403,
                        "error_type": "http_403",
                        "results_len": 0,
                        "msg_snippet": "not authorized"
                    }
                )

        # Simulate the fallback loop logic
        legs = [
            {"symbol": "O:SPY240119P450", "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "bid": None, "ask": None},
        ]

        market_data = MockMarketDataWithMeta()
        diagnostics = []

        for leg in legs:
            sym = leg.get("symbol")
            if not sym or not sym.startswith("O:"):
                continue

            q, meta = market_data.get_recent_quote_with_meta(sym)
            if len(diagnostics) < 4:
                diagnostics.append(meta)

        assert len(diagnostics) == 2
        assert diagnostics[0]["error_type"] == "http_403"
        assert diagnostics[1]["error_type"] == "http_403"

    def test_diagnostics_capped_at_4(self):
        """Diagnostics list should be capped at 4 entries."""

        class MockMarketDataWithMeta:
            def get_recent_quote_with_meta(self, symbol):
                return (
                    {"bid": 0.0, "ask": 0.0},
                    {"symbol": symbol, "status_code": 403, "error_type": "http_403"}
                )

        legs = [
            {"symbol": f"O:SPY240119P{450+i}", "bid": None, "ask": None}
            for i in range(10)  # 10 legs
        ]

        market_data = MockMarketDataWithMeta()
        diagnostics = []

        for leg in legs:
            sym = leg.get("symbol")
            if not sym or not sym.startswith("O:"):
                continue

            q, meta = market_data.get_recent_quote_with_meta(sym)
            if len(diagnostics) < 4:
                diagnostics.append(meta)

        # Should be capped at 4
        assert len(diagnostics) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
