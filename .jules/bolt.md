## 2025-05-23 - [Pandas Overhead on Small Batches]
**Learning:** Using `pandas` for data manipulation (creation, type conversion, grouping) on small datasets (e.g., batch size of 2) is significantly slower than using native Python dictionaries and lists. The initialization overhead dominates the execution time.
**Action:** For small-batch data processing, prefer native Python `dict` aggregation and list comprehensions over `pandas`.

## 2025-05-23 - [Redundant Data Filtering Cost]
**Learning:** Even simple operations like date parsing (`datetime.fromisoformat`) and dictionary lookups become expensive when repeated inside high-volume loops (e.g., thousands of option contracts).
**Action:** When consuming data from a trusted source (like an internal service or API with filtering params), trust the source's filtering instead of re-verifying every item, especially in hot paths.

## 2026-01-15 - [Vectorized Indicators in Simulation]
**Learning:** Calculating technical indicators iteratively inside a simulation loop creates O(N^2) complexity due to repeated list slicing and re-computation. Pre-calculating them vectorized (O(N)) reduced simulation time by ~45%.
**Action:** For historical simulations where the full price series is known upfront, always pre-calculate indicators using vectorized operations (Pandas/NumPy) instead of computing them step-by-step.

## 2026-05-24 - [Pandas Rolling Overhead]
**Learning:** Pandas `rolling()` operations carry significant overhead compared to NumPy's `sliding_window_view` + `mean/std` for simple sliding windows. Switching to pure NumPy yielded a ~2.4x speedup for indicator calculations.
**Action:** Prefer `numpy.lib.stride_tricks.sliding_window_view` for sliding window calculations on arrays when Pandas index alignment/features are not strictly necessary.

## 2026-06-02 - [Vectorized Conditional Logic]
**Learning:** Complex conditional logic (e.g., state machines, regime detection) inside loops can be vectorized using `np.select` and `np.where`, eliminating Python interpreter overhead. This yielded a ~30% speedup for historical simulations.
**Action:** Replace "if-else" chains inside hot loops with `np.select` when the logic depends on vectorized inputs.

## 2026-06-12 - [SciPy Norm CDF Overhead]
**Learning:** `scipy.stats.norm.cdf` has significant overhead (~8.4s for 100k calls) compared to a pure Python implementation using `math.erf` (~0.03s). This overhead is critical in hot loops like option scanners.
**Action:** Replace `scipy.stats.norm.cdf` with a custom `math.erf` based implementation (`0.5 * (1 + erf(x / sqrt(2)))`) for scalar calculations in performance-critical paths.

## 2026-06-15 - [Decimal Overhead in Float Normalization]
**Learning:** Converting floats to `Decimal` solely for fixed-point rounding (e.g. `Decimal(str(val)).quantize(...)`) is ~2.5x slower than using integer arithmetic (`int(val * 1e6 + 0.5) / 1e6`). For high-frequency serialization/hashing of floats, this overhead adds up.
**Action:** Use integer scaling and rounding for fixed-precision float normalization in performance-critical paths, while ensuring proper handling of NaN/Inf and overflow risks.

## 2026-06-18 - [JSX Conditional Rendering Efficiency]
**Learning:** Performing O(N) operations like `.filter(...).length` inside JSX for conditional rendering triggers redundant computations on every re-render, even if the result is static. Using `useMemo` to pre-calculate these values ensures O(1) checks during the render phase.
**Action:** Move expensive conditional logic (like array filtering) into `useMemo` blocks and reference the memoized value in JSX.

## 2026-07-28 - [Iterative List Slicing Trap]
**Learning:** Repeatedly slicing a growing list (e.g., `history[:i+1]`) inside a simulation loop creates an implicit O(N^2) memory copy bottleneck, which is often invisible in small tests. Replacing this with pre-calculated vectorized arrays and O(1) index lookups yielded a ~25x speedup for 10k items.
**Action:** Identify loops where history is passed to a stateless function by slicing, and replace them with vectorized pre-calculation on the full array.

## 2026-08-15 - [Linear Search in Sorted Time Series]
**Learning:** Iterating linearly to find a start date in a sorted time series is O(N) and can be slow in tight loops (e.g., parameter sweeps). Using `bisect_left` (binary search) reduces this to O(log N).
**Action:** Always use the `bisect` module for finding insertion points or values in sorted lists, especially for date/time lookups in simulations.
