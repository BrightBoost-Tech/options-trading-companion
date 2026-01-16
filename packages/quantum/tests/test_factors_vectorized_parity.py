import unittest
import numpy as np
import pandas as pd
from packages.quantum.analytics.factors import calculate_indicators_vectorized

# Original implementation copied for reference
def reference_calculate_indicators_vectorized(prices):
    if not prices:
        return {
            "trend": np.array([]),
            "volatility": np.array([]),
            "rsi": np.array([])
        }

    s = pd.Series(prices)
    n = len(s)

    # 1. Trend (SMA20 > SMA50)
    sma20 = s.rolling(20).mean()
    sma50 = s.rolling(50).mean()

    trend = np.full(n, 'NEUTRAL', dtype=object)

    valid_mask = sma50.notna()

    if valid_mask.any():
        up_mask = (sma20 > sma50) & valid_mask
        down_mask = (sma20 <= sma50) & valid_mask

        trend[up_mask] = 'UP'
        trend[down_mask] = 'DOWN'

    # 2. Volatility
    pct_change = s.pct_change()
    vol = pct_change.rolling(30).std(ddof=0) * np.sqrt(252)
    vol = vol.fillna(0.0).values

    # 3. RSI
    period = 14
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = ma_up / ma_down
        # Fix division by zero or where ma_down is 0 (pure uptrend -> 0 in existing logic)
        if isinstance(rs, pd.Series):
             mask = (ma_down == 0)
             rs[mask] = 0.0
        else:
             rs[ma_down == 0] = 0.0

    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50.0).values

    return {
        "trend": trend,
        "volatility": vol,
        "rsi": rsi
    }

class TestFactorsVectorizedParity(unittest.TestCase):
    def test_parity_random_data(self):
        # Generate random data
        np.random.seed(42)
        prices = (np.random.rand(1000) * 100 + 50).tolist() # Positive prices

        reference = reference_calculate_indicators_vectorized(prices)
        # currently calculates_indicators_vectorized is the same as reference
        # but after we change it, this test will verify parity
        current = calculate_indicators_vectorized(prices)

        # Check Trend
        np.testing.assert_array_equal(reference['trend'], current['trend'], err_msg="Trend mismatch")

        # Check Volatility
        np.testing.assert_allclose(reference['volatility'], current['volatility'], rtol=1e-5, atol=1e-8, err_msg="Volatility mismatch")

        # Check RSI
        np.testing.assert_allclose(reference['rsi'], current['rsi'], rtol=1e-5, atol=1e-8, err_msg="RSI mismatch")

    def test_parity_edge_cases(self):
        # Case 1: Short data
        prices_short = [100.0, 101.0, 102.0]
        reference = reference_calculate_indicators_vectorized(prices_short)
        current = calculate_indicators_vectorized(prices_short)

        np.testing.assert_array_equal(reference['trend'], current['trend'])
        np.testing.assert_allclose(reference['volatility'], current['volatility'])
        np.testing.assert_allclose(reference['rsi'], current['rsi'])

        # Case 2: Zero volatility (flat)
        prices_flat = [100.0] * 100
        reference = reference_calculate_indicators_vectorized(prices_flat)
        current = calculate_indicators_vectorized(prices_flat)

        np.testing.assert_array_equal(reference['trend'], current['trend'])
        np.testing.assert_allclose(reference['volatility'], current['volatility'])
        np.testing.assert_allclose(reference['rsi'], current['rsi'])

        # Case 3: Pure uptrend (RSI behavior check)
        prices_up = [10.0 + i for i in range(100)]
        reference = reference_calculate_indicators_vectorized(prices_up)
        current = calculate_indicators_vectorized(prices_up)

        np.testing.assert_allclose(reference['rsi'], current['rsi'])
        # Ensure it is 0.0 as per legacy behavior
        # (Though reference implementation dictates what is correct for this test)

    def test_empty_input(self):
        prices = []
        reference = reference_calculate_indicators_vectorized(prices)
        current = calculate_indicators_vectorized(prices)

        np.testing.assert_array_equal(reference['trend'], current['trend'])
        np.testing.assert_array_equal(reference['volatility'], current['volatility'])
        np.testing.assert_array_equal(reference['rsi'], current['rsi'])

if __name__ == '__main__':
    unittest.main()
