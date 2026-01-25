import unittest
from decimal import Decimal
from packages.quantum.observability.lineage import LineageSigner
from packages.quantum.observability.telemetry import compute_features_hash

class TestDeterminismFloat(unittest.TestCase):
    def test_lineage_signer_float_stability(self):
        """
        Verify that LineageSigner produces identical output for slightly drifting floats.
        This ensures determinism across different environments/architectures.
        """
        # Baseline
        data_base = {"val": 1.234567}
        canonical_base = LineageSigner.canonicalize(data_base)
        hash_base = LineageSigner.compute_hash(data_base)

        # Tiny drift (floating point noise)
        # 1.2345670000000001
        data_drift = {"val": 1.234567 + 1e-15}
        canonical_drift = LineageSigner.canonicalize(data_drift)
        hash_drift = LineageSigner.compute_hash(data_drift)

        # Decimal (exact)
        data_decimal = {"val": Decimal("1.234567")}
        canonical_decimal = LineageSigner.canonicalize(data_decimal)
        hash_decimal = LineageSigner.compute_hash(data_decimal)

        # Assertions
        # The canonical output should be identical because it normalizes to 6 decimal places
        self.assertEqual(canonical_base, canonical_drift, "Float drift caused canonical change")
        self.assertEqual(canonical_base, canonical_decimal, "Decimal vs Float caused canonical change")

        self.assertEqual(hash_base, hash_drift)
        self.assertEqual(hash_base, hash_decimal)

        # Verify the actual string format (should be "1.234567")
        # canonical_json_bytes produces compact JSON: {"val":"1.234567"}
        expected_str = '{"val":"1.234567"}'
        self.assertEqual(canonical_base.decode('utf-8'), expected_str)

    def test_telemetry_hash_float_stability(self):
        """
        Verify that compute_features_hash is also stable.
        """
        features_base = {"f1": 0.123456}
        hash_base = compute_features_hash(features_base)

        features_drift = {"f1": 0.1234560000000001}
        hash_drift = compute_features_hash(features_drift)

        self.assertEqual(hash_base, hash_drift, "Feature hash drifted with float noise")

if __name__ == "__main__":
    unittest.main()
