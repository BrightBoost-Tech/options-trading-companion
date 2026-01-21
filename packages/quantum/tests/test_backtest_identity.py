"""
Tests for backtest_identity.py deterministic hashing.

Tests:
1. Same inputs produce same hash (determinism)
2. Different inputs produce different hashes
3. code_sha fallback behavior
"""

import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBacktestIdentity(unittest.TestCase):
    """Tests for BacktestIdentity deterministic hashing."""

    def _create_mock_request(self, ticker="SPY", start="2024-01-01", end="2024-06-30", seed=42):
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
        mock_request.ticker = ticker
        mock_request.start_date = start
        mock_request.end_date = end
        mock_request.seed = seed
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        return mock_request

    def _create_mock_config(self, conviction_floor=0.7):
        """Create a mock StrategyConfig."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "name": "test_strategy",
            "version": 1,
            "conviction_floor": conviction_floor,
            "conviction_slope": 0.5,
            "max_risk_pct_per_trade": 0.02,
            "max_risk_pct_portfolio": 0.10
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

    def test_hash_dict_deterministic(self):
        """Same dict produces same hash on repeated calls."""
        from services.backtest_identity import BacktestIdentity

        obj = {"a": 1, "b": 2, "c": [3, 4, 5]}

        hash1 = BacktestIdentity.hash_dict(obj)
        hash2 = BacktestIdentity.hash_dict(obj)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA256 hex

    def test_hash_dict_key_order_independent(self):
        """Key order doesn't affect hash (sorted internally)."""
        from services.backtest_identity import BacktestIdentity

        obj1 = {"z": 1, "a": 2, "m": 3}
        obj2 = {"a": 2, "m": 3, "z": 1}

        self.assertEqual(
            BacktestIdentity.hash_dict(obj1),
            BacktestIdentity.hash_dict(obj2)
        )

    def test_hash_dict_different_values_different_hash(self):
        """Different values produce different hashes."""
        from services.backtest_identity import BacktestIdentity

        obj1 = {"a": 1}
        obj2 = {"a": 2}

        self.assertNotEqual(
            BacktestIdentity.hash_dict(obj1),
            BacktestIdentity.hash_dict(obj2)
        )

    def test_compute_data_hash_deterministic(self):
        """Same request produces same data_hash."""
        from services.backtest_identity import BacktestIdentity

        request = self._create_mock_request()

        hash1 = BacktestIdentity.compute_data_hash(request)
        hash2 = BacktestIdentity.compute_data_hash(request)

        self.assertEqual(hash1, hash2)

    def test_compute_data_hash_different_ticker(self):
        """Different ticker produces different data_hash."""
        from services.backtest_identity import BacktestIdentity

        request1 = self._create_mock_request(ticker="SPY")
        request2 = self._create_mock_request(ticker="QQQ")

        hash1 = BacktestIdentity.compute_data_hash(request1)
        hash2 = BacktestIdentity.compute_data_hash(request2)

        self.assertNotEqual(hash1, hash2)

    def test_compute_data_hash_different_dates(self):
        """Different date range produces different data_hash."""
        from services.backtest_identity import BacktestIdentity

        request1 = self._create_mock_request(start="2024-01-01", end="2024-06-30")
        request2 = self._create_mock_request(start="2024-01-01", end="2024-12-31")

        hash1 = BacktestIdentity.compute_data_hash(request1)
        hash2 = BacktestIdentity.compute_data_hash(request2)

        self.assertNotEqual(hash1, hash2)

    def test_compute_config_hash_deterministic(self):
        """Same config/cost/seed produces same config_hash."""
        from services.backtest_identity import BacktestIdentity

        config = self._create_mock_config()
        cost_model = self._create_mock_cost_model()
        seed = 42

        hash1 = BacktestIdentity.compute_config_hash(config, cost_model, seed)
        hash2 = BacktestIdentity.compute_config_hash(config, cost_model, seed)

        self.assertEqual(hash1, hash2)

    def test_compute_config_hash_different_seed(self):
        """Different seed produces different config_hash."""
        from services.backtest_identity import BacktestIdentity

        config = self._create_mock_config()
        cost_model = self._create_mock_cost_model()

        hash1 = BacktestIdentity.compute_config_hash(config, cost_model, seed=42)
        hash2 = BacktestIdentity.compute_config_hash(config, cost_model, seed=123)

        self.assertNotEqual(hash1, hash2)

    def test_compute_config_hash_different_conviction(self):
        """Different config values produce different config_hash."""
        from services.backtest_identity import BacktestIdentity

        config1 = self._create_mock_config(conviction_floor=0.7)
        config2 = self._create_mock_config(conviction_floor=0.8)
        cost_model = self._create_mock_cost_model()

        hash1 = BacktestIdentity.compute_config_hash(config1, cost_model, seed=42)
        hash2 = BacktestIdentity.compute_config_hash(config2, cost_model, seed=42)

        self.assertNotEqual(hash1, hash2)

    def test_get_code_sha_from_env(self):
        """get_code_sha reads from environment variable."""
        from services.backtest_identity import BacktestIdentity

        with patch.dict(os.environ, {"GIT_SHA": "abc123def456"}):
            sha = BacktestIdentity.get_code_sha()
            self.assertEqual(sha, "abc123def456")

    def test_get_code_sha_railway_fallback(self):
        """get_code_sha falls back to RAILWAY_GIT_COMMIT_SHA."""
        from services.backtest_identity import BacktestIdentity

        env = {"RAILWAY_GIT_COMMIT_SHA": "railway123"}
        with patch.dict(os.environ, env, clear=True):
            sha = BacktestIdentity.get_code_sha()
            self.assertEqual(sha, "railway123")

    def test_get_code_sha_unknown_fallback(self):
        """get_code_sha returns 'unknown' when no env var set."""
        from services.backtest_identity import BacktestIdentity

        with patch.dict(os.environ, {}, clear=True):
            sha = BacktestIdentity.get_code_sha()
            self.assertEqual(sha, "unknown")

    def test_compute_full_identity_returns_all_hashes(self):
        """compute_full_identity returns data_hash, config_hash, code_sha."""
        from services.backtest_identity import BacktestIdentity

        request = self._create_mock_request()
        config = self._create_mock_config()
        cost_model = self._create_mock_cost_model()

        with patch.dict(os.environ, {"GIT_SHA": "test_sha_123"}):
            identity = BacktestIdentity.compute_full_identity(
                request, config, cost_model, seed=42
            )

        self.assertIn("data_hash", identity)
        self.assertIn("config_hash", identity)
        self.assertIn("code_sha", identity)
        self.assertEqual(len(identity["data_hash"]), 64)
        self.assertEqual(len(identity["config_hash"]), 64)
        self.assertEqual(identity["code_sha"], "test_sha_123")


if __name__ == "__main__":
    unittest.main()
