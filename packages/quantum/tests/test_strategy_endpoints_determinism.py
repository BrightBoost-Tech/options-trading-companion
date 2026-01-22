"""
Tests for determinism in strategy endpoints and param hashing.
Verifies fix for JSON serialization consistency.
"""
import unittest
import json
from packages.quantum.services.replay.canonical import canonical_json_bytes

class TestStrategyEndpointsDeterminism(unittest.TestCase):
    def test_canonical_json_determinism(self):
        """Verify that canonical_json_bytes is deterministic across ordering and spacing."""
        params1 = {"b": 2, "a": 1, "c": [3, 2, 1]}
        params2 = {"a": 1, "c": [3, 2, 1], "b": 2}

        # New method
        hash1 = canonical_json_bytes(params1).decode("utf-8")
        hash2 = canonical_json_bytes(params2).decode("utf-8")

        self.assertEqual(hash1, hash2)

        # Verify compact format (no spaces)
        self.assertNotIn(" ", hash1)
        self.assertEqual(hash1, '{"a":1,"b":2,"c":[3,2,1]}')

    def test_float_normalization(self):
        """Verify float normalization handles precision consistently."""
        # Using a float that might have representation issues
        params = {"val": 1.0/3.0}

        json_str = canonical_json_bytes(params).decode("utf-8")

        # Should be normalized to fixed precision (e.g. 6 decimals per canonical.py)
        # 0.333333333... -> 0.333333
        self.assertIn('"val":"0.333333"', json_str)

if __name__ == "__main__":
    unittest.main()
