import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from packages.quantum.services.earnings_calendar_service import (
    EarningsCalendarService,
    LocalStubEarningsProvider,
    PolygonEarningsProvider
)
from packages.quantum.cache import save_to_cache, get_cached_data

class TestEarningsCalendarService(unittest.TestCase):

    def setUp(self):
        # Clear env to force Stub default unless patched
        self.original_api_key = os.environ.get("POLYGON_API_KEY")
        if "POLYGON_API_KEY" in os.environ:
            del os.environ["POLYGON_API_KEY"]

        # Mock cache to avoid file I/O
        self.patcher_get = patch('packages.quantum.services.earnings_calendar_service.get_cached_data')
        self.mock_get_cache = self.patcher_get.start()

        self.patcher_save = patch('packages.quantum.services.earnings_calendar_service.save_to_cache')
        self.mock_save_cache = self.patcher_save.start()

    def tearDown(self):
        self.patcher_get.stop()
        self.patcher_save.stop()
        if self.original_api_key:
            os.environ["POLYGON_API_KEY"] = self.original_api_key

    def test_stub_provider_defaults(self):
        """Test that service uses Stub provider when API key is missing."""
        service = EarningsCalendarService()
        self.assertIsInstance(service.provider, LocalStubEarningsProvider)

        # Test known symbol
        self.mock_get_cache.return_value = None
        d = service.get_earnings_date("AAPL")
        self.assertIsInstance(d, date)
        self.assertEqual(d, date(2025, 5, 2)) # Match static map in stub

        # Test unknown symbol
        d_unknown = service.get_earnings_date("UNKNOWN123")
        self.assertIsNone(d_unknown)

    def test_polygon_provider_selection(self):
        """Test that service uses Polygon provider when API key is present."""
        os.environ["POLYGON_API_KEY"] = "fake_key"
        service = EarningsCalendarService()
        self.assertIsInstance(service.provider, PolygonEarningsProvider)

    def test_caching_logic(self):
        """Test cache hit vs miss."""
        service = EarningsCalendarService() # Stub

        # 1. Cache Miss
        self.mock_get_cache.return_value = None
        d = service.get_earnings_date("AAPL")
        self.assertEqual(d, date(2025, 5, 2))
        self.mock_save_cache.assert_called() # Should save result

        # 2. Cache Hit
        self.mock_get_cache.return_value = {"date": "2025-06-01"}
        d_cached = service.get_earnings_date("AAPL")
        self.assertEqual(d_cached, date(2025, 6, 1))
        # Provider should NOT be called (implied, but we can't easily assert on internal provider calls without mocking it directly)

    def test_batch_fetch(self):
        """Test get_earnings_map batching."""
        service = EarningsCalendarService()

        # Setup cache: AAPL is cached, MSFT is not
        def side_effect(key):
            if key == ("earnings_AAPL",):
                return {"date": "2025-05-02"}
            return None
        self.mock_get_cache.side_effect = side_effect

        results = service.get_earnings_map(["AAPL", "MSFT", "SPY"])

        self.assertEqual(results["AAPL"], date(2025, 5, 2))
        self.assertEqual(results["MSFT"], date(2025, 4, 25)) # From Stub map
        self.assertIsNone(results["SPY"]) # ETF

    def test_polygon_provider_logic(self):
        """Mock PolygonService to test the provider logic independently."""
        mock_poly = MagicMock()
        provider = PolygonEarningsProvider(mock_poly)

        # Case 1: ETF
        mock_poly.get_ticker_details.return_value = {'type': 'ETF'}
        self.assertIsNone(provider.get_next_earnings("SPY"))

        # Case 2: Stock with financials
        mock_poly.get_ticker_details.return_value = {'type': 'CS'}
        # Last financial was 60 days ago
        last_date = date.today() - timedelta(days=60)
        mock_poly.get_last_financials_date.return_value = datetime(last_date.year, last_date.month, last_date.day)

        next_date = provider.get_next_earnings("TEST")
        # Estimate: last + 90 days = today - 60 + 90 = today + 30
        expected = last_date + timedelta(days=90)
        self.assertEqual(next_date, expected)

if __name__ == '__main__':
    unittest.main()
