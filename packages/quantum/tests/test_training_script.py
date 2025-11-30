import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from datetime import datetime
import sys
import os

# Ensure package root is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

from packages.quantum.scripts.train_symbol_adapters import train_adapters, SymbolAdapterState

class TestTrainingScript(unittest.TestCase):

    def test_train_adapters_volatility_underestimation(self):
        """
        If model consistently underestimates volatility (surprise is high, realized vol is high?),
        scaler should increase.
        """
        # Mock Data
        # Predicted vol (implicit via existing adapters or logs) doesn't matter too much
        # because the function uses 'surprise' score and simple heuristics.
        # "If model consistently underestimates volatility... update signals... increase sigma_scaler"

        # We simulate a "high surprise" scenario where risk was higher than expected.
        data = []
        for i in range(10):
            data.append({
                "inference": {
                    "symbol_universe": ["TEST"],
                    "predicted_mu": {"TEST": 0.05},
                    "predicted_sigma": {} # Ignored by current simple heuristic
                },
                "outcome": {
                    "realized_pl_1d": 0.0,
                    "realized_vol_1d": 0.05, # High?
                    "surprise_score": 80.0, # Very surprising (implies miss)
                    "created_at": datetime.now().isoformat()
                }
            })

        current_adapters = {
            "TEST": SymbolAdapterState("TEST", 0.0, 1.0)
        }

        updated = train_adapters(data, current_adapters, learning_rate=0.1)

        # Scaler should increase
        self.assertGreater(updated["TEST"].sigma_scaler, 1.0)
        self.assertLessEqual(updated["TEST"].sigma_scaler, 1.5) # Should not explode (clamped in training? or runtime?)
        # Logic has loose clamps [0.5, 3.0] in training script. Runtime has [0.8, 1.5].
        # Let's check training script clamps.

    def test_train_adapters_negative_pnl(self):
        """
        If PnL is consistently negative, alpha should decrease.
        """
        data = []
        for i in range(10):
            data.append({
                "inference": {
                    "symbol_universe": ["FAIL_STOCK"],
                    "predicted_mu": {"FAIL_STOCK": 0.05}
                },
                "outcome": {
                    "realized_pl_1d": -100.0,
                    "realized_vol_1d": 0.01,
                    "surprise_score": 20.0, # Not too surprising maybe?
                }
            })

        current_adapters = {
            "FAIL_STOCK": SymbolAdapterState("FAIL_STOCK", 0.0, 1.0)
        }

        updated = train_adapters(data, current_adapters, learning_rate=0.1)

        # Alpha should be negative
        self.assertLess(updated["FAIL_STOCK"].alpha_adjustment, 0.0)

if __name__ == '__main__':
    unittest.main()
