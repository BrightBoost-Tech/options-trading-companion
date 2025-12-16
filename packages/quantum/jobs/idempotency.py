import hashlib
import json
from datetime import datetime, date

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
    # sort_keys=True ensures consistent ordering for the same dictionary content
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
