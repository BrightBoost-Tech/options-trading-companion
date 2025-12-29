## 2025-05-23 - [Scalar vs Array Performance]
**Learning:** `np.array(list)` creates a full copy of the data, which is O(N). When calculating rolling windows or stats on a subset of data (like SMA20/50 from a list of 1000 items), slicing the list first (`list[-50:]`) is O(K) and significantly faster than converting the entire list to an array first.
**Action:** Always slice Python lists to the minimum required window *before* passing them to NumPy functions or converting them to arrays.

## 2025-05-23 - [Scalar Math Optimization]
**Learning:** For scalar floating-point operations, Python's built-in `math` module (e.g., `math.exp`) and `max/min` are significantly faster (2-10x) than NumPy's counterparts (`np.exp`, `np.clip`) because they avoid the overhead of type checking and array dispatch.
**Action:** Use `math.*` and Python built-ins for scalar calculations inside hot loops; reserve NumPy for actual vector operations.
