## 2025-05-23 - [Date Parsing Performance]
**Learning:** `datetime.strptime(s, "%Y-%m-%d")` is surprisingly slow (~14µs) compared to `datetime.fromisoformat(s)` (~0.4µs) for ISO-8601 strings. When processing thousands of option contracts in a loop, this difference adds up.
**Action:** Use `datetime.fromisoformat()` for standard date strings and cache parsed dates when iterating over data with repeated dates (like option chains).
