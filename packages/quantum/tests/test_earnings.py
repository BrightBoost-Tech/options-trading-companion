import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import os
import json

from packages.quantum.services.earnings_calendar_service import EarningsCalendarService
from packages.quantum.market_data import PolygonService

class TestEarningsCalendarService(unittest.TestCase):
    def setUp(self):
        self.mock_polygon = MagicMock(spec=PolygonService)
        self.service = EarningsCalendarService(self.mock_polygon)

        # Patch cache to avoid file I/O and side effects
        self.patcher_get = patch('packages.quantum.services.earnings_calendar_service.get_cached_data')
        self.patcher_save = patch('packages.quantum.services.earnings_calendar_service.save_to_cache')

        self.mock_get_cache = self.patcher_get.start()
        self.mock_save_cache = self.patcher_save.start()

        # Default cache miss
        self.mock_get_cache.return_value = None

    def tearDown(self):
        self.patcher_get.stop()
        self.patcher_save.stop()

    def test_get_earnings_date_cache_hit(self):
        # Arrange
        symbol = "AAPL"
        expected_date = datetime(2025, 1, 20)
        self.mock_get_cache.return_value = {"date": expected_date.isoformat()}

        # Act
        result = self.service.get_earnings_date(symbol)

        # Assert
        self.assertEqual(result, expected_date)
        self.mock_polygon.get_ticker_details.assert_not_called()

    def test_etf_exclusion(self):
        # Arrange
        symbol = "SPY"
        self.mock_polygon.get_ticker_details.return_value = {"type": "ETF"}

        # Act
        result = self.service.get_earnings_date(symbol)

        # Assert
        self.assertIsNone(result)
        # Should cache the None result
        self.mock_save_cache.assert_called_with((f"earnings_{symbol}",), {"date": None})

    def test_estimate_earnings_from_last_filing(self):
        # Arrange
        symbol = "TSLA"
        self.mock_polygon.get_ticker_details.return_value = {"type": "CS"}

        last_filing = datetime(2023, 10, 18)
        self.mock_polygon.get_last_financials_date.return_value = last_filing

        # Act
        # Note: We need to mock datetime.now() if we want deterministic "future" projection
        # The logic adds 90 days loops until > now - 1 day.
        # If we assume now is 2024-01-01
        # 1. 2023-10-18 + 90 = 2024-01-16. This is > now. So it should return this.

        # We can't easily mock datetime.now() inside the module without more patching.
        # But we can rely on the fact that the loop logic works.
        # If I run this test now (2025), 2023-10-18 will be projected forward many times.

        result = self.service.get_earnings_date(symbol)

        # Assert
        self.assertIsNotNone(result)
        self.assertGreater(result, datetime.now() - timedelta(days=1))

        # Check it's roughly 90 day intervals from base
        diff = (result - last_filing).days
        self.assertTrue(diff % 90 < 5 or diff % 90 > 85, f"Diff {diff} not close to multiple of 90")

    def test_no_data_returns_none(self):
        # Arrange
        symbol = "UNKNOWN"
        self.mock_polygon.get_ticker_details.return_value = {"type": "CS"}
        self.mock_polygon.get_last_financials_date.return_value = None

        # Act
        result = self.service.get_earnings_date(symbol)

        # Assert
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
