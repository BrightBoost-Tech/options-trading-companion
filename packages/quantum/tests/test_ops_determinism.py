import unittest
from unittest.mock import MagicMock, patch
import sys
import os

class TestOpsDeterminism(unittest.TestCase):
    def test_stale_symbols_sorted(self):
        """
        Verify that compute_market_data_freshness returns sorted stale_symbols
        regardless of the order returned by MarketDataTruthLayer.
        """
        # Create a mock module for market_data_truth_layer
        mock_mdtl_module = MagicMock()
        MockLayerClass = MagicMock()
        mock_mdtl_module.MarketDataTruthLayer = MockLayerClass

        # Patch sys.modules to inject our mock module
        with patch.dict(sys.modules, {"packages.quantum.services.market_data_truth_layer": mock_mdtl_module}):
            # Import function under test
            from packages.quantum.services.ops_health_service import compute_market_data_freshness

            # Setup mock instance
            mock_layer_instance = MockLayerClass.return_value

            # Create mock snapshots
            snap_a = MagicMock()
            snap_a.quality.is_stale = True
            snap_a.quality.freshness_ms = 1000

            snap_b = MagicMock()
            snap_b.quality.is_stale = True
            snap_b.quality.freshness_ms = 1000

            # Return dict with specific insertion order (B then A)
            snapshots = {"B": snap_b, "A": snap_a}
            mock_layer_instance.snapshot_many_v4.return_value = snapshots

            # Call function
            with patch.dict(os.environ, {"POLYGON_API_KEY": "fake_key"}):
                result = compute_market_data_freshness(["A", "B"])

            # Assertions
            self.assertEqual(result.stale_symbols, ["A", "B"],
                             f"Expected sorted stale_symbols ['A', 'B'], but got {result.stale_symbols}")

if __name__ == "__main__":
    unittest.main()
