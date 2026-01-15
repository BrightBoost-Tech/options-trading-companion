"""Market data integration with caching"""
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
import numpy as np
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from packages.quantum.cache import get_cached_data, save_to_cache
# We keep the old import for backward compatibility if any external module uses it,
# but we are moving to the new service internally.
from packages.quantum.market_data_cache import get_cached_market_data, cache_market_data
from packages.quantum.services.market_data_cache import get_market_data_cache, TTL_QUOTES, TTL_SNAPSHOTS, TTL_OHLC
from packages.quantum.services.cache_key_builder import make_cache_key_parts, normalize_symbol as normalize_option_symbol
from packages.quantum.services.provider_guardrails import guardrail
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank

def extract_underlying_symbol(symbol: str) -> str:
    """
    Extracts the underlying equity ticker from an option symbol.
    Handles 'O:' prefix and standard/compact option formats.
    Example: O:AMZN230616C00125000 -> AMZN
    """
    # Remove Polygon prefix
    clean = symbol.replace("O:", "")

    # Extract ticker (letters, dots, hyphens before the first digit)
    match = re.match(r"^([A-Z\.-]+)\d", clean)
    if match:
        return match.group(1)

    return clean

class PolygonService:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            print("Warning: POLYGON_API_KEY not found. Service will use mock data.")
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
    
    def get_historical_prices(self, symbol: str, days: int = 252, to_date: datetime = None) -> Optional[Dict]:
        to_date = to_date or datetime.now()
        
        # Handle weekend roll to previous Friday
        if to_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            days_to_subtract = to_date.weekday() - 4  # Sat(5)->1, Sun(6)->2
            to_date = to_date - timedelta(days=days_to_subtract)

        # Normalize symbol first to ensure cache consistency
        # e.g. "AMZN23..." -> "O:AMZN23..."
        symbol = normalize_option_symbol(symbol)

        # 1. Check New Unified Cache
        to_date_str = to_date.strftime('%Y-%m-%d')
        # Use simple key parts: symbol, days, date
        cache_key_parts = make_cache_key_parts("OHLC", symbol=symbol, days=days, to_date_str=to_date_str)
        cached = self.cache.get("OHLC", cache_key_parts)
        if cached:
            return cached

        # Fallback to old cache (read-only migration path)
        old_cached = get_cached_market_data(symbol, days, to_date_str)
        if old_cached:
            # Migrate to new cache
            self.cache.set("OHLC", cache_key_parts, old_cached, ttl_seconds=TTL_OHLC)
            return old_cached

        # In-Flight Lock: Prevent cache stampede if multiple threads request same OHLC
        # (e.g., during scanner runs)
        with self.cache.inflight_lock("OHLC", cache_key_parts):
            # Double-check cache inside lock
            cached = self.cache.get("OHLC", cache_key_parts)
            if cached:
                return cached

            # Call Guarded Private Method
            result = self._get_historical_prices_api(symbol, days, to_date, to_date_str)

            if result:
                 # 3. Cache Success
                self.cache.set("OHLC", cache_key_parts, result, ttl_seconds=TTL_OHLC)
                return result

            return None

    def get_option_historical_prices(
        self,
        option_symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict]:
        """
        Fetches daily OHLC data for a specific option contract.

        Args:
            option_symbol: OCC option symbol (e.g., "O:AAPL240119C00150000" or "AAPL240119C00150000")
            start_date: Start date for historical data
            end_date: End date for historical data

        Returns:
            Dict with keys: dates, prices (close), opens, highs, lows, volumes
            Returns None if no data available (common for options with limited history)

        Note:
            Options typically have limited trading history compared to stocks.
            This method returns None gracefully if no data exists.
        """
        # Normalize symbol to ensure O: prefix
        symbol = normalize_option_symbol(option_symbol)

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        # Cache key
        cache_key_parts = make_cache_key_parts(
            "OPTION_OHLC",
            symbol=symbol,
            start_date=start_str,
            end_date=end_str
        )
        cached = self.cache.get("OPTION_OHLC", cache_key_parts)
        if cached:
            return cached

        with self.cache.inflight_lock("OPTION_OHLC", cache_key_parts):
            cached = self.cache.get("OPTION_OHLC", cache_key_parts)
            if cached:
                return cached

            result = self._get_option_historical_prices_api(symbol, start_str, end_str)

            if result:
                self.cache.set("OPTION_OHLC", cache_key_parts, result, ttl_seconds=TTL_OHLC)

            return result

    @guardrail(provider="polygon", fallback=None)
    def _get_option_historical_prices_api(
        self,
        symbol: str,
        start_str: str,
        end_str: str
    ) -> Optional[Dict]:
        """Internal API call for option historical prices."""
        if not self.api_key:
            return None

        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/{start_str}/{end_str}"
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'apiKey': self.api_key
        }

        response = self.session.get(url, params=params, timeout=5)

        if response.status_code != 200:
            return None

        data = response.json()
        if 'results' not in data or len(data['results']) == 0:
            return None

        bars = data['results']
        result = {
            'symbol': symbol,
            'dates': [datetime.fromtimestamp(bar['t'] / 1000).strftime('%Y-%m-%d') for bar in bars],
            'opens': [bar.get('o', 0) for bar in bars],
            'highs': [bar.get('h', 0) for bar in bars],
            'lows': [bar.get('l', 0) for bar in bars],
            'prices': [bar['c'] for bar in bars],  # Close prices
            'volumes': [bar.get('v', 0) for bar in bars]
        }
        return result

    @guardrail(provider="polygon", fallback=None)
    def _get_historical_prices_api(self, symbol: str, days: int, to_date: datetime, to_date_str: str) -> Optional[Dict]:
        # 2. Guardrails: Check API Key
        if not self.api_key:
            return None

        from_date = to_date - timedelta(days=days + 30)
        from_str = from_date.strftime('%Y-%m-%d')
        to_str = to_date_str
        
        search_symbol = symbol

        url = f"{self.base_url}/v2/aggs/ticker/{search_symbol}/range/1/day/{from_str}/{to_str}"
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'apiKey': self.api_key
        }
        
        response = self.session.get(url, params=params, timeout=5)
        response.raise_for_status()

        data = response.json()
        if 'results' not in data or len(data['results']) == 0:
            return None

        prices = [bar['c'] for bar in data['results']]
        volumes = [bar.get('v', 0) for bar in data['results']]
        dates = [datetime.fromtimestamp(bar['t'] / 1000).strftime('%Y-%m-%d')
                for bar in data['results']]

        returns = []
        for i in range(1, len(prices)):
            returns.append((prices[i] - prices[i-1]) / prices[i-1])

        result = {
            'symbol': symbol,
            'prices': prices,
            'volumes': volumes,
            'returns': returns,
            'dates': dates
        }
        return result

    def get_ticker_details(self, symbol: str) -> Dict:
        """Fetches details for a given ticker, including sector."""

        # Check cache
        cache_key_parts = make_cache_key_parts("DETAILS", symbol=symbol)
        cached = self.cache.get("DETAILS", cache_key_parts)
        if cached:
            return cached

        with self.cache.inflight_lock("DETAILS", cache_key_parts):
             # Double-check
            cached = self.cache.get("DETAILS", cache_key_parts)
            if cached: return cached

            result = self._get_ticker_details_api(symbol)

            if result:
                self.cache.set("DETAILS", cache_key_parts, result, ttl_seconds=86400 * 7) # 1 week TTL for static details

            return result

    @guardrail(provider="polygon", fallback={})
    def _get_ticker_details_api(self, symbol: str) -> Dict:
        # Check if it is an option (heuristic: length > 5 chars or starts with O:)
        is_option = len(symbol) > 5 or symbol.startswith('O:')

        if is_option:
            search_symbol = normalize_option_symbol(symbol)
            # Options Contract Endpoint
            url = f"{self.base_url}/v3/reference/options/contracts/{search_symbol}"
        else:
            # Stock Ticker Endpoint
            url = f"{self.base_url}/v3/reference/tickers/{symbol}"

        params = {'apiKey': self.api_key}
        response = self.session.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('results', {})

    def get_last_financials_date(self, symbol: str) -> Optional[datetime]:
        """
        Fetches the date of the most recent financial filing (usually earnings).
        Uses Polygon /vX/reference/financials.
        """
        # Cache key: EARNINGS:{symbol}:{today_date}
        today_str = datetime.now().strftime('%Y-%m-%d')
        key_parts = make_cache_key_parts("EARNINGS", symbol=symbol, today_str=today_str)

        cached = self.cache.get("EARNINGS", key_parts)
        if cached:
            return datetime.fromisoformat(cached)

        with self.cache.inflight_lock("EARNINGS", key_parts):
            cached = self.cache.get("EARNINGS", key_parts)
            if cached: return datetime.fromisoformat(cached)

            filing_date_str = self._get_last_financials_date_api(symbol)

            if filing_date_str:
                self.cache.set("EARNINGS", key_parts, filing_date_str, ttl_seconds=86400)
                return datetime.fromisoformat(filing_date_str)

        return None

    @guardrail(provider="polygon", fallback=None)
    def _get_last_financials_date_api(self, symbol: str) -> Optional[str]:
        url = f"{self.base_url}/vX/reference/financials"
        params = {
            'ticker': symbol,
            'limit': 1,
            'sort': 'filing_date',
            'order': 'desc',
            'apiKey': self.api_key
        }
        response = self.session.get(url, params=params, timeout=3)
        if response.status_code != 200:
            return None

        data = response.json()
        results = data.get('results', [])
        if not results:
            return None

        # Use filing_date or period_of_report_date
        filing_date_str = results[0].get('filing_date')
        return filing_date_str

    def get_iv_rank(self, symbol: str) -> float:
        """Calculates IV Rank from historical data."""
        try:
            # Use underlying equity data for IV Rank
            underlying = extract_underlying_symbol(symbol)
            data = self.get_historical_prices(underlying, days=365)

            if not data or 'returns' not in data:
                return None

            return calculate_iv_rank(data['returns'])

        except Exception:
            return None

    def get_trend(self, symbol: str) -> str:
        """Determines trend using simple moving averages."""
        try:
            data = self.get_historical_prices(symbol, days=100)
            return calculate_trend(data['prices'])
        except Exception:
            return "NEUTRAL"

    def get_recent_quote(self, symbol: str) -> Dict[str, float]:
        """
        Returns a dict with quotes for the given symbol.
        Keys: 'bid', 'ask', 'bid_price', 'ask_price', 'price'
        Uses Polygon's quotes endpoint.
        """
        # Cache check (short TTL)
        cache_key_parts = make_cache_key_parts("QUOTE", symbol=symbol)
        cached = self.cache.get("QUOTE", cache_key_parts)
        if cached:
            return cached

        result = self._get_recent_quote_api(symbol)

        if result.get("price") is not None or result.get("bid") > 0:
             self.cache.set("QUOTE", cache_key_parts, result, ttl_seconds=TTL_QUOTES)

        return result

    @guardrail(provider="polygon", fallback={"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None})
    def _get_recent_quote_api(self, symbol: str) -> Dict[str, float]:
        # 1. Normalize Symbol
        search_symbol = normalize_option_symbol(symbol)
        is_option = search_symbol.startswith('O:')

        if is_option:
            # Options: Use v3 Quotes (latest)
            url = f"{self.base_url}/v3/quotes/{search_symbol}"
            params = {
                'limit': 1,
                'order': 'desc',
                'sort': 'timestamp',
                'apiKey': self.api_key
            }
            response = self.session.get(url, params=params, timeout=5)
            # Use raise_for_status to catch 4xx/5xx errors
            if response.status_code != 200:
                    return {"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None}

            data = response.json()

            if 'results' in data and len(data['results']) > 0:
                quote = data['results'][0]
                bid = float(quote.get('bid_price', 0.0))
                ask = float(quote.get('ask_price', 0.0))
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else None
                return {
                    "bid": bid,
                    "ask": ask,
                    "bid_price": bid,
                    "ask_price": ask,
                    "price": mid
                }
        else:
            # Stocks: Use v2 NBBO (Last Quote)
            url = f"{self.base_url}/v2/last/nbbo/{search_symbol}"
            params = {'apiKey': self.api_key}
            response = self.session.get(url, params=params, timeout=5)

            # NBBO endpoint might return 404 if no data, or 200 with empty results
            if response.status_code != 200:
                return {"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None}

            data = response.json()

            if 'results' in data:
                res = data['results']
                # Polygon v2/last/nbbo: p = bid price, P = ask price
                bid = float(res.get('p', 0.0))
                ask = float(res.get('P', 0.0))
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else None
                return {
                    "bid": bid,
                    "ask": ask,
                    "bid_price": bid,
                    "ask_price": ask,
                    "price": mid
                }

        return {"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None}

    def get_option_snapshot(self, symbol: str) -> Dict:
        """
        Fetches snapshot data (price, greeks, iv) for a single option contract.
        Endpoint: /v3/snapshot/options/{underlyingAsset}/{optionContract}
        """
        # Cache check
        cache_key_parts = make_cache_key_parts("SNAPSHOT", symbol=symbol)
        cached = self.cache.get("SNAPSHOT", cache_key_parts)
        if cached:
            return cached

        result = self._get_option_snapshot_api(symbol)

        if result:
            self.cache.set("SNAPSHOT", cache_key_parts, result, ttl_seconds=TTL_SNAPSHOTS)

        return result

    @guardrail(provider="polygon", fallback={})
    def _get_option_snapshot_api(self, symbol: str) -> Dict:
        search_symbol = normalize_option_symbol(symbol)
        underlying = extract_underlying_symbol(symbol)

        # Construct URL
        # Note: underlying is required in path
        url = f"{self.base_url}/v3/snapshot/options/{underlying}/{search_symbol}"

        params = {'apiKey': self.api_key}

        response = self.session.get(url, params=params, timeout=5)
        if response.status_code != 200:
            print(f"Snapshot fetch failed: {response.status_code} {response.text}")
            return {}

        data = response.json()
        if 'results' in data:
            res = data['results']
            if isinstance(res, list):
                result = res[0] if res else {}
            else:
                result = res
            return result
        return {}

    def get_option_chain_snapshot(self, underlying: str, strike_range: float = 0.20, limit: int = 1000) -> List[Dict]:
        """
        Fetches option chain snapshot for the underlying.
        Endpoint: /v3/snapshot/options/{underlyingAsset}
        Filters:
        - 20-45 DTE initially to optimize for 30d interpolation (can widen if needed)
        - Strike range ±20% around spot (requires spot price first)

        If strike_range is None, fetches full chain (careful with pagination).
        """
        # Cache key needs to include params
        # Note: we stringify params. Order is preserved in list.
        now_str = datetime.now().strftime('%Y-%m-%d-%H')
        cache_key = make_cache_key_parts("CHAIN", underlying=underlying, strike_range=strike_range, limit=limit, date_str=now_str)
        cached = self.cache.get("CHAIN", cache_key)
        if cached:
            return cached

        with self.cache.inflight_lock("CHAIN", cache_key):
            cached = self.cache.get("CHAIN", cache_key)
            if cached: return cached

            result = self._get_option_chain_snapshot_api(underlying, strike_range, limit)

            if result:
                self.cache.set("CHAIN", cache_key, result, ttl_seconds=TTL_SNAPSHOTS)

            return result

    @guardrail(provider="polygon", fallback=[])
    def _get_option_chain_snapshot_api(self, underlying: str, strike_range: float, limit: int) -> List[Dict]:
        # 1. Get spot price first to filter strikes
        try:
            quote = self.get_recent_quote(underlying)
            spot = quote.get("price") or (quote['bid'] + quote['ask']) / 2.0
        except:
            spot = 0

        if spot <= 0:
            # Try getting price from get_historical_prices (previous close)
            try:
                hist = self.get_historical_prices(underlying, days=2)
                if hist and hist.get('prices'):
                    spot = hist['prices'][-1]
            except:
                pass

        url = f"{self.base_url}/v3/snapshot/options/{underlying}"

        params = {
            'apiKey': self.api_key,
            'limit': 250
        }

        today = datetime.now(timezone.utc).date()
        date_min = (today + timedelta(days=15)).strftime('%Y-%m-%d')
        date_max = (today + timedelta(days=60)).strftime('%Y-%m-%d')

        params['expiration_date.gte'] = date_min
        params['expiration_date.lte'] = date_max

        if spot > 0:
            strike_min = spot * (1 - strike_range)
            strike_max = spot * (1 + strike_range)
            params['strike_price.gte'] = strike_min
            params['strike_price.lte'] = strike_max

        results = []

        while url:
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code != 200:
                print(f"Chain snapshot fetch failed for {underlying}: {response.status_code}")
                break

            data = response.json()
            batch = data.get('results', [])
            results.extend(batch)

            next_url = data.get('next_url')
            if next_url:
                url = next_url
                params = {'apiKey': self.api_key}
            else:
                break

            if len(results) > limit:
                break

        return results

    def get_option_chain(self, symbol: str, min_dte: int = 25, max_dte: int = 45, limit: int = 1000) -> List[Dict[str, Any]]:
        """
        High-level wrapper to fetch and normalize option chain for scanner.
        """
        raw_chain = self.get_option_chain_snapshot(symbol, limit=limit)
        normalized = []
        today = datetime.now(timezone.utc).date()

        for item in raw_chain:
            details = item.get("details") or {}
            exp_str = details.get("expiration_date")
            strike = details.get("strike_price")
            right = (details.get("contract_type") or "").lower() # "call"/"put"
            ticker = details.get("ticker") or item.get("ticker")

            if not (ticker and exp_str and strike and right):
                continue

            try:
                # Bolt Optimization: Use fromisoformat (30x faster) with fallback
                try:
                    exp_date = datetime.fromisoformat(exp_str).date()
                except ValueError:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()

                dte = (exp_date - today).days
                if not (min_dte <= dte <= max_dte):
                    continue
            except ValueError:
                continue

            greeks = item.get("greeks") or {}
            last_quote = item.get("last_quote") or {}

            # Extract prices
            bid = float(last_quote.get("b") or 0.0)
            ask = float(last_quote.get("a") or 0.0)

            mid = None
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0

            day = item.get("day") or {}
            close = float(day.get("close") or 0.0)

            # Best effort price
            price = mid if mid else (float(item.get("last_trade", {}).get("p") or 0.0) or close)

            normalized.append({
                "ticker": ticker,
                "strike": strike,
                "expiration": exp_str,
                "type": right,
                "delta": float(greeks.get("delta") or 0.0),
                "gamma": float(greeks.get("gamma") or 0.0),
                "vega": float(greeks.get("vega") or 0.0),
                "theta": float(greeks.get("theta") or 0.0),
                "bid": bid,
                "ask": ask,
                "price": price,
                "close": close
            })

        return normalized

def get_polygon_price(symbol: str) -> float:
    # FIX 1: Handle Cash Manually
    if symbol == 'CUR:USD':
        return 1.0

    # FIX 2: Format Options for Polygon (Prepend 'O:')
    # Plaid sends "AMZN251219...", Polygon needs "O:AMZN251219..."
    search_symbol = normalize_option_symbol(symbol)

    try:
        # Use existing service to reuse API key logic
        service = PolygonService()
        if not service.api_key:
             return 0.0

        # We use get_previous_close_agg for fast latest price
        # URL: /v2/aggs/ticker/{stocksTicker}/prev
        url = f"{service.base_url}/v2/aggs/ticker/{search_symbol}/prev"
        params = {
            'adjusted': 'true',
            'apiKey': service.api_key
        }

        response = service.session.get(url, params=params, timeout=5)

        if response.status_code == 200:
             data = response.json()
             if data.get('resultsCount', 0) > 0 and data.get('results'):
                 return float(data['results'][0]['c'])

        return 0.0
    except Exception as e:
        print(f"⚠️ Error fetching {search_symbol}: {e}")
        return 0.0 # Fallback

def _nearest_psd(A):
    """Find the nearest positive-semi-definite matrix to input A."""
    B = (A + A.T) / 2
    _, s, V = np.linalg.svd(B)
    H = np.dot(V.T, np.dot(np.diag(s), V))
    A2 = (B + H) / 2
    A3 = (A2 + A2.T) / 2
    if _is_psd(A3):
        return A3
    spacing = np.spacing(np.linalg.norm(A))
    I = np.eye(A.shape[0])
    k = 1
    while not _is_psd(A3):
        mineig = np.min(np.real(np.linalg.eigvals(A3)))
        A3 += I * (-mineig * k**2 + spacing)
        k += 1
    return A3

def _is_psd(A):
    """Check if matrix is positive semi-definite."""
    try:
        # Check eigenvalues
        return np.all(np.linalg.eigvals(A) >= -1e-8)
    except np.linalg.LinAlgError:
        return False

def calculate_portfolio_inputs(
    symbols: List[str],
    api_key: str = None,
    method: str = "sample", # "sample", "ewma", "ledoit_wolf"
    shrinkage_tau_days: int = 0
) -> Dict:
    """
    Calculate portfolio inputs (mu, sigma) with robust estimation methods.

    Args:
        symbols: List of ticker symbols.
        api_key: Polygon API key.
        method: Estimation method for covariance ("sample", "ewma", "ledoit_wolf").
        shrinkage_tau_days: If > 0, use Bayesian shrinkage for mu to 0 with this tau strength (days of evidence).

    Returns:
        Dict with 'expected_returns', 'covariance_matrix', etc.
    """
    
    if not symbols:
        raise ValueError("No symbols provided")

    # Check cache first (incorporate method into cache key if needed, or clear cache on method change)
    # Simple cache key: symbols + method
    symbols_tuple = tuple(sorted(symbols))
    # cache_key must be compatible with get_cached_data expectation.
    # The error was '<' not supported between instances of 'str' and 'tuple' inside cache.py's sorted(symbols)
    # cache.py expects an iterable of strings.
    # So we flatten cache_key into a tuple of strings.
    cache_key = symbols_tuple + (str(method), str(shrinkage_tau_days))
    
    # We use a custom cache mechanism here or reuse get_cached_data
    # get_cached_data uses filename based on hash of arg.
    # Let's assume get_cached_data works on arbitrary pickleable objects.
    cached = get_cached_data(cache_key)
    if cached:
        return cached

    # Check for API Key
    real_api_key = api_key or os.getenv('POLYGON_API_KEY')
    if not real_api_key:
        raise ValueError("POLYGON_API_KEY not found.")

    # Fetch fresh data
    try:
        service = PolygonService(real_api_key)
        print(f"Fetching historical data for: {', '.join(symbols)}")

        all_data_map = {}
        # Use ThreadPoolExecutor for parallel I/O (network requests)
        # Max workers 20 covers most portfolio sizes without overwhelming the pool (max 50)
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_symbol = {executor.submit(service.get_historical_prices, sym): sym for sym in symbols}

            for future in as_completed(future_to_symbol):
                sym = future_to_symbol[future]
                try:
                    data = future.result()
                    all_data_map[sym] = data
                    print(f"  ✓ {sym}: {len(data['prices'])} days")
                except Exception as e:
                    print(f"  ✗ {sym}: {str(e)}")
                    # We raise immediately to fail fast, or could collect errors
                    raise e

        # Reconstruct list in alignment with input 'symbols' order
        all_data = [all_data_map[s] for s in symbols]

        # Align Data
        min_length = min(len(data['returns']) for data in all_data)
        aligned_returns = [data['returns'][-min_length:] for data in all_data]
        returns_matrix = np.array(aligned_returns) # Shape (n_assets, n_days)

        # 1. Expected Returns (mu)
        # Default: Sample Mean * 252
        means = np.mean(returns_matrix, axis=1) * 252

        # Bayesian Shrinkage (James-Stein style)
        if shrinkage_tau_days > 0:
            # Shrink towards 0.0 (or market mean, here 0.0 for risk-adjusted view)
            # Alpha = T / (T + tau)
            # Est = Alpha * SampleMean + (1 - Alpha) * Prior
            T = min_length
            alpha = T / (T + shrinkage_tau_days)
            means = alpha * means + (1 - alpha) * 0.0

        expected_returns = means.tolist()

        # 2. Covariance (Sigma)
        cov_matrix = None

        if method == "ewma":
            # Exponentially Weighted Moving Average
            # Decay factor lambda usually 0.94 or 0.97 for daily
            decay = 0.94
            # Implement EWMA covariance
            T_days = returns_matrix.shape[1]
            n_assets = returns_matrix.shape[0]

            # Remove mean? Usually EWMA assumes mean 0 or uses trailing mean.
            # Assuming mean 0 is standard for daily vol.
            centered = returns_matrix # or returns_matrix - np.mean(returns_matrix, axis=1, keepdims=True)

            weights = np.power(decay, np.arange(T_days)[::-1])
            weights /= np.sum(weights)

            # Weighted Covariance
            # cov_ij = sum(w_t * r_it * r_jt)
            # Efficient: (R * sqrt(W)) @ (R * sqrt(W)).T

            w_matrix = np.sqrt(weights)
            weighted_R = centered * w_matrix
            cov_matrix = (weighted_R @ weighted_R.T) * 252 # Annualize

        elif method == "ledoit_wolf":
             # Use sklearn if available, else simple shrinkage to diagonal
            try:
                from sklearn.covariance import LedoitWolf
                lw = LedoitWolf()
                # sklearn expects (n_samples, n_features) -> (n_days, n_assets)
                lw.fit(returns_matrix.T)
                cov_matrix = lw.covariance_ * 252
            except ImportError:
                print("sklearn not found, falling back to simple shrinkage")
                # Simple linear shrinkage: 0.5 * Sample + 0.5 * Diag
                sample_cov = np.cov(returns_matrix) * 252
                prior = np.diag(np.diag(sample_cov))
                cov_matrix = 0.5 * sample_cov + 0.5 * prior

        else: # "sample"
            cov_matrix = np.cov(returns_matrix) * 252

        # Ensure PSD
        if not _is_psd(cov_matrix):
            print("Warning: Covariance matrix not PSD, repairing...")
            cov_matrix = _nearest_psd(cov_matrix)

        result = {
            'expected_returns': expected_returns,
            'covariance_matrix': cov_matrix.tolist(),
            'symbols': symbols,
            'data_points': min_length,
            'is_mock': False
        }

        # Cache for next time
        save_to_cache(cache_key, result)

        return result

    except Exception as e:
        print(f"Error fetching real data: {e}")
        raise e


if __name__ == '__main__':
    symbols = ['SPY', 'QQQ', 'IWM', 'DIA']
    
    try:
        inputs = calculate_portfolio_inputs(symbols, method="ewma", shrinkage_tau_days=30)
        
        print("\nPortfolio Inputs:")
        print("="*50)
        print(f"Source: {'Mock Data' if inputs.get('is_mock') else 'Real Market Data'}")
        print(f"\nSymbols: {inputs['symbols']}")
        print(f"Data points: {inputs['data_points']} days")
        
        print("\nExpected Returns (annualized):")
        for symbol, ret in zip(inputs['symbols'], inputs['expected_returns']):
            print(f"  {symbol}: {ret*100:.2f}%")
        
        print("\nCovariance Matrix:")
        cov = np.array(inputs['covariance_matrix'])
        print(f"  Shape: {cov.shape}")
        print(f"  Avg volatility: {np.sqrt(np.diag(cov)).mean()*100:.2f}%")
        
    except Exception as e:
        print(f"\nError: {e}")
