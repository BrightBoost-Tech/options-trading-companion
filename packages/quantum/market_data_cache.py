"""
Market Data Cache Module
Provides caching for Polygon historical data to prevent rate limits and speed up batch processing.
"""
import os
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict

CACHE_DIR = "market_data_cache"
CACHE_TTL_HOURS = 24

def _get_cache_key(symbol: str, days: int, to_date_str: str) -> str:
    """Generates a deterministic cache key/filename."""
    raw_key = f"{symbol}_{days}_{to_date_str}"
    return hashlib.md5(raw_key.encode()).hexdigest()

def _get_cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{key}.json")

def get_cached_market_data(symbol: str, days: int, to_date_str: str) -> Optional[Dict]:
    """
    Retrieves cached market data if available and fresh.
    """
    key = _get_cache_key(symbol, days, to_date_str)
    path = _get_cache_path(key)

    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r') as f:
            cached = json.load(f)

        # Check TTL (optional, since data is historical and keyed by end_date, it shouldn't change much,
        # but re-fetching ensures corrections are propagated)
        cached_ts = datetime.fromisoformat(cached['timestamp'])
        age_hours = (datetime.now() - cached_ts).total_seconds() / 3600

        if age_hours < CACHE_TTL_HOURS:
            # print(f"[Cache] Hit for {symbol} (age: {age_hours:.1f}h)")
            return cached['data']

        # print(f"[Cache] Expired for {symbol}")
        return None

    except Exception as e:
        print(f"[Cache] Read error for {symbol}: {e}")
        return None

def cache_market_data(symbol: str, days: int, to_date_str: str, data: Dict):
    """
    Saves market data to cache.
    """
    key = _get_cache_key(symbol, days, to_date_str)
    path = _get_cache_path(key)

    try:
        payload = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'days': days,
            'to_date': to_date_str,
            'data': data
        }

        with open(path, 'w') as f:
            json.dump(payload, f)

    except Exception as e:
        print(f"[Cache] Write error for {symbol}: {e}")
