
import unittest
import time
import os
import shutil
import json
import threading
from datetime import datetime, timedelta
from packages.quantum.services.market_data_cache import MarketDataCache, get_market_data_cache

class TestMarketDataCache(unittest.TestCase):
    def setUp(self):
        # Use a temporary test file
        self.test_cache_file = "test_market_data_cache.json"
        self.cache = MarketDataCache(file_path=self.test_cache_file, persist=True)

    def tearDown(self):
        # Clean up
        if os.path.exists(self.test_cache_file):
            os.remove(self.test_cache_file)
        # Clear singleton if needed, though we use instance here

    def test_set_and_get(self):
        self.cache.set("TEST", "key1", "value1", ttl_seconds=10)
        value = self.cache.get("TEST", "key1")
        self.assertEqual(value, "value1")

    def test_ttl_expiry(self):
        self.cache.set("TEST", "key2", "value2", ttl_seconds=1)
        time.sleep(1.1)
        value = self.cache.get("TEST", "key2")
        self.assertIsNone(value)

    def test_persistence(self):
        self.cache.set("PERSIST", "key3", "value3", ttl_seconds=60)
        # Force save
        self.cache._save_to_file_safe()

        # New instance loading from same file
        new_cache = MarketDataCache(file_path=self.test_cache_file, persist=True)
        value = new_cache.get("PERSIST", "key3")
        self.assertEqual(value, "value3")

    def test_namespaces(self):
        self.cache.set("NS1", "key", "val1", ttl_seconds=60)
        self.cache.set("NS2", "key", "val2", ttl_seconds=60)

        self.assertEqual(self.cache.get("NS1", "key"), "val1")
        self.assertEqual(self.cache.get("NS2", "key"), "val2")

    def test_complex_keys_no_sort(self):
        # Update test to reflect that lists are NOT sorted automatically anymore
        key = ["AAPL", 100, "2023-01-01"]
        self.cache.set("COMPLEX", key, "data", ttl_seconds=60)

        # Exact match should work
        self.assertEqual(self.cache.get("COMPLEX", key), "data")

        # Shuffled key should NOT match now (which is expected per new design)
        key_shuffled = ["2023-01-01", "AAPL", 100]
        self.assertIsNone(self.cache.get("COMPLEX", key_shuffled))

    def test_clear_namespace(self):
        self.cache.set("CLEAR", "k1", "v1", ttl_seconds=60)
        self.cache.set("KEEP", "k1", "v1", ttl_seconds=60)

        self.cache.clear_namespace("CLEAR")

        self.assertIsNone(self.cache.get("CLEAR", "k1"))
        self.assertEqual(self.cache.get("KEEP", "k1"), "v1")

    def test_inflight_lock(self):
        # Verify that inflight lock allows sequential access or blocking
        # Ideally we'd test concurrency, but simple functional check:
        with self.cache.inflight_lock("LOCK", "key"):
            # Inside lock
            pass

        # Verify separate threads block (simulated)
        def worker(results):
            with self.cache.inflight_lock("LOCK", "shared"):
                results.append("start")
                time.sleep(0.1)
                results.append("end")

        results = []
        t1 = threading.Thread(target=worker, args=(results,))
        t2 = threading.Thread(target=worker, args=(results,))

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Expected: start, end, start, end (atomic blocks)
        # Not: start, start, end, end
        self.assertEqual(results, ["start", "end", "start", "end"])

if __name__ == '__main__':
    unittest.main()
