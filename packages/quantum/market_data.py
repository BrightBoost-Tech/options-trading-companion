"""Market data integration with caching"""
import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict
import numpy as np
import re
from cache import get_cached_data, save_to_cache
from analytics.factors import calculate_trend, calculate_iv_rank

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

def calculate_portfolio_inputs(symbols: List[str], api_key: str = None) -> Dict:
    """Calculate with caching to avoid rate limits"""
    
    if not symbols:
        raise ValueError("No symbols provided")

    # Check cache first
    symbols_tuple = tuple(sorted(symbols))
    cached = get_cached_data(symbols_tuple)
    
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

        expected_returns = []
        for data in all_data:
            mean_daily_return = np.mean(data['returns'])
            annualized_return = mean_daily_return * 252
            expected_returns.append(float(annualized_return))

        min_length = min(len(data['returns']) for data in all_data)
        aligned_returns = [data['returns'][-min_length:] for data in all_data]

        returns_matrix = np.array(aligned_returns)
        cov_matrix = np.cov(returns_matrix) * 252

        result = {
            'expected_returns': expected_returns,
            'covariance_matrix': cov_matrix.tolist(),
            'symbols': symbols,
            'data_points': min_length,
            'is_mock': False
        }

        # Cache for next time
        save_to_cache(symbols_tuple, result)

        return result

    except Exception as e:
        print(f"Error fetching real data: {e}")
        raise e


if __name__ == '__main__':
    symbols = ['SPY', 'QQQ', 'IWM', 'DIA']
    
    try:
        inputs = calculate_portfolio_inputs(symbols)
        
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
