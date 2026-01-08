## 2025-05-23 - [Pandas Overhead on Small Batches]
**Learning:** Using `pandas` for data manipulation (creation, type conversion, grouping) on small datasets (e.g., batch size of 2) is significantly slower than using native Python dictionaries and lists. The initialization overhead dominates the execution time.
**Action:** For small-batch data processing, prefer native Python `dict` aggregation and list comprehensions over `pandas`.

## 2025-05-23 - [Redundant Data Filtering Cost]
**Learning:** Even simple operations like date parsing (`datetime.fromisoformat`) and dictionary lookups become expensive when repeated inside high-volume loops (e.g., thousands of option contracts).
**Action:** When consuming data from a trusted source (like an internal service or API with filtering params), trust the source's filtering instead of re-verifying every item, especially in hot paths.
