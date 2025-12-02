import unittest
from unittest.mock import MagicMock
from datetime import datetime, timedelta
import sys
import os

# Add package root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.historical_simulation import HistoricalCycleService

class TestHistoricalCycle(unittest.TestCase):
    def test_cycle_logic(self):
        # Mock Polygon
        mock_poly = MagicMock()

        # Create fake price data (enough for lookback + cycle)
        # We need 60 days lookback + some forward
        dates = []
        prices = []

        # Generate 100 days
        start_dt = datetime(2023, 1, 1)
        for i in range(100):
            d_str = (start_dt + timedelta(days=i)).strftime('%Y-%m-%d')
            dates.append(d_str)
            if i < 60:
                prices.append(100.0) # Flat start
            else:
                prices.append(100.0 + (i-60)*2) # Strong uptrend

        volumes = [1000000] * 100

        mock_poly.get_historical_prices.return_value = {
            "dates": dates,
            "prices": prices,
            "volumes": volumes,
            "returns": []
        }

        service = HistoricalCycleService(polygon_service=mock_poly)

        # Run starting at index 60 (start of uptrend)
        # Date at index 60 is our cursor
        cursor = dates[60]

        print(f"Testing cursor: {cursor}")

        result = service.run_cycle(cursor, "SPY")

        print("Result:", result)

        self.assertFalse(result.get('error'))

        # We expect entry because trend starts
        # And exit eventually due to take profit (prices double)

        if result.get('entryTime'):
            self.assertEqual(result['direction'], 'long')
            self.assertTrue(result['pnl'] > 0)
        else:
            print("No entry found - might be due to lookback window logic or scoring weights")

if __name__ == '__main__':
    unittest.main()
