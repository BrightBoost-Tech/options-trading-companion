## 2025-05-23 - [Pandas Overhead on Small Batches]
**Learning:** Using `pandas` for data manipulation (creation, type conversion, grouping) on small datasets (e.g., batch size of 2) is significantly slower than using native Python dictionaries and lists. The initialization overhead dominates the execution time.
**Action:** For small-batch data processing, prefer native Python `dict` aggregation and list comprehensions over `pandas`.
