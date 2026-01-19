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
