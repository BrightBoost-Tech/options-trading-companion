"""
Market Data Truth Layer
Centralized service for market data fetching, normalization, and IV context.
Implements the "Truth Layer" pattern to ensure consistency across the application.
"""
import os
import time
import requests
import logging
import re
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timedelta

from packages.quantum.services.market_data_cache import get_market_data_cache
from packages.quantum.analytics.factors import calculate_iv_rank, calculate_trend

# Use a module-level logger
logger = logging.getLogger(__name__)

class MarketDataTruthLayer:
    """
    Truth Layer for Market Data.
    Handles caching, rate limiting, normalization, and fallback logic.
    """

    def __init__(self, api_key: Optional[str] = None):
        # 1. Resolve API Key
        self.api_key = (
            api_key
            or os.getenv("MARKETDATA_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        if not self.api_key:
            logger.warning("No API key provided for MarketDataTruthLayer. Calls may fail.")

        self.base_url = "https://api.polygon.io"
        self.cache = get_market_data_cache()

        # Caching TTLs (in seconds)
        self.ttl_snapshot = 10
        self.ttl_option_chain = 60
        self.ttl_daily_bars = 43200  # 12 hours

    def _get_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _make_request(self, endpoint: str, params: Dict = None, retries: int = 2) -> Any:
        """Helper to make requests with retry logic."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        if self.api_key and "apiKey" not in params:
             params["apiKey"] = self.api_key

        attempt = 0
        while attempt <= retries:
            try:
                start_ts = time.time()
                response = requests.get(url, params=params, timeout=5)
                elapsed_ms = (time.time() - start_ts) * 1000

                if response.status_code == 200:
                    logger.info(f"OK {endpoint} {response.status_code} {elapsed_ms:.1f}ms")
                    return response.json()
                elif response.status_code == 429:
                    logger.warning(f"Rate limited on {endpoint}. Retrying...")
                    time.sleep(1 * (attempt + 1)) # Backoff
                else:
                    logger.error(f"Error {endpoint}: {response.status_code} {response.text}")
                    # Don't retry 4xx errors generally, except maybe 429 which we handled
                    if 400 <= response.status_code < 500:
                         return None

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on {endpoint}. Retrying...")
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed {endpoint}: {e}")

            attempt += 1
            time.sleep(0.5 * attempt)

        return None

    def snapshot_many(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetches snapshots for multiple tickers (up to 250).
        Returns a dict keyed by ticker.
        """
        if not tickers:
            return {}

        # 1. Normalize tickers and filter valid ones
        # Use existing logic for option symbol normalization
        normalized_tickers = [self.normalize_symbol(t) for t in tickers]
        # Remove duplicates
        unique_tickers = list(set(normalized_tickers))

        # 2. Check Cache
        results = {}
        missing_tickers = []

        for ticker in unique_tickers:
            cached = self.cache.get("snapshot_many", ticker)
            if cached:
                results[ticker] = cached
            else:
                missing_tickers.append(ticker)

        if not missing_tickers:
            return results

        # 3. Batch Fetch from Polygon
        # Polygon allows comma-separated list in ticker.any_of
        # Max chunk size logic if list is huge (Polygon limit is ~250 usually for URL length?
        # Actually universal snapshot takes `ticker.any_of` which can be long.
        # But let's be safe and chunk at 50 to avoid massive URLs or limits.)
        chunk_size = 50

        for i in range(0, len(missing_tickers), chunk_size):
            chunk = missing_tickers[i:i + chunk_size]
            tickers_str = ",".join(chunk)

            data = self._make_request("/v3/snapshot", params={"ticker.any_of": tickers_str})

            if data and "results" in data:
                for item in data["results"]:
                    ticker = item.get("ticker")
                    if not ticker:
                        continue

                    canonical = self._parse_snapshot_item(item)

                    # Cache it
                    self.cache.set("snapshot_many", ticker, canonical, self.ttl_snapshot)
                    results[ticker] = canonical
            else:
                logger.warning(f"No results for snapshot batch: {chunk}")

        return results

    def _parse_snapshot_item(self, item: Dict) -> Dict:
        """Parses a Polygon snapshot item into our canonical format."""
        # item structure varies by asset type but usually has:
        # last_quote: {P: ask, p: bid, t: timestamp} or similar
        # session: {price, change, ...}
        # But wait, Universal Snapshot structure:
        # { ticker: "...", type: "...", session: {...}, last_quote: {...}, last_trade: {...} }

        # Quote handling
        # Polygon V3 snapshot response for stocks:
        # last_quote: { "a": ask_price, "b": bid_price, "t": timestamp ... }
        # Options might have "last_quote" similarly.

        quote_data = item.get("last_quote", {})

        # Note: keys might differ based on asset class if not unified?
        # Checking docs: v3/snapshot returns Universal Snapshot.
        # "a" = ask price, "b" = bid price, "ax" = ask size, "bx" = bid size, "t" = timestamp

        ask = quote_data.get("a") or quote_data.get("P") # Fallback to P just in case (v2 style)
        bid = quote_data.get("b") or quote_data.get("p")

        # Convert to float if exists
        ask = float(ask) if ask is not None else None
        bid = float(bid) if bid is not None else None

        # Mid calculation
        mid = None
        if ask is not None and bid is not None and ask > 0 and bid > 0:
            mid = (ask + bid) / 2.0

        last_trade = item.get("last_trade", {})
        last_price = last_trade.get("p") or item.get("session", {}).get("close")
        if last_price is not None:
            last_price = float(last_price)

        day_data = item.get("session", {})

        # Greek handling (if available - e.g. for options)
        greeks = item.get("greeks", {})
        iv = item.get("implied_volatility")

        return {
            "ticker": item.get("ticker"),
            "asset_type": item.get("type"), # e.g. "CS" (Common Stock), "O" (Option)
            "quote": {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": last_price,
                "quote_ts": quote_data.get("t")
            },
            "day": {
                "o": day_data.get("open"),
                "h": day_data.get("high"),
                "l": day_data.get("low"),
                "c": day_data.get("close"),
                "v": day_data.get("volume"),
                "vwap": None # Not always in snapshot
            },
            "greeks": {
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega")
            },
            "iv": iv,
            "source": "polygon",
            "retrieved_ts": datetime.utcnow().isoformat(),
            "provider_ts": item.get("updated"), # Polygon timestamp in nanos usually? or millis?
            "staleness_ms": self._compute_staleness(item.get("updated"))
        }

    def _compute_staleness(self, provider_ts: Optional[Union[int, float]]) -> Optional[float]:
        """
        Computes staleness in milliseconds.
        Handles provider_ts in milliseconds, microseconds, or nanoseconds automatically.
        """
        if not provider_ts:
            return None

        try:
            # Current time in milliseconds
            now_ms = time.time() * 1000.0
            ts_val = float(provider_ts)

            # Determine unit based on magnitude
            # Unix 2025: ~1.7e9 (sec), ~1.7e12 (ms), ~1.7e15 (us), ~1.7e18 (ns)

            if ts_val > 1e16: # Nanoseconds (> 10^16)
                ts_ms = ts_val / 1e6
            elif ts_val > 1e14: # Microseconds (> 10^14)
                ts_ms = ts_val / 1e3
            elif ts_val > 1e11: # Milliseconds (> 10^11)
                ts_ms = ts_val
            else: # Seconds or invalid
                ts_ms = ts_val * 1000.0

            staleness = max(0.0, now_ms - ts_ms)
            return staleness

        except (ValueError, TypeError):
            return None

    def option_chain(self, underlying: str, *,
                     expiration_date: Optional[str] = None,
                     min_expiry: Optional[str] = None,
                     max_expiry: Optional[str] = None,
                     strike_range: Optional[float] = None,
                     right: Optional[str] = None) -> List[Dict]:
        """
        Fetches option chain snapshot for an underlying.
        Returns a list of canonical option objects.
        """
        # 1. Check Cache
        cache_key = f"{underlying}_{expiration_date}_{min_expiry}_{max_expiry}_{right}"
        cached = self.cache.get("option_chain", cache_key)
        if cached:
            return cached

        # 2. Fetch from Polygon
        # Endpoint: /v3/snapshot/options/{underlyingAsset}

        params = {"limit": 250}

        if expiration_date:
            params["expiration_date"] = expiration_date
        elif min_expiry or max_expiry:
             if min_expiry:
                 params["expiration_date.gte"] = min_expiry
             if max_expiry:
                 params["expiration_date.lte"] = max_expiry

        if right:
            # right should be 'call' or 'put'
            params["contract_type"] = right.lower()

        all_contracts = []
        url = f"/v3/snapshot/options/{underlying}"

        # Loop for pagination
        while url:
            data = self._make_request(url, params=params)
            if not data:
                break

            results = data.get("results", [])
            for item in results:
                # Client-side filtering for complex ranges if needed,
                # but let's trust server params for expiry/right.

                details = item.get("details", {})

                # Parse
                contract = {
                    "contract": details.get("ticker"),
                    "underlying": underlying,
                    "strike": details.get("strike_price"),
                    "expiry": details.get("expiration_date"),
                    "right": details.get("contract_type"), # 'call' or 'put'
                    "quote": {
                        "bid": item.get("last_quote", {}).get("b"),
                        "ask": item.get("last_quote", {}).get("a"),
                        "mid": None, # Compute below
                        "last": item.get("last_trade", {}).get("p")
                    },
                    "iv": item.get("implied_volatility"),
                    "greeks": {
                        "delta": item.get("greeks", {}).get("delta"),
                        "gamma": item.get("greeks", {}).get("gamma"),
                        "theta": item.get("greeks", {}).get("theta"),
                        "vega": item.get("greeks", {}).get("vega")
                    },
                    "oi": item.get("open_interest"),
                    "volume": item.get("day", {}).get("volume"),
                    "retrieved_ts": datetime.utcnow().isoformat(),
                    "source": "polygon"
                }

                # Fix Mid
                b = contract["quote"]["bid"]
                a = contract["quote"]["ask"]
                if b and a:
                    contract["quote"]["mid"] = (b + a) / 2.0

                all_contracts.append(contract)

            # Pagination
            # URL for next page is usually in data['next_url']
            # But wait, `_make_request` takes endpoint. `next_url` is full URL.
            # We need to handle this.
            next_url = data.get("next_url")
            if next_url:
                # Extract path and params from next_url or just use requests directly?
                # next_url already has params encoded.
                # Let's simple check: if next_url starts with https://api.polygon.io, strip base.
                url = next_url.replace(self.base_url, "")
                params = {} # Params are in the URL now
            else:
                url = None

        self.cache.set("option_chain", cache_key, all_contracts, self.ttl_option_chain)
        return all_contracts

    def daily_bars(self, ticker: str, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Fetches daily bars (adjusted).
        Wraps /v2/aggs/ticker/{ticker}/range/1/day/...
        """
        # Normalize
        symbol = self.normalize_symbol(ticker)

        # Cache key
        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")
        cache_key = f"{symbol}_{s_str}_{e_str}"

        cached = self.cache.get("daily_bars", cache_key)
        if cached:
            return cached

        # Fetch
        endpoint = f"/v2/aggs/ticker/{symbol}/range/1/day/{s_str}/{e_str}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000}

        data = self._make_request(endpoint, params)
        if not data or "results" not in data:
            return []

        # Parse
        bars = []
        for r in data["results"]:
            # r keys: c, h, l, o, v, vw, t
            dt = datetime.fromtimestamp(r["t"] / 1000.0)
            bars.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": r.get("o"),
                "high": r.get("h"),
                "low": r.get("l"),
                "close": r.get("c"),
                "volume": r.get("v"),
                "vwap": r.get("vw")
            })

        # Cache
        self.cache.set("daily_bars", cache_key, bars, self.ttl_daily_bars)
        return bars

    def get_trend(self, symbol: str) -> str:
        """Determines trend using simple moving averages (100 days)."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=150) # Fetch enough data
        bars = self.daily_bars(symbol, start_date, end_date)

        if not bars:
            return "NEUTRAL"

        prices = [b["close"] for b in bars]
        return calculate_trend(prices)

    def iv_context(self, underlying: str) -> Dict[str, Any]:
        """
        Returns IV context including Rank and Regime.
        Uses historical volatility proxy for now.
        """
        # 1. Fetch history (1 year for rank)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        bars = self.daily_bars(underlying, start_date, end_date)

        # Calculate returns
        if not bars or len(bars) < 30:
            return {
                "iv_rank": None,
                "iv_rank_source": "unknown",
                "iv_regime": None
            }

        closes = [b["close"] for b in bars]
        returns = []
        for i in range(1, len(closes)):
            r = (closes[i] - closes[i-1]) / closes[i-1]
            returns.append(r)

        # Calculate Rank
        # Note: calculate_iv_rank expects returns list
        rank = calculate_iv_rank(returns) # Returns 0..100 or None

        regime = None
        if rank is not None:
            if rank < 20:
                regime = "suppressed"
            elif rank < 60:
                regime = "normal"
            else:
                regime = "elevated"

        return {
            "iv_rank": rank,
            "iv_rank_source": "hv_proxy",
            "iv_regime": regime
        }

    def normalize_symbol(self, symbol: str) -> str:
        """
        Ensures proper Polygon format.
        O: prefix for options (length > 5 heuristic or known format).
        """
        # Clean inputs
        s = symbol.strip().upper()

        # Option heuristic: has numbers? length > 6?
        # Standard format: Ticker + Date + C/P + Price (e.g. AAPL230616C00150000)
        # Length of date(6) + type(1) + price(8) = 15 chars fixed suffix.
        # Plus ticker (1-5). So total 16-20 chars.
        # Simple check: if > 8 chars and contains digits, likely option.
        if len(s) > 6 and any(c.isdigit() for c in s):
            if not s.startswith("O:"):
                return f"O:{s}"

        return s

    # Backward compat
    _normalize_symbol = normalize_symbol
