import unittest
import math
import numpy as np
from packages.quantum.analytics.factors import calculate_rsi, calculate_trend, calculate_volatility

class TestFactors(unittest.TestCase):
    def test_rsi_calculations(self):
        # Case 1: Standard mixed movement
        # This sequence has ups and downs
        prices_mixed = [100.0, 101.0, 100.5, 102.0, 101.0, 103.0, 102.5, 104.0, 103.0, 105.0, 104.0, 106.0, 105.0, 107.0, 106.0, 108.0]
        # We test that it returns a valid float and is reproducible
        rsi_mixed = calculate_rsi(prices_mixed, period=14)
        self.assertIsInstance(rsi_mixed, float)
        self.assertTrue(0 <= rsi_mixed <= 100)

        # Case 2: All Up (Preserves existing behavior of returning 0.0)
        # Note: Mathematically RSI should be 100, but existing implementation returned 0.0
        # due to logic: rs = up/down if down!=0 else 0.
        prices_up = [10.0 + i for i in range(20)]
        rsi_up = calculate_rsi(prices_up, period=14)
        self.assertEqual(rsi_up, 0.0, "Should preserve existing behavior for pure uptrend (RSI=0)")

        # Case 3: All Down
        prices_down = [100.0 - i for i in range(20)]
        rsi_down = calculate_rsi(prices_down, period=14)
        self.assertEqual(rsi_down, 0.0, "Should return 0 for pure downtrend")

        # Case 4: Flat
        prices_flat = [100.0] * 20
        rsi_flat = calculate_rsi(prices_flat, period=14)
        # If flat, up=0, down=0. RS=0. RSI=0.
        self.assertEqual(rsi_flat, 0.0)

    def test_trend_calculations(self):
        # Case 1: Uptrend (SMA20 > SMA50)
        prices_up = [float(i) for i in range(60)]
        self.assertEqual(calculate_trend(prices_up), "UP")

        # Case 2: Downtrend (SMA20 < SMA50)
        prices_down = [float(100-i) for i in range(60)]
        self.assertEqual(calculate_trend(prices_down), "DOWN")

        # Case 3: Not enough data
        self.assertEqual(calculate_trend([1.0]*10), "NEUTRAL")

    def test_volatility_calculations(self):
        # Case 1: Known volatility
        # Alternating +1%, -1% (approx)
        # prices: 100, 101, 100, 101...
        prices = []
        for i in range(40):
            prices.append(100.0 if i % 2 == 0 else 101.0)

        vol = calculate_volatility(prices, window=30)
        self.assertTrue(vol > 0.0)

        # Exact value check against previous run
        # prices = [100.0, 101.0, 102.0, 101.0, 100.0] * 10
        # Vol: 0.1405890724494924
        prices_check = [100.0, 101.0, 102.0, 101.0, 100.0] * 10
        vol_check = calculate_volatility(prices_check, window=30)
        self.assertAlmostEqual(vol_check, 0.1405890724494924, places=7)

        # Case 2: Flat -> 0 vol
        self.assertEqual(calculate_volatility([10.0]*40, window=30), 0.0)

if __name__ == '__main__':
    unittest.main()
