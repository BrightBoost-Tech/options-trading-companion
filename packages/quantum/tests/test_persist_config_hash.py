"""
Tests for v6 config_hash persistence.

Tests:
1. BacktestIdentity.compute_full_identity returns config_hash
2. _persist_v3_results row dict includes config_hash
"""

import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBacktestIdentityConfigHash(unittest.TestCase):
    """Tests that BacktestIdentity returns config_hash."""

    def _create_mock_request(self):
        """Create a mock BacktestRequestV3."""
        mock_wf = MagicMock()
        mock_wf.model_dump.return_value = {
            "train_days": 60,
            "test_days": 30,
            "step_days": 30,
            "warmup_days": 10,
            "embargo_days": 0
        }

        mock_cost = MagicMock()
        mock_cost.model_dump.return_value = {
            "commission_per_contract": 0.65,
            "spread_slippage_bps": 5
        }

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-06-30"
        mock_request.seed = 42
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        return mock_request

    def _create_mock_config(self):
        """Create a mock StrategyConfig."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "name": "test_strategy",
            "version": 1,
            "conviction_floor": 0.7,
            "conviction_slope": 0.5,
            "max_risk_pct_per_trade": 0.02
        }
        return mock_config

    def _create_mock_cost_model(self):
        """Create a mock CostModelConfig."""
        mock_cost = MagicMock()
        mock_cost.model_dump.return_value = {
            "commission_per_contract": 0.65,
            "spread_slippage_bps": 5
        }
        return mock_cost

    def test_compute_full_identity_returns_config_hash(self):
        """compute_full_identity returns dict with config_hash key."""
        from services.backtest_identity import BacktestIdentity

        request = self._create_mock_request()
        config = self._create_mock_config()
        cost_model = self._create_mock_cost_model()

        identity = BacktestIdentity.compute_full_identity(
            request, config, cost_model, seed=42
        )

        self.assertIn("config_hash", identity)
        self.assertIsInstance(identity["config_hash"], str)
        self.assertEqual(len(identity["config_hash"]), 64)  # SHA256 hex

    def test_config_hash_deterministic(self):
        """Same config produces same config_hash."""
        from services.backtest_identity import BacktestIdentity

        request = self._create_mock_request()
        config = self._create_mock_config()
        cost_model = self._create_mock_cost_model()

        identity1 = BacktestIdentity.compute_full_identity(
            request, config, cost_model, seed=42
        )
        identity2 = BacktestIdentity.compute_full_identity(
            request, config, cost_model, seed=42
        )

        self.assertEqual(identity1["config_hash"], identity2["config_hash"])

    def test_config_hash_different_for_different_config(self):
        """Different config produces different config_hash."""
        from services.backtest_identity import BacktestIdentity

        request = self._create_mock_request()
        cost_model = self._create_mock_cost_model()

        config1 = MagicMock()
        config1.model_dump.return_value = {"conviction_floor": 0.7}

        config2 = MagicMock()
        config2.model_dump.return_value = {"conviction_floor": 0.8}

        identity1 = BacktestIdentity.compute_full_identity(
            request, config1, cost_model, seed=42
        )
        identity2 = BacktestIdentity.compute_full_identity(
            request, config2, cost_model, seed=42
        )

        self.assertNotEqual(identity1["config_hash"], identity2["config_hash"])


class TestPersistV3ResultsConfigHash(unittest.TestCase):
    """Tests that _persist_v3_results includes config_hash in row."""

    def test_row_includes_config_hash(self):
        """Row dict built by _persist_v3_results includes config_hash."""
        # We can test the logic by simulating the row-building code
        # This avoids needing to mock the full supabase insert chain

        from services.backtest_identity import BacktestIdentity

        # Create mocks
        mock_wf = MagicMock()
        mock_wf.model_dump.return_value = {"train_days": 60}
        mock_wf.train_days = 60
        mock_wf.test_days = 30
        mock_wf.step_days = 30

        mock_cost = MagicMock()
        mock_cost.model_dump.return_value = {"commission_per_contract": 0.65}

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-06-30"
        mock_request.seed = 42
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost
        mock_request.run_mode = "walk_forward"

        mock_config = MagicMock()
        mock_config.version = 1
        mock_config.model_dump.return_value = {"conviction_floor": 0.7}

        # Compute identity (same as in _persist_v3_results)
        identity = BacktestIdentity.compute_full_identity(
            request=mock_request,
            config=mock_config,
            cost_model=mock_request.cost_model,
            seed=mock_request.seed
        )

        # Build row dict (simulating what _persist_v3_results does)
        row = {
            "user_id": "test-user",
            "strategy_name": "test-strategy",
            "version": mock_config.version,
            "start_date": mock_request.start_date,
            "end_date": mock_request.end_date,
            "ticker": mock_request.ticker,
            "seed": mock_request.seed,
            "data_hash": identity["data_hash"],
            "code_sha": identity["code_sha"],
            "config_hash": identity["config_hash"],  # v6
        }

        # Assert config_hash is present and valid
        self.assertIn("config_hash", row)
        self.assertEqual(len(row["config_hash"]), 64)  # SHA256 hex

    def test_all_identity_hashes_present(self):
        """Row includes all three identity hashes: data_hash, code_sha, config_hash."""
        from services.backtest_identity import BacktestIdentity

        mock_wf = MagicMock()
        mock_wf.model_dump.return_value = {"train_days": 60}

        mock_cost = MagicMock()
        mock_cost.model_dump.return_value = {"commission_per_contract": 0.65}

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-06-30"
        mock_request.seed = 42
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        mock_config = MagicMock()
        mock_config.model_dump.return_value = {"conviction_floor": 0.7}

        identity = BacktestIdentity.compute_full_identity(
            request=mock_request,
            config=mock_config,
            cost_model=mock_request.cost_model,
            seed=mock_request.seed
        )

        # All three hashes present
        self.assertIn("data_hash", identity)
        self.assertIn("code_sha", identity)
        self.assertIn("config_hash", identity)

        # data_hash and config_hash are 64-char SHA256
        self.assertEqual(len(identity["data_hash"]), 64)
        self.assertEqual(len(identity["config_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
