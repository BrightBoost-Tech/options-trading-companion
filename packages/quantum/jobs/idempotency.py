from datetime import datetime, date
from packages.quantum.observability.canonical import compute_content_hash

def daily_key(d: date, suffix: str = None) -> str:
    """Returns a key for daily idempotency (e.g. 2023-10-27)."""
    base = d.isoformat()
    return f"{base}:{suffix}" if suffix else base

def hourly_key(dt: datetime, suffix: str = None) -> str:
    """Returns a key for hourly idempotency (e.g. 2023-10-27T10)."""
    base = dt.strftime("%Y-%m-%dT%H")
    return f"{base}:{suffix}" if suffix else base

def weekly_key(d: date) -> str:
    """Returns a key for weekly idempotency (Year-WeekNumber)."""
    # Using ISO calendar year and week number
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"

def stable_hash(payload: dict) -> str:
    """Returns a short SHA256 hash of the payload dictionary."""
    # Using compute_content_hash for deterministic serialization (float normalization, sorted keys, etc)
    return compute_content_hash(payload)
