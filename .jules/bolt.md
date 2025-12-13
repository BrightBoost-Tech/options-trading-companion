# Bolt's Journal ⚡

## 2024-05-22 - [Initial Setup]
**Learning:** Journal was missing. Created it to track critical performance learnings.
**Action:** Always check for existence before reading.

## 2025-02-23 - [Parallel I/O Optimization]
**Learning:** When optimizing synchronous I/O bound tasks in Python (like API scanners), `ThreadPoolExecutor` + `requests.Session` is a powerful combination that avoids the complexity of full `asyncio` rewrites while delivering similar performance gains for network-heavy operations.
**Action:** Look for other synchronous loops over network calls (e.g., backtesting, data syncing) to apply this pattern.
