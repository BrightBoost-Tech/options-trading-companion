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
        
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/{from_str}/{to_str}"
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'apiKey': self.api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
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

def generate_mock_market_data(symbols: List[str]) -> Dict:
    """Generate consistent mock data for testing without API key"""
    print(f"⚠️  Using MOCK market data for {symbols} (Polygon Key missing)")
    
    n_assets = len(symbols)
    # Generate deterministic mock data based on symbol names to be consistent
    # Use a seed so that the same symbols always produce the same mock stats
    seed_val = sum(ord(c) for c in ''.join(symbols))
    rng = np.random.RandomState(seed_val)

    # Annualized returns between 5% and 25%
    expected_returns = rng.uniform(0.05, 0.25, n_assets).tolist()

    # Random covariance matrix
    A = rng.rand(n_assets, n_assets)
    # Make it symmetric positive definite: A * A.T
    # Scale volatility to be somewhat realistic
    cov_matrix = np.dot(A, A.transpose()) * 0.05

    result = {
        'expected_returns': expected_returns,
        'covariance_matrix': cov_matrix.tolist(),
        'symbols': symbols,
        'data_points': 252,
        'is_mock': True
    }
    return result

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
        return generate_mock_market_data(symbols)

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
        print("Falling back to mock data...")
        return generate_mock_market_data(symbols)


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
