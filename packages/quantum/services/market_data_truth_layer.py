"""
Market Data Truth Layer
Centralized service for market data fetching, normalization, and IV context.
Implements the "Truth Layer" pattern to ensure consistency across the application.
"""
import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import re
from typing import List, Dict, Optional, Any, Union, Tuple
from datetime import datetime, timedelta
import concurrent.futures
from pydantic import BaseModel

from packages.quantum.services.market_data_cache import get_market_data_cache
from packages.quantum.services.cache_key_builder import normalize_symbol
from packages.quantum.analytics.factors import calculate_iv_rank, calculate_trend

# Use a module-level logger
logger = logging.getLogger(__name__)

# =============================================================================
# V4 Configuration (env-configurable with safe defaults)
# =============================================================================
# Default values (used when env vars are not set)
_DEFAULT_MAX_FRESHNESS_MS = 60000
_DEFAULT_MIN_QUALITY_SCORE = 60
_DEFAULT_WIDE_SPREAD_PCT = 0.10

# Legacy module-level constants for backward compatibility
# NOTE: These are read at import time; prefer getter functions for dynamic env access
MARKETDATA_MAX_FRESHNESS_MS = int(os.getenv("MARKETDATA_MAX_FRESHNESS_MS", str(_DEFAULT_MAX_FRESHNESS_MS)))
MARKETDATA_MIN_QUALITY_SCORE = int(os.getenv("MARKETDATA_MIN_QUALITY_SCORE", str(_DEFAULT_MIN_QUALITY_SCORE)))
MARKETDATA_WIDE_SPREAD_PCT = float(os.getenv("MARKETDATA_WIDE_SPREAD_PCT", str(_DEFAULT_WIDE_SPREAD_PCT)))


def get_marketdata_max_freshness_ms() -> int:
    """Get max freshness threshold in milliseconds (env-safe, reads at call time)."""
    return int(os.getenv("MARKETDATA_MAX_FRESHNESS_MS", str(_DEFAULT_MAX_FRESHNESS_MS)))


def get_marketdata_min_quality_score() -> int:
    """Get minimum quality score threshold (env-safe, reads at call time)."""
    return int(os.getenv("MARKETDATA_MIN_QUALITY_SCORE", str(_DEFAULT_MIN_QUALITY_SCORE)))


def get_marketdata_wide_spread_pct() -> float:
    """Get wide spread percentage threshold (env-safe, reads at call time)."""
    return float(os.getenv("MARKETDATA_WIDE_SPREAD_PCT", str(_DEFAULT_WIDE_SPREAD_PCT)))


# =============================================================================
# V4 Canonical Models (Pydantic)
# =============================================================================
class TruthQuoteV4(BaseModel):
    """Canonical quote structure for V4 snapshots."""
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None


class TruthTimestampsV4(BaseModel):
    """Timestamp metadata for V4 snapshots."""
    source_ts: Optional[int] = None  # Provider timestamp (ms)
    received_ts: int                  # When we received it (ms)


class TruthQualityV4(BaseModel):
    """Quality assessment for V4 snapshots."""
    quality_score: int                    # 0-100
    issues: List[str]                     # List of issue codes
    is_stale: bool
    freshness_ms: Optional[float] = None  # received_ts - source_ts


class TruthSourceV4(BaseModel):
    """Source metadata for V4 snapshots."""
    provider: str = "polygon"
    endpoint: str = "/v3/snapshot"
    request_id: Optional[str] = None


class TruthSnapshotV4(BaseModel):
    """
    Canonical V4 market data snapshot with quality scoring.
    Used for typed, quality-aware market data access.
    """
    symbol_canonical: str
    quote: TruthQuoteV4
    timestamps: TruthTimestampsV4
    quality: TruthQualityV4
    source: TruthSourceV4
    # Optional fields
    iv: Optional[float] = None
    greeks: Optional[dict] = None
    open_interest: Optional[int] = None
    volume: Optional[int] = None
    day: Optional[dict] = None


