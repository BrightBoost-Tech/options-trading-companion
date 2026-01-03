"""
Market Data Cache Service
Implements a TTL cache with namespaces, file fallback, robust key generation, and in-flight locking.
"""
import os
import time
import json
import logging
import hashlib
import threading
from typing import Dict, Any, Optional, Union, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Default TTLs
TTL_QUOTES = 60         # 1 minute
TTL_SNAPSHOTS = 300     # 5 minutes
TTL_OHLC = 43200        # 12 hours
TTL_EARNINGS = 86400    # 24 hours

class MarketDataCache:
    """
    Thread-safe in-memory cache with optional file persistence.
    Supports namespaced keys with individual TTLs.
    """

    def __init__(self, file_path: Optional[str] = None, persist: bool = False):
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._inflight_locks: Dict[str, threading.Lock] = {}
        self._inflight_counts: Dict[str, int] = {} # Ref counting for cleanup
        self._inflight_registry_lock = threading.Lock()

        self.persist = persist
        # Default to a file in the same directory if not provided
        self.file_path = file_path or os.path.join(os.path.dirname(__file__), "market_data_v2.json")

        if self.persist:
            self._load_from_file()

    def _get_namespaced_key(self, namespace: str, key_parts: Union[str, List[Any]]) -> str:
        """
        Generates a deterministic key from namespace and parts.
        key_parts can be a single string or a list of items.
        """
        if isinstance(key_parts, str):
            raw_key = key_parts
        else:
            # Join parts with separator
            raw_key = "_".join(str(p) for p in key_parts)

        # Hash for consistent length and safety
        hashed = hashlib.md5(raw_key.encode()).hexdigest()
        return f"{namespace}:{hashed}"

    def get(self, namespace: str, key_parts: Union[str, List[Any]]) -> Optional[Any]:
        full_key = self._get_namespaced_key(namespace, key_parts)

        with self._lock:
            entry = self._memory_cache.get(full_key)

            if not entry:
                return None

            if time.time() > entry['expiry']:
                del self._memory_cache[full_key]
                return None

            return entry['data']

    def set(self, namespace: str, key_parts: Union[str, List[Any]], value: Any, ttl_seconds: int = 300) -> None:
        full_key = self._get_namespaced_key(namespace, key_parts)

        with self._lock:
            self._memory_cache[full_key] = {
                'data': value,
                'expiry': time.time() + ttl_seconds,
                'set_at': time.time()
            }

            if self.persist:
                self._save_to_file_safe()

    @contextmanager
    def inflight_lock(self, namespace: str, key_parts: Union[str, List[Any]]):
        """
        Context manager to acquire a lock for a specific cache key.
        Prevents cache stampede by ensuring only one thread fetches data for a missing key.
        Cleans up lock references to avoid memory leaks.
        """
        full_key = self._get_namespaced_key(namespace, key_parts)

        # Get or create lock for this specific key
        with self._inflight_registry_lock:
            if full_key not in self._inflight_locks:
                self._inflight_locks[full_key] = threading.Lock()
                self._inflight_counts[full_key] = 0

            lock = self._inflight_locks[full_key]
            self._inflight_counts[full_key] += 1

        acquired = lock.acquire(blocking=True)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

            # Cleanup reference
            with self._inflight_registry_lock:
                self._inflight_counts[full_key] -= 1
                if self._inflight_counts[full_key] <= 0:
                    # Double check no new waiters came in between release and now
                    # (Waiters would have incremented count before acquiring)
                    if full_key in self._inflight_locks:
                         del self._inflight_locks[full_key]
                         del self._inflight_counts[full_key]

    def _load_from_file(self):
        """Loads cache from file if it exists."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    data = json.load(f)

                with self._lock:
                    now = time.time()
                    # Prune expired on load
                    count = 0
                    for k, v in data.items():
                        if v.get('expiry', 0) > now:
                            self._memory_cache[k] = v
                            count += 1
                    logger.info(f"Loaded {count} entries from market data cache.")
            except Exception as e:
                logger.warning(f"Failed to load cache from file: {e}")

    def _save_to_file_safe(self):
        """Persists current cache to file, swallowing errors."""
        try:
            # Atomic write pattern could be better, but simple write is okay for now
            with open(self.file_path, 'w') as f:
                json.dump(self._memory_cache, f)
        except Exception as e:
            logger.error(f"Failed to save cache to file: {e}")

    def clear_namespace(self, namespace: str):
        prefix = f"{namespace}:"
        with self._lock:
            keys_to_delete = [k for k in self._memory_cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._memory_cache[k]
            if self.persist:
                self._save_to_file_safe()

    def get_stats(self) -> Dict[str, int]:
        """Returns basic stats about the cache."""
        with self._lock:
            total_items = len(self._memory_cache)
            now = time.time()
            active_items = sum(1 for v in self._memory_cache.values() if v['expiry'] > now)
            return {
                "total_entries": total_items,
                "active_entries": active_items
            }

# Global instance
_CACHE_INSTANCE = None
_CACHE_LOCK = threading.Lock()

def get_market_data_cache(persist: bool = False) -> MarketDataCache:
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            # Save cache in the services directory
            cache_dir = os.path.dirname(__file__)
            cache_file = os.path.join(cache_dir, "market_data_v2.json")
            _CACHE_INSTANCE = MarketDataCache(file_path=cache_file, persist=persist)
    return _CACHE_INSTANCE
