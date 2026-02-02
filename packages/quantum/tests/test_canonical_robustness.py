
import unittest
import json
from datetime import datetime, timezone
from packages.quantum.observability.canonical import compute_content_hash, canonical_json_bytes

class TestCanonicalRobustness(unittest.TestCase):
    def test_mixed_key_types(self):
        """
        Verify that compute_content_hash does not crash with mixed key types
        (e.g., int and str) in the same dictionary.
        This was a crash in the previous implementation due to sorted() failure.
        """
        data = {1: "a", "b": 2}
        try:
            hash_val = compute_content_hash(data)
            self.assertTrue(len(hash_val) > 0)
        except TypeError:
            self.fail("compute_content_hash crashed on mixed key types")

    def test_int_str_key_equivalence(self):
        """
        Verify that integer keys and string keys produce identical hashes.
        This ensures stability and backward compatibility with JSON which only supports string keys.
        """
        data_int = {1: "a", 2: "b"}
        data_str = {"1": "a", "2": "b"}

        h1 = compute_content_hash(data_int)
        h2 = compute_content_hash(data_str)

        self.assertEqual(h1, h2, "Int keys should produce same hash as String keys")

    def test_datetime_keys(self):
        """
        Verify that datetime objects can be used as keys without crashing.
        Previously, json.dumps would fail on these even if normalized values were OK.
        """
        dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
        data = {dt: "event"}

        try:
            h = compute_content_hash(data)
            self.assertTrue(len(h) > 0)
        except TypeError:
            self.fail("compute_content_hash crashed on datetime keys")

        # Verify deterministic output (ISO string key)
        # Expected key: "2023-01-01 00:00:00+00:00" -> stringified
        # Note: str(dt) includes space, not T, depending on python version?
        # datetime.__str__ is '2023-01-01 00:00:00+00:00' usually.
        # This differs from our ISO serialization for VALUES which uses 'T' and 'Z'.
        # But for KEYS, we use str(k).
        # This is acceptable as long as it's deterministic.

        # Let's ensure it's stable
        h2 = compute_content_hash({str(dt): "event"})
        self.assertEqual(h, h2)

    def test_tuple_keys(self):
        """
        Verify that tuple keys can be used.
        """
        data = {(1, 2): "val"}
        try:
            h = compute_content_hash(data)
            self.assertTrue(len(h) > 0)
        except TypeError:
            self.fail("compute_content_hash crashed on tuple keys")

        h2 = compute_content_hash({str((1, 2)): "val"})
        self.assertEqual(h, h2)

if __name__ == "__main__":
    unittest.main()
