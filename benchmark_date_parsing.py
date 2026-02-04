import time
import datetime
from functools import lru_cache

# Simulate a list of expiry strings (repeated many times as in a scan)
expiries = ["2023-10-20", "2023-10-27", "2023-11-03", "2023-11-10", "2023-11-17"] * 1000
today = datetime.date(2023, 10, 1)

def parse_uncached(exp_str):
    try:
        return datetime.datetime.fromisoformat(exp_str).date()
    except ValueError:
        return datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()

@lru_cache(maxsize=None)
def parse_cached(exp_str):
    try:
        return datetime.datetime.fromisoformat(exp_str).date()
    except ValueError:
        return datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()

# Benchmark Uncached
start = time.time()
for e in expiries:
    d = parse_uncached(e)
    diff = (d - today).days
end = time.time()
print(f"Uncached: {end - start:.4f}s")

# Benchmark Cached
start = time.time()
for e in expiries:
    d = parse_cached(e)
    diff = (d - today).days
end = time.time()
print(f"Cached: {end - start:.4f}s")
