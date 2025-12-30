import unittest
from unittest.mock import MagicMock, patch
import os
import shutil
from datetime import datetime
from packages.quantum.market_data_cache import get_cached_market_data, cache_market_data, CACHE_DIR
from packages.quantum.market_data import PolygonService

class TestRealizedVolPolygonCache(unittest.TestCase):
    def setUp(self):
        # Clean cache dir
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR)

    def tearDown(self):
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)

    def test_cache_round_trip(self):
        symbol = "SPY"
        days = 10
        to_date = "2025-01-01"
        data = {"prices": [100, 101, 102], "returns": [0.01, 0.01]}

        # 1. Should be miss initially
        self.assertIsNone(get_cached_market_data(symbol, days, to_date))

        # 2. Cache it
        cache_market_data(symbol, days, to_date, data)

        # 3. Should be hit
        cached = get_cached_market_data(symbol, days, to_date)
        self.assertIsNotNone(cached)
        self.assertEqual(cached['prices'], data['prices'])

    @patch('packages.quantum.market_data.requests.Session')
    @patch('packages.quantum.market_data.get_cached_market_data')
    @patch('packages.quantum.market_data.cache_market_data')
    def test_polygon_service_uses_cache(self, mock_save, mock_get, mock_session):
        # Setup Service
        service = PolygonService(api_key="test_key")

        # Mock Cache Hit
        mock_get.return_value = {"prices": [10, 11], "returns": [0.1]}

        # Call
        result = service.get_historical_prices("AAPL", days=5, to_date=datetime(2025, 1, 1))

        # Verify
        self.assertEqual(result['prices'], [10, 11])
        mock_get.assert_called()
        # Should NOT call API (mock_session.get should not be called)
        # However, PolygonService init calls mount, but get_historical_prices calls session.get
        # We need to verify session.get was not called for the data URL
        # session object is created in init. We mocked Session class, so service.session is a Mock.
        service.session.get.assert_not_called()

    @patch('packages.quantum.market_data.requests.Session')
    @patch('packages.quantum.market_data.get_cached_market_data')
    @patch('packages.quantum.market_data.cache_market_data')
    def test_polygon_service_cache_miss_and_save(self, mock_save, mock_get, mock_session):
        service = PolygonService(api_key="test_key")
        mock_get.return_value = None # Miss

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"c": 100, "t": 1609459200000},
                {"c": 101, "t": 1609545600000}
            ]
        }
        service.session.get.return_value = mock_response

        # Call
        result = service.get_historical_prices("AAPL", days=5, to_date=datetime(2025, 1, 1))

        # Verify
        self.assertEqual(len(result['prices']), 2)
        mock_get.assert_called()
        service.session.get.assert_called()
        mock_save.assert_called()

    @patch('packages.quantum.market_data.requests.Session')
    def test_missing_api_key_returns_none_if_safe(self, mock_session):
        # Start with NO env var and force api_key=None
        with patch.dict(os.environ, {}, clear=True):
            service = PolygonService(api_key=None)
            result = service.get_historical_prices("AAPL", days=5)
            self.assertIsNone(result)

    @patch('packages.quantum.market_data.requests.Session')
    @patch('packages.quantum.market_data.get_cached_market_data')
    def test_rate_limit_handling(self, mock_get, mock_session):
        import requests

        # Setup service and cache miss
        service = PolygonService(api_key="test_key")
        mock_get.return_value = None

        # Simulate RequestException (e.g. 429 or Timeout)
        # Mocking session.get to raise exception
        service.session.get.side_effect = requests.exceptions.RequestException("Rate Limit")

        # Call - should catch and return None
        result = service.get_historical_prices("AAPL", days=5)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