# =============================================================================
# V4 Quality Scoring Functions
# =============================================================================
def compute_quote_quality(
    quote: TruthQuoteV4,
    freshness_ms: Optional[float],
    max_freshness_ms: Optional[int] = None,
    wide_spread_pct: Optional[float] = None
) -> TruthQualityV4:
    """
    Deterministic rule-based quality scoring for market quotes.

    Returns quality_score (0-100), issues list, and is_stale flag.

    Scoring rules:
    - Crossed market (ask < bid): score=0, issue="crossed_market"
    - Missing bid/ask: score-=40, issue="missing_quote_fields"
    - Wide spread (> threshold): score-=20, issue="wide_spread"
    - Stale timestamp: score-=30, issue="stale_quote"
    - Missing timestamp: is_stale=True, issue="missing_timestamp"

    Args:
        quote: The quote to score
        freshness_ms: Quote freshness in milliseconds (None if unknown)
        max_freshness_ms: Max freshness threshold (uses env getter if None)
        wide_spread_pct: Wide spread threshold (uses env getter if None)
    """
    # Use getters for env-safe defaults (read at call time, not import time)
    if max_freshness_ms is None:
        max_freshness_ms = get_marketdata_max_freshness_ms()
    if wide_spread_pct is None:
        wide_spread_pct = get_marketdata_wide_spread_pct()

    score = 100
    issues: List[str] = []

    # Check 1: Crossed market (ask < bid) - fatal quality issue
    if quote.bid is not None and quote.ask is not None:
        if quote.ask < quote.bid:
            score = 0
            issues.append("crossed_market")

    # Check 2: Missing bid/ask
    if quote.bid is None or quote.ask is None:
        score -= 40
        issues.append("missing_quote_fields")

    # Check 3: Wide spread (only if we have valid values)
    # Use explicit None checks to handle 0.0 values correctly
    if (quote.mid is not None and quote.bid is not None and
            quote.ask is not None and quote.mid > 0):
        spread_pct = (quote.ask - quote.bid) / quote.mid
        if spread_pct > wide_spread_pct:
            score -= 20
            issues.append("wide_spread")

    # Check 4: Staleness
    is_stale = False
    if freshness_ms is None:
        issues.append("missing_timestamp")
        is_stale = True  # Conservative: treat missing timestamp as stale
    elif freshness_ms > max_freshness_ms:
        is_stale = True
        issues.append("stale_quote")
        score -= 30

    # Clamp score to valid range
    score = max(0, min(100, score))

    return TruthQualityV4(
        quality_score=score,
        issues=issues,
        is_stale=is_stale,
        freshness_ms=freshness_ms
    )


