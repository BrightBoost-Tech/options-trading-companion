import numpy as np
from typing import List, Union

def calculate_trend(prices: List[float]) -> str:
    """
    Determines trend using simple moving averages (SMA20 vs SMA50).
    Returns 'UP', 'DOWN', or 'NEUTRAL'.
    """
    if len(prices) < 50:
        return "NEUTRAL"

    prices_arr = np.array(prices)
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

    returns_arr = np.array(returns)

    # Calculate 30-day rolling volatility
    # We need at least 30 days of data
    if len(returns_arr) < 30:
        return None

    # Vectorized rolling std dev
    # Create a view of rolling windows
    # Note: simple loop is often safer/clearer for small arrays than complex stride tricks
    rolling_vol = []
    # We start from index 30 to get the first window [0:30]
    for i in range(30, len(returns_arr) + 1):
        window = returns_arr[i-30:i]
        vol = np.std(window) * np.sqrt(252)
        rolling_vol.append(vol)

    if not rolling_vol:
        return None

    rolling_vol_arr = np.array(rolling_vol)

    # Get 52-week high and low of volatility (or as much history as provided)
    high_52_week = np.max(rolling_vol_arr)
    low_52_week = np.min(rolling_vol_arr)

    # Avoid division by zero
    if high_52_week == low_52_week:
        return None

    # Current volatility (last window)
    current_vol = rolling_vol_arr[-1]

    # IV Rank formula
    iv_rank = ((current_vol - low_52_week) / (high_52_week - low_52_week)) * 100

    return max(0.0, min(100.0, float(iv_rank)))

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """
    Calculates RSI.
    """
    if len(prices) < period + 1:
        return 50.0

    prices_arr = np.array(prices)
    deltas = np.diff(prices_arr)
    seed = deltas[-period:]
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

    prices_arr = np.array(prices)
    # Returns: (P_t - P_{t-1}) / P_{t-1}
    # To get `window` returns, we need `window+1` prices.
    # diff of array of length N is N-1.

    # Take window+1 prices from end
    subset = prices_arr[-(window+1):]
    if len(subset) < window+1:
        return 0.0

    returns = np.diff(subset) / subset[:-1]
    vol = np.std(returns) * np.sqrt(252)
    return float(vol)
