"""Market data integration with caching"""
import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict
import numpy as np
from cache import get_cached_data, save_to_cache

class PolygonService:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            print("Warning: POLYGON_API_KEY not found. Service will use mock data.")
        self.base_url = "https://api.polygon.io"
    
    def get_historical_prices(self, symbol: str, days: int = 252) -> Dict:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days + 30)
        
        from_str = from_date.strftime('%Y-%m-%d')
        to_str = to_date.strftime('%Y-%m-%d')
        
        # Handle Options formatting
        search_symbol = symbol
        if len(symbol) > 5 and not symbol.startswith('O:'):
            search_symbol = f"O:{symbol}"

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
        dates = [datetime.fromtimestamp(bar['t'] / 1000).strftime('%Y-%m-%d') 
                for bar in data['results']]
        
        returns = []
        for i in range(1, len(prices)):
            returns.append((prices[i] - prices[i-1]) / prices[i-1])
        
        return {
            'symbol': symbol,
            'prices': prices,
            'returns': returns,
            'dates': dates
        }

    def get_ticker_details(self, symbol: str) -> Dict:
        """Fetches details for a given ticker, including sector."""
        url = f"{self.base_url}/v3/reference/tickers/{symbol}"
        params = {'apiKey': self.api_key}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('results', {})

    def get_iv_rank(self, symbol: str) -> float:
        """Calculates IV Rank from historical data."""
        try:
            data = self.get_historical_prices(symbol, days=365)
            returns = np.array(data['returns'])

            # Calculate 30-day rolling volatility
            rolling_vol = np.std([returns[i-30:i] for i in range(30, len(returns))], axis=1) * np.sqrt(252)

            if len(rolling_vol) == 0:
                return 50.0 # Default if not enough data

            # Get 52-week high and low of volatility
            high_52_week = np.max(rolling_vol)
            low_52_week = np.min(rolling_vol)

            # Current volatility (last 30 days)
            current_vol = rolling_vol[-1]

            # IV Rank formula
            iv_rank = ((current_vol - low_52_week) / (high_52_week - low_52_week)) * 100

            return np.clip(iv_rank, 0, 100)

        except Exception:
            return 50.0 # Default

    def get_trend(self, symbol: str) -> str:
        """Determines trend using simple moving averages."""
        try:
            data = self.get_historical_prices(symbol, days=100)
            prices = np.array(data['prices'])
            sma_20 = np.mean(prices[-20:])
            sma_50 = np.mean(prices[-50:])
            if sma_20 > sma_50:
                return "UP"
            else:
                return "DOWN"
        except Exception:
            return "NEUTRAL"

def get_polygon_price(symbol: str) -> float:
    # FIX 1: Handle Cash Manually
    if symbol == 'CUR:USD':
        return 1.0

    # FIX 2: Format Options for Polygon (Prepend 'O:')
    # Plaid sends "AMZN251219...", Polygon needs "O:AMZN251219..."
    search_symbol = symbol
    if len(symbol) > 5 and not symbol.startswith('O:'):
        search_symbol = f"O:{symbol}"

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
