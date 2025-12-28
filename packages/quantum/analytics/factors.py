import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Union

def calculate_trend(prices: List[float]) -> str:
    """
    Determines trend using simple moving averages (SMA20 vs SMA50).
    Returns 'UP', 'DOWN', or 'NEUTRAL'.
    """
    if len(prices) < 50:
        return "NEUTRAL"

    # Optimization: Slice the list before converting to numpy array
    # We only need the last 50 prices for SMA50 and SMA20
    prices_arr = np.array(prices[-50:])

    sma_20 = np.mean(prices_arr[-20:])
    sma_50 = np.mean(prices_arr[-50:])

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

    # Optimization: Only process relevant data
    # We only need the last 'period' + 1 prices to calculate the last 'period' deltas
    prices_arr = np.array(prices[-(period+1):])

    deltas = np.diff(prices_arr)
    # deltas will have length 'period'
    seed = deltas # usage of variable name 'seed' preserved from original logic

    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_volatility(prices: List[float], window: int = 30) -> float:
    """
    Calculates annualized volatility of returns over the last `window` days.
    """
    if len(prices) < window + 1:
        return 0.0

    # Optimization: Only process relevant data
    # To get `window` returns, we need `window+1` prices.
    prices_arr = np.array(prices[-(window+1):])

    returns = np.diff(prices_arr) / prices_arr[:-1]
    vol = np.std(returns) * np.sqrt(252)
    return float(vol)
