"""Market data integration with caching"""
import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import re
from packages.quantum.cache import get_cached_data, save_to_cache
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank

def normalize_option_symbol(symbol: str) -> str:
    """Ensures option symbols have the 'O:' prefix required by Polygon."""
    if len(symbol) > 5 and not symbol.startswith('O:'):
        return f"O:{symbol}"
    return symbol

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
    
    def get_historical_prices(self, symbol: str, days: int = 252, to_date: datetime = None) -> Dict:
        to_date = to_date or datetime.now()
        from_date = to_date - timedelta(days=days + 30)
        
        from_str = from_date.strftime('%Y-%m-%d')
        to_str = to_date.strftime('%Y-%m-%d')
        
        # Handle Options formatting
        search_symbol = normalize_option_symbol(symbol)

        url = f"{self.base_url}/v2/aggs/ticker/{search_symbol}/range/1/day/{from_str}/{to_str}"
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'apiKey': self.api_key
        }
        
        # Reduced timeout to 5s to prevent hanging
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        if 'results' not in data or len(data['results']) == 0:
            raise ValueError(f"No data returned for {symbol}")
        
        prices = [bar['c'] for bar in data['results']]
        volumes = [bar.get('v', 0) for bar in data['results']]
        dates = [datetime.fromtimestamp(bar['t'] / 1000).strftime('%Y-%m-%d') 
                for bar in data['results']]
        
        returns = []
        for i in range(1, len(prices)):
            returns.append((prices[i] - prices[i-1]) / prices[i-1])
        
        return {
            'symbol': symbol,
            'prices': prices,
            'volumes': volumes,
            'returns': returns,
            'dates': dates
        }

    def get_ticker_details(self, symbol: str) -> Dict:
        """Fetches details for a given ticker, including sector."""

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
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('results', {})

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
        Returns a dict with 'bid' and 'ask' for the given symbol.
        Uses Polygon's quotes endpoint.
        Returns {'bid': 0.0, 'ask': 0.0} on failure.
        """
        # 1. Normalize Symbol
        search_symbol = normalize_option_symbol(symbol)
        is_option = search_symbol.startswith('O:')

        try:
            if is_option:
                # Options: Use v3 Quotes (latest)
                # We fetch the most recent quote
                url = f"{self.base_url}/v3/quotes/{search_symbol}"
                params = {
                    'limit': 1,
                    'order': 'desc',
                    'sort': 'timestamp',
                    'apiKey': self.api_key
                }
                response = requests.get(url, params=params, timeout=5)
                # Use raise_for_status to catch 4xx/5xx errors
                if response.status_code != 200:
                     return {"bid": 0.0, "ask": 0.0}

                data = response.json()

                if 'results' in data and len(data['results']) > 0:
                    quote = data['results'][0]
                    return {
                        "bid": float(quote.get('bid_price', 0.0)),
                        "ask": float(quote.get('ask_price', 0.0))
                    }
            else:
                # Stocks: Use v2 NBBO (Last Quote)
                url = f"{self.base_url}/v2/last/nbbo/{search_symbol}"
                params = {'apiKey': self.api_key}
                response = requests.get(url, params=params, timeout=5)

                # NBBO endpoint might return 404 if no data, or 200 with empty results
                if response.status_code != 200:
                    return {"bid": 0.0, "ask": 0.0}

                data = response.json()

                if 'results' in data:
                    res = data['results']
                    # Polygon v2/last/nbbo: p = bid price, P = ask price
                    return {
                        "bid": float(res.get('p', 0.0)),
                        "ask": float(res.get('P', 0.0))
                    }

        except Exception as e:
            # Fallback for any network/parsing errors
            print(f"Quote fetch failed for {search_symbol}: {e}")

        return {"bid": 0.0, "ask": 0.0}

    def get_option_snapshot(self, symbol: str) -> Dict:
        """
        Fetches snapshot data (price, greeks, iv) for a single option contract.
        Endpoint: /v3/snapshot/options/{underlyingAsset}/{optionContract}
        """
        search_symbol = normalize_option_symbol(symbol)
        underlying = extract_underlying_symbol(symbol)

        # Construct URL
        # Note: underlying is required in path
        url = f"{self.base_url}/v3/snapshot/options/{underlying}/{search_symbol}"

        params = {'apiKey': self.api_key}

        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code != 200:
                print(f"Snapshot fetch failed: {response.status_code} {response.text}")
                return {}

            data = response.json()
            if 'results' in data:
                # API returns a single object in 'results' for this endpoint?
                # Or a list? Usually list if bulk, but specific path might return object.
                # Let's handle both.
                res = data['results']
                if isinstance(res, list):
                    return res[0] if res else {}
                return res

        except Exception as e:
            print(f"Error fetching option snapshot for {symbol}: {e}")

        return {}

    def get_option_chain_snapshot(self, underlying: str, strike_range: float = 0.20) -> List[Dict]:
        """
        Fetches option chain snapshot for the underlying.
        Endpoint: /v3/snapshot/options/{underlyingAsset}
        Filters:
        - 20-45 DTE initially to optimize for 30d interpolation (can widen if needed)
        - Strike range ±20% around spot (requires spot price first)

        If strike_range is None, fetches full chain (careful with pagination).
        """
        # 1. Get spot price first to filter strikes
        try:
            quote = self.get_recent_quote(underlying)
            spot = (quote['bid'] + quote['ask']) / 2.0
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

        # If still no spot, we can't filter by strike effectively. Use wider net or fail?
        # Let's proceed with no strike filter if spot is missing, but strict limit.

        url = f"{self.base_url}/v3/snapshot/options/{underlying}"

        params = {
            'apiKey': self.api_key,
            'limit': 250
        }

        # Add filters for efficiency
        # Expiry: >= 15 days, <= 60 days (to bracket 30 days)
        # Polygon filtering syntax: expiration_date.gte, etc.

        today = datetime.now().date()
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

        try:
            while url:
                response = requests.get(url, params=params, timeout=10)
                if response.status_code != 200:
                    print(f"Chain snapshot fetch failed for {underlying}: {response.status_code}")
                    break

                data = response.json()
                batch = data.get('results', [])
                results.extend(batch)

                # Check for pagination
                # Polygon uses 'next_url' in response, which includes params (but not apiKey usually?)
                # Actually v3 snapshot often includes cursor in next_url
                next_url = data.get('next_url')
                if next_url:
                    url = next_url
                    # next_url usually has params embedded. reset params to avoid duplication/conflict
                    # but we MUST ensure apiKey is attached if it's not in next_url
                    params = {'apiKey': self.api_key}
                else:
                    break

                # Safety break for massive chains
                if len(results) > 1000:
                    break

            return results

        except Exception as e:
            print(f"Error fetching chain snapshot for {underlying}: {e}")
            return []

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

        response = requests.get(url, params=params, timeout=5)

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
    cache_key = (symbols_tuple, method)
    
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

        all_data = []
        for symbol in symbols:
            try:
                data = service.get_historical_prices(symbol)
                all_data.append(data)
                print(f"  ✓ {symbol}: {len(data['prices'])} days")
            except Exception as e:
                print(f"  ✗ {symbol}: {str(e)}")
                raise

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
