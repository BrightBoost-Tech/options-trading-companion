"""
Market Data Cache Service
Implements a TTL cache with namespaces and file fallback support.
"""
import os
import time
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MarketDataCache:
    """
    In-memory cache with optional file persistence.
    Supports namespaced keys with individual TTLs.
    """

    def __init__(self, file_path: Optional[str] = None):
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self.file_path = file_path or os.path.join(os.path.dirname(__file__), "market_data_cache.json")
        self._load_from_file()

    def _get_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    def get(self, namespace: str, key: str) -> Optional[Any]:
        full_key = self._get_key(namespace, key)
        entry = self._memory_cache.get(full_key)

        if not entry:
            return None

        if time.time() > entry['expiry']:
            del self._memory_cache[full_key]
            return None

        return entry['data']

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
        full_key = self._get_key(namespace, key)
        self._memory_cache[full_key] = {
            'data': value,
            'expiry': time.time() + ttl_seconds,
            'set_at': time.time()
        }
        # We don't save to file on every set for performance, rely on periodic or shutdown hooks ideally.
        # But for this simple implementation, we can save if it's a long-lived item?
        # For now, let's keep it in memory mostly, unless we implement explicit save.

    def _load_from_file(self):
        """Loads cache from file if it exists."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                    # Prune expired
                    now = time.time()
                    self._memory_cache = {
                        k: v for k, v in data.items()
                        if v['expiry'] > now
                    }
            except Exception as e:
                logger.warning(f"Failed to load cache from file: {e}")

    def save_to_file(self):
        """Persists current cache to file."""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self._memory_cache, f)
        except Exception as e:
            logger.error(f"Failed to save cache to file: {e}")

    def clear_namespace(self, namespace: str):
        prefix = f"{namespace}:"
        keys_to_delete = [k for k in self._memory_cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._memory_cache[k]

# Global instance
# We might want to use a different path for the cache file in production
_CACHE_INSTANCE = None

def get_market_data_cache() -> MarketDataCache:
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is None:
        # Save cache in the same directory as this file
        cache_dir = os.path.dirname(__file__)
        cache_file = os.path.join(cache_dir, "market_data_v3_cache.json")
        _CACHE_INSTANCE = MarketDataCache(file_path=cache_file)
    return _CACHE_INSTANCE
