import numpy as np
import pandas as pd
import math
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Union, Dict

def calculate_indicators_vectorized(prices: List[float]) -> Dict[str, np.ndarray]:
    """
    Calculates Trend, Volatility, and RSI for the entire price series using vectorized operations.
    Returns aligned numpy arrays matching the input length.
    """
    if not prices:
        return {
            "trend": np.array([]),
            "volatility": np.array([]),
            "rsi": np.array([])
        }

    s = pd.Series(prices)
    n = len(s)

    # 1. Trend (SMA20 > SMA50)
    # Existing logic: if len < 50 return "NEUTRAL"
    sma20 = s.rolling(20).mean()
    sma50 = s.rolling(50).mean()

    trend = np.full(n, 'NEUTRAL', dtype=object)

    # Only compare where we have data for SMA50 (implied index >= 49)
    # sma20 will also be valid there
    valid_mask = sma50.notna()

    if valid_mask.any():
        up_mask = (sma20 > sma50) & valid_mask
        down_mask = (sma20 <= sma50) & valid_mask

        trend[up_mask] = 'UP'
        trend[down_mask] = 'DOWN'

    # 2. Volatility
    # Annualized vol of 30-day returns.
    # Existing logic: if len < 31 return 0.0
    # Rolling window of 30 on returns requires 30 returns, which requires 31 prices.
    # Pandas: s.pct_change() gives returns. rolling(30) on returns gives result at index 30 (len 31).

    pct_change = s.pct_change()
    # ddof=0 to match population std dev used in original code
    vol = pct_change.rolling(30).std(ddof=0) * np.sqrt(252)
    vol = vol.fillna(0.0).values

    # 3. RSI
    # Existing logic: Simple average of gains/losses over period 14.
    # if len < 15 return 50.0
    period = 14
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()

    # Calculate RS
    # Existing logic quirk: if down average is 0, rs = 0.
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = ma_up / ma_down
        # Fix division by zero or where ma_down is 0 (pure uptrend -> 0 in existing logic)
        rs[ma_down == 0] = 0.0

    rsi = 100 - (100 / (1 + rs))

    # Fill NaN (initial period) with 50.0
    rsi = rsi.fillna(50.0).values

    return {
        "trend": trend,
        "volatility": vol,
        "rsi": rsi
    }

def calculate_trend(prices: List[float]) -> str:
    """
    Determines trend using simple moving averages (SMA20 vs SMA50).
    Returns 'UP', 'DOWN', or 'NEUTRAL'.
    """
    if len(prices) < 50:
        return "NEUTRAL"

    # Optimization: Use pure Python slice and sum for speed on small lists
    # Avoiding numpy overhead for simple scalar means
    # SMA20 needs last 20 prices
    # SMA50 needs last 50 prices

    # We can perform the slicing directly on the list
    sma_20_slice = prices[-20:]
    sma_50_slice = prices[-50:]

    # Calculate means
    sma_20 = sum(sma_20_slice) / 20.0
    sma_50 = sum(sma_50_slice) / 50.0

    if sma_20 > sma_50:
        return "UP"
    else:
        return "DOWN"

def calculate_iv_rank(returns: List[float], days: int = 365) -> float:
    """
    Calculates IV Rank (approximated by HV Rank) from historical returns.
    Returns a value between 0.0 and 100.0, or None if insufficient data.
    """
    if not returns or len(returns) < 30:
        return None

    # Use NumPy sliding window view for vectorized performance (O(N))
    # Avoids Python loops and overhead of pandas Series creation

    # Optimization: If returns is very large (e.g. backtesting), limit to relevant window
    # We need 'days' of history for the rank + window size for the rolling vol
    window_size = 30
    required_len = days + window_size

    if len(returns) > required_len:
        returns_arr = np.array(returns[-required_len:])
    else:
        returns_arr = np.array(returns)

    # Check sufficient data again after conversion
    if len(returns_arr) < 30:
        return None

    # Create rolling windows of size 30
    # shape will be (N - 29, 30)
    windows = sliding_window_view(returns_arr, window_shape=30)

    # Calculate std dev for each window along axis 1
    # ddof=0 matches original implementation (population std)
    rolling_vol = np.std(windows, axis=1, ddof=0) * np.sqrt(252)

    if rolling_vol.size == 0:
        return None

    # Get 52-week high and low
    high_52_week = np.max(rolling_vol)
    low_52_week = np.min(rolling_vol)

    # Avoid division by zero
    if high_52_week == low_52_week:
        return None

    # Current volatility (last window)
    current_vol = rolling_vol[-1]

    # IV Rank formula
    iv_rank = ((current_vol - low_52_week) / (high_52_week - low_52_week)) * 100

    return max(0.0, min(100.0, float(iv_rank)))

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """
    Calculates RSI.
    """
    if len(prices) < period + 1:
        return 50.0

    # Optimization: Pure Python calculation is ~5x faster for small windows (N=14)
    # than creating a NumPy array and doing vector operations.

    # We only need the last 'period' + 1 prices to calculate the last 'period' deltas
    relevant_prices = prices[-(period+1):]

    up_sum = 0.0
    down_sum = 0.0

    # Calculate deltas and sums in one pass
    for i in range(len(relevant_prices) - 1):
        diff = relevant_prices[i+1] - relevant_prices[i]
        if diff >= 0:
            up_sum += diff
        else:
            down_sum -= diff # down is positive magnitude of negative move

    # Average gains/losses
    up = up_sum / period
    down = down_sum / period

    # Preserve original logic: rs = up / down if down != 0 else 0
    # Note: If down is 0 (pure uptrend), this returns 0, which results in RSI=0.
    # This preserves existing behavior exactly.
    if down == 0:
        rs = 0.0
    else:
        rs = up / down

    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_volatility(prices: List[float], window: int = 30) -> float:
    """
    Calculates annualized volatility of returns over the last `window` days.
    """
    if len(prices) < window + 1:
        return 0.0

    # Optimization: Pure Python variance calculation
    # Faster than np.std for small window sizes (N=30)

    relevant_prices = prices[-(window+1):]

    # Calculate returns: (p[i+1] - p[i]) / p[i]
    # We can do this in a single pass to compute mean and sum_sq_diffs

    returns = []
    sum_returns = 0.0

    for i in range(len(relevant_prices) - 1):
        p_start = relevant_prices[i]
        p_end = relevant_prices[i+1]

        # Avoid division by zero if price is 0 (though unlikely for asset prices)
        if p_start == 0:
            ret = 0.0
        else:
            ret = (p_end - p_start) / p_start

        returns.append(ret)
        sum_returns += ret

    n = len(returns)
    if n == 0:
        return 0.0

    mean_ret = sum_returns / n

    sum_sq_diff = 0.0
    for r in returns:
        diff = r - mean_ret
        sum_sq_diff += diff * diff

    # Standard deviation (population, ddof=0 to match np.std default)
    # If we wanted sample std, we'd divide by n-1
    # Original code used np.std which defaults to ddof=0
    variance = sum_sq_diff / n
    std_dev = math.sqrt(variance)

    vol = std_dev * math.sqrt(252)
    return float(vol)
