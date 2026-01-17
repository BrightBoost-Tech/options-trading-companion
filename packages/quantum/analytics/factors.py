import numpy as np
import math
from numpy.lib.stride_tricks import sliding_window_view
from typing import List, Dict

def fast_rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """
    Calculates rolling mean using O(N) cumsum approach.
    Significantly faster than sliding_window_view + mean (O(N*W)).
    Handles NaNs by falling back to robust sliding window method.
    """
    if len(arr) < window:
        return np.array([])

    # Fast check for NaNs - if present, use robust slow path
    if np.isnan(arr).any():
        windows = sliding_window_view(arr, window_shape=window)
        return np.mean(windows, axis=1)

    # Optimization: O(N) using cumsum
    # Prepend 0 to simplify indexing
    cs = np.insert(np.cumsum(arr, dtype=np.float64), 0, 0)

    # Calculate sum of windows
    # window_sum[i] = cs[i+window] - cs[i]
    # corresponding to arr[i : i+window]
    window_sums = cs[window:] - cs[:-window]

    return window_sums / window

def calculate_indicators_vectorized(prices: List[float]) -> Dict[str, np.ndarray]:
    """
    Calculates Trend, Volatility, and RSI for the entire price series using vectorized operations.
    Returns aligned numpy arrays matching the input length.
    Optimized to use NumPy directly instead of Pandas for performance.
    """
    if not prices:
        return {
            "trend": np.array([]),
            "volatility": np.array([]),
            "rsi": np.array([])
        }

    # Convert to array once
    prices_arr = np.array(prices, dtype=np.float64)
    n = len(prices_arr)

    # --- 1. Trend (SMA20 > SMA50) ---
    trend = np.full(n, 'NEUTRAL', dtype=object)

    if n >= 50:
        sma20_valid = fast_rolling_mean(prices_arr, 20)
        sma50_valid = fast_rolling_mean(prices_arr, 50)

        # Align them
        # sma50_valid length is N - 49. It covers indices [49, ..., N-1].
        # sma20_valid length is N - 19. It covers indices [19, ..., N-1].
        # We need sma20 values starting from index 49.
        # Index 49 in original array corresponds to index (49-19)=30 in sma20_valid.

        sma20_aligned = sma20_valid[30:]

        # Compare
        up_mask = sma20_aligned > sma50_valid
        down_mask = sma20_aligned <= sma50_valid

        # Map to original trend array indices [49:]
        trend_slice = trend[49:]
        trend_slice[up_mask] = 'UP'
        trend_slice[down_mask] = 'DOWN'

    # --- 2. Volatility ---
    # Annualized vol of 30-day returns.
    # Matches logic: pct_change().rolling(30).std(ddof=0) * sqrt(252)
    vol = np.zeros(n, dtype=np.float64)

    # We need at least 31 prices to get 30 returns and 1 window
    if n >= 31:
        # Calculate Returns: (p[i+1] - p[i]) / p[i]
        # Handle division by zero
        denom = prices_arr[:-1].copy()
        # Avoid division by zero
        denom[denom == 0] = np.nan

        returns = (prices_arr[1:] - prices_arr[:-1]) / denom
        # Replace infs/nans with 0.0 to handle bad data safely
        returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

        # Rolling std(30) on returns
        # sliding_window_view on returns (length N-1)
        windows_ret = sliding_window_view(returns, window_shape=30)

        # ddof=0 matches population std
        stds = np.std(windows_ret, axis=1, ddof=0)
        vol_valid = stds * np.sqrt(252)

        # Align
        # Returns index 0 is p1/p0 - 1.
        # First window of returns [0..29] corresponds to result at index 30 (p30).
        # So vol_valid corresponds to prices[30:]
        vol[30:] = vol_valid

    # --- 3. RSI ---
    # Period 14
    # Legacy behavior: if pure uptrend (down avg=0), RSI=0.
    # Initial 14 values (0..13) are 50.0
    rsi = np.full(n, 50.0, dtype=np.float64)

    if n >= 15: # need 15 prices for first RSI at index 14
        period = 14
        deltas = np.diff(prices_arr)

        up = np.maximum(deltas, 0)
        down = -np.minimum(deltas, 0)

        # Rolling mean of period 14 - Optimized using cumsum
        ma_up = fast_rolling_mean(up, period)
        ma_down = fast_rolling_mean(down, period)

        with np.errstate(divide='ignore', invalid='ignore'):
            rs = ma_up / ma_down
            # Preserve legacy behavior: if ma_down is 0, rs=0 -> RSI=0
            rs[ma_down == 0] = 0.0

        rsi_valid = 100 - (100 / (1 + rs))

        # Align
        # First valid window corresponds to index 14
        rsi[period:] = rsi_valid

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
