# Bolt's Journal ⚡

## 2024-05-22 - [Initial Setup]
**Learning:** Journal was missing. Created it to track critical performance learnings.
**Action:** Always check for existence before reading.

## 2025-02-23 - [Parallel I/O Optimization]
**Learning:** When optimizing synchronous I/O bound tasks in Python (like API scanners), `ThreadPoolExecutor` + `requests.Session` is a powerful combination that avoids the complexity of full `asyncio` rewrites while delivering similar performance gains for network-heavy operations.
**Action:** Look for other synchronous loops over network calls (e.g., backtesting, data syncing) to apply this pattern.

## 2025-02-23 - [Vectorized Rolling Windows]
**Learning:** Python loops for rolling window calculations on NumPy arrays are a major bottleneck ($O(N \cdot W)$). `numpy.lib.stride_tricks.sliding_window_view` provides a zero-copy view that allows full vectorization of rolling statistics (like `std`) along an axis, yielding ~96x speedup over loops and ~2x speedup over `pandas.Series.rolling` for simple cases.
**Action:** Replace manual loop-based sliding windows with `sliding_window_view` wherever possible in analytics code.
## 2025-05-22 - [Vectorized Sliding Window Optimization]
**Learning:** When calculating rolling statistics (like SMA, RSI, Volatility) on large datasets in Python/NumPy, converting the entire list to a NumPy array is a major bottleneck (O(N)). Slicing the Python list *before* conversion (O(K), where K is the window size) drastically reduces overhead for sequential calls.
**Action:** Always slice lists to the required window size before passing them to NumPy for rolling calculations in hot loops.
