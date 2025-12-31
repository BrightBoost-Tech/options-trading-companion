import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import os
import shutil
from packages.quantum.market_data import PolygonService
from packages.quantum.market_data_cache import get_cached_market_data, cache_market_data

class TestPolygonCacheGuardrails(unittest.TestCase):
    def setUp(self):
        # Create a temp cache dir for testing
        self.test_cache_dir = "test_market_data_cache"
        self.patcher = patch("packages.quantum.market_data_cache.CACHE_DIR", self.test_cache_dir)
        self.patcher.start()
        os.makedirs(self.test_cache_dir, exist_ok=True)

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.test_cache_dir):
            shutil.rmtree(self.test_cache_dir)

    def test_cache_hit_avoids_api_call(self):
        """Test that if data is in cache, the API is not called."""
        symbol = "AAPL"
        today = datetime.now().strftime('%Y-%m-%d')

        # Seed cache
        mock_data = {
            "symbol": symbol,
            "prices": [100, 101, 102],
            "returns": [0.01, 0.01],
            "dates": ["2023-01-01", "2023-01-02", "2023-01-03"]
        }
        cache_market_data(symbol, 5, today, mock_data)

        # Init service with mock session
        service = PolygonService(api_key="fake_key")
        service.session.get = MagicMock()

        # Call get_historical_prices
        result = service.get_historical_prices(symbol, days=5)

        # Assertions
        self.assertEqual(result, mock_data)
        service.session.get.assert_not_called()

    def test_missing_api_key_returns_none(self):
        """Test that missing API key returns None gracefully if not in cache."""
        service = PolygonService(api_key=None)
        # Ensure env var is also not set or we explicitly pass None
        service.api_key = None

        result = service.get_historical_prices("GOOG", days=5)
        self.assertIsNone(result)

    def test_api_failure_returns_none(self):
        """Test that API failure (timeout/rate limit) returns None gracefully."""
        service = PolygonService(api_key="fake_key")

        # Mock requests.get to raise an exception
        mock_response = MagicMock()
        from requests.exceptions import RequestException
        mock_response.raise_for_status.side_effect = RequestException("Rate Limited")
        service.session.get = MagicMock(return_value=mock_response)

        result = service.get_historical_prices("MSFT", days=5)
        self.assertIsNone(result)

    def test_option_normalization_cache_consistency(self):
        """Test that 'O:' prefix is handled consistently in cache keys."""
        symbol_raw = "AMZN230616C00125000"
        symbol_norm = "O:AMZN230616C00125000"
        today = datetime.now().strftime('%Y-%m-%d')

        # Cache with normalized symbol
        mock_data = {"prices": [1, 2]}
        cache_market_data(symbol_norm, 5, today, mock_data)

        # Retrieve with raw symbol (should normalize internally and hit cache)
        service = PolygonService(api_key="fake_key")
        service.session.get = MagicMock() # Should not be called

        result = service.get_historical_prices(symbol_raw, days=5)
        self.assertEqual(result, mock_data)

    def test_weekend_roll(self):
        """Test that weekend dates roll back to Friday."""
        service = PolygonService(api_key="fake_key")
        service.session.get = MagicMock()

        # Saturday -> Friday
        saturday = datetime(2023, 10, 7) # Oct 7 2023 is Sat
        friday = datetime(2023, 10, 6)

        # Mock cache to return None so we hit API (which we mocked)
        with patch('packages.quantum.market_data.get_cached_market_data', return_value=None) as mock_cache:
            # Mock the API call to return valid data so we don't fail later
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'results': [
                    {'c': 100, 't': 1600000000000}
                ]
            }
            mock_response.status_code = 200
            service.session.get.return_value = mock_response

            service.get_historical_prices("AAPL", days=5, to_date=saturday)

            # Check what date was used for cache key
            # args[2] is the 3rd argument (symbol, days, to_date_str)
            args, _ = mock_cache.call_args
            to_date_str = args[2]
            self.assertEqual(to_date_str, friday.strftime('%Y-%m-%d'))

            # Also check API URL
            call_args = service.session.get.call_args
            url = call_args[0][0]
            # URL ends with .../from_str/to_str
            self.assertTrue(url.endswith(friday.strftime('%Y-%m-%d')))

if __name__ == "__main__":
    unittest.main()