def check_snapshots_executable(
    snapshots: Dict[str, TruthSnapshotV4],
    required_symbols: List[str],
    min_quality_score: Optional[int] = None
) -> Tuple[bool, List[str]]:
    """
    Checks if all required symbols have executable-quality snapshots.

    Handles symbol normalization automatically - tries both raw and canonical
    key lookups to prevent false "missing_snapshot" errors.

    Returns:
        (is_executable, list_of_issues)

    A snapshot is NOT executable if:
    - Missing from the snapshots dict (after trying normalized lookup)
    - is_stale is True
    - quality_score < min_quality_score
    """
    # Use getter for env-safe default (read at call time, not import time)
    if min_quality_score is None:
        min_quality_score = get_marketdata_min_quality_score()

    issues: List[str] = []

    for raw_sym in required_symbols:
        # Try both raw and normalized key lookups to handle mismatches
        snap = snapshots.get(raw_sym)
        canonical_sym = raw_sym

        if snap is None:
            # Try normalized/canonical lookup
            try:
                canonical_sym = normalize_symbol(raw_sym)
                snap = snapshots.get(canonical_sym)
            except Exception:
                # If normalization fails, treat symbol as-is
                pass

        if snap is None:
            # Include both raw and canonical in error for debugging
            if canonical_sym != raw_sym:
                issues.append(f"{raw_sym} (canon={canonical_sym}): missing_snapshot")
            else:
                issues.append(f"{raw_sym}: missing_snapshot")
            continue

        if snap.quality.is_stale:
            issues.append(f"{raw_sym}: stale_quote (freshness={snap.quality.freshness_ms}ms)")

        if snap.quality.quality_score < min_quality_score:
            issues.append(
                f"{raw_sym}: low_quality (score={snap.quality.quality_score}, "
                f"issues={snap.quality.issues})"
            )

    return (len(issues) == 0, issues)


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

        # Initialize Session with Connection Pooling
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        # Mount adapter with increased pool size for parallel execution
        # pool_maxsize=50 supports up to 50 concurrent threads without blocking on connection pool
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=50,
            max_retries=retry_strategy
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

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

        # Use session for connection pooling
        try:
            start_ts = time.time()
            response = self.session.get(url, params=params, timeout=5)
            elapsed_ms = (time.time() - start_ts) * 1000

            if response.status_code == 200:
                logger.info(f"OK {endpoint} {response.status_code} {elapsed_ms:.1f}ms")
                return response.json()
            elif response.status_code == 429:
                # Retry logic handled by adapter, but if we are here it failed retries or manual handling needed?
                # Actually Adapter handles retries on status codes. If we get 429 here, it means retries exhausted.
                logger.warning(f"Rate limited on {endpoint} (Retries exhausted).")
                return None
            else:
                logger.error(f"Error {endpoint}: {response.status_code} {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed {endpoint}: {e}")
            return None

    # ... rest of the class methods ...
    def snapshot_many(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetches snapshots for multiple tickers (up to 250).
        Returns a dict keyed by ticker.
        """
        if not tickers:
            return {}

        # 1. Normalize tickers and filter valid ones
        # Use centralized normalization (Sentinel: Input Sanitization)
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

        # Bolt Optimization: Parallelize batch fetching
        # If we have multiple chunks, fetch them concurrently
        # 4 chunks of 50 = 200 tickers
        # Sequential: ~2.0s
        # Parallel: ~0.5s

        def fetch_chunk(chunk):
            tickers_str = ",".join(chunk)
            return self._make_request("/v3/snapshot", params={"ticker.any_of": tickers_str})

        chunks = [missing_tickers[i:i + chunk_size] for i in range(0, len(missing_tickers), chunk_size)]

        # Use max_workers=10 to allow sufficient concurrency without overwhelming the API rate limits (if any)
        # Connection pool is sized at 50, so this is safe.
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_chunk = {executor.submit(fetch_chunk, chunk): chunk for chunk in chunks}

            for future in concurrent.futures.as_completed(future_to_chunk):
                try:
                    data = future.result()
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
                        chunk = future_to_chunk[future]
                        logger.warning(f"No results for snapshot batch: {chunk}")
                except Exception as e:
                    logger.error(f"Error fetching snapshot chunk: {e}")

        return results

    def snapshot_many_v4(
        self,
        tickers: List[str],
        raw_snapshots: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, TruthSnapshotV4]:
        """
        V4 API: Returns canonical TruthSnapshotV4 objects with quality scoring.

        This is the preferred method for quality-aware market data access.
        Backward compatible: existing snapshot_many() unchanged.

        Args:
            tickers: List of ticker symbols to fetch
            raw_snapshots: Optional pre-fetched raw snapshots to avoid double fetch.
                           If provided, snapshot_many() will NOT be called.

        Returns:
            Dict mapping ticker to TruthSnapshotV4 with quality scoring
        """
        # Use provided raw_snapshots or fetch them
        if raw_snapshots is None:
            raw_snapshots = self.snapshot_many(tickers)

        v4_results: Dict[str, TruthSnapshotV4] = {}
        received_ts = int(time.time() * 1000)

        for ticker, raw in raw_snapshots.items():
            quote_data = raw.get("quote", {})

            # Build TruthQuoteV4
            quote = TruthQuoteV4(
                bid=quote_data.get("bid"),
                ask=quote_data.get("ask"),
                mid=quote_data.get("mid"),
                last=quote_data.get("last"),
                bid_size=quote_data.get("bid_size"),
                ask_size=quote_data.get("ask_size"),
            )

            # Compute mid if missing but bid/ask present
            if quote.mid is None and quote.bid is not None and quote.ask is not None:
                quote = quote.model_copy(update={"mid": (quote.bid + quote.ask) / 2.0})

            # Build timestamps
            source_ts = raw.get("provider_ts")
            if source_ts:
                source_ts = self._normalize_timestamp_to_ms(source_ts)

            timestamps = TruthTimestampsV4(
                source_ts=source_ts,
                received_ts=received_ts
            )

            # Compute freshness from raw staleness_ms or calculate from timestamps
            freshness_ms = raw.get("staleness_ms")
            if freshness_ms is None and source_ts:
                freshness_ms = float(received_ts - source_ts)

            # Compute quality
            quality = compute_quote_quality(quote, freshness_ms)

            # Build source metadata
            source = TruthSourceV4(provider="polygon", endpoint="/v3/snapshot")

            v4_results[ticker] = TruthSnapshotV4(
                symbol_canonical=ticker,
                quote=quote,
                timestamps=timestamps,
                quality=quality,
                source=source,
                iv=raw.get("iv"),
                greeks=raw.get("greeks"),
                day=raw.get("day"),
                volume=raw.get("day", {}).get("v"),
            )

        return v4_results

    def _normalize_timestamp_to_ms(self, ts: Optional[Union[int, float]]) -> Optional[int]:
        """
        Normalize timestamp to milliseconds.

        Handles timestamps in nanoseconds, microseconds, milliseconds, or seconds.
        """
        if ts is None:
            return None
        try:
            ts_val = float(ts)
            if ts_val > 1e16:  # Nanoseconds (> 10^16)
                return int(ts_val / 1e6)
            elif ts_val > 1e14:  # Microseconds (> 10^14)
                return int(ts_val / 1e3)
            elif ts_val > 1e11:  # Already milliseconds (> 10^11)
                return int(ts_val)
            else:  # Seconds
                return int(ts_val * 1000)
        except (ValueError, TypeError):
            return None

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
        Delegates to centralized cache_key_builder for consistent sanitization.
        """
        return normalize_symbol(symbol)

    # Backward compat
    _normalize_symbol = normalize_symbol
