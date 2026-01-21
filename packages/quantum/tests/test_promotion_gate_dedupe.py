"""
Tests for v7 promotion gate and dedupe functionality.

Tests:
1. Promotion gate eligibility thresholds
2. Promotion tier assignment
3. Promotion reasons populated
4. Dedupe skips duplicate inserts
5. Param hash computation deterministic
"""

import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPromotionGateEligibility(unittest.TestCase):
    """Tests for evaluate_promotion_gate function."""

    def test_eligible_live_all_thresholds_met(self):
        """Strategy meeting all live thresholds is eligible_live=True."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 1.5,
            "max_drawdown": 0.10,
            "total_trades": 100,
            "win_rate": 0.55,
            "stability_score": 70.0,
            "pct_positive_folds": 0.8,
            "total_pnl": 5000.0,
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertTrue(result["eligible_micro_live"])
        self.assertTrue(result["eligible_live"])
        self.assertEqual(result["promotion_tier"], "live")

    def test_eligible_micro_live_only(self):
        """Strategy meeting micro-live but not live thresholds."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 0.7,  # Above micro-live (0.5) but below live (1.0)
            "max_drawdown": 0.20,  # Above micro-live (0.25) but above live (0.15)
            "total_trades": 30,  # Above micro-live (20) but below live (50)
            "win_rate": 0.40,  # Above micro-live (0.35) but below live (0.45)
            "stability_score": 40.0,  # Above micro-live (25) but below live (50)
            "pct_positive_folds": 0.5,  # Below live (0.6)
            "total_pnl": 1000.0,
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertTrue(result["eligible_micro_live"])
        self.assertFalse(result["eligible_live"])
        self.assertEqual(result["promotion_tier"], "micro_live")

    def test_not_eligible_paper_tier(self):
        """Strategy with positive PnL but failing thresholds gets paper tier."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 0.3,  # Below micro-live
            "max_drawdown": 0.30,  # Above micro-live limit
            "total_trades": 10,  # Below minimum
            "win_rate": 0.30,
            "stability_score": 20.0,
            "pct_positive_folds": 0.3,
            "total_pnl": 100.0,  # Positive
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertFalse(result["eligible_micro_live"])
        self.assertFalse(result["eligible_live"])
        self.assertEqual(result["promotion_tier"], "paper")

    def test_rejected_tier_negative_pnl(self):
        """Strategy with negative PnL gets rejected tier."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": -0.5,
            "max_drawdown": 0.40,
            "total_trades": 15,
            "win_rate": 0.25,
            "stability_score": 10.0,
            "pct_positive_folds": 0.2,
            "total_pnl": -500.0,
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertFalse(result["eligible_micro_live"])
        self.assertFalse(result["eligible_live"])
        self.assertEqual(result["promotion_tier"], "rejected")

    def test_promotion_reasons_populated(self):
        """promotion_reasons list is populated with failure details."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 0.3,
            "max_drawdown": 0.30,
            "total_trades": 10,
            "win_rate": 0.30,
            "stability_score": 15.0,
            "pct_positive_folds": 0.3,
            "total_pnl": 100.0,
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertIsInstance(result["promotion_reasons"], list)
        self.assertGreater(len(result["promotion_reasons"]), 0)
        # Should contain failure reasons
        reasons_str = " ".join(result["promotion_reasons"])
        self.assertIn("sharpe", reasons_str.lower())

    def test_single_run_mode_skips_stability_checks(self):
        """Single run mode doesn't check stability_score."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 1.5,
            "max_drawdown": 0.10,
            "total_trades": 100,
            "win_rate": 0.55,
            "stability_score": 0.0,  # Would fail walk_forward check
            "pct_positive_folds": 0.0,
            "total_pnl": 5000.0,
        }

        result = evaluate_promotion_gate(metrics, "single")

        # Should still be eligible since single mode skips stability
        self.assertTrue(result["eligible_live"])

    def test_custom_thresholds(self):
        """Custom thresholds are respected."""
        from services.promotion_gate import evaluate_promotion_gate, PromotionThresholds

        metrics = {
            "sharpe": 0.3,
            "max_drawdown": 0.10,
            "total_trades": 30,
            "win_rate": 0.50,
            "stability_score": 50.0,
            "pct_positive_folds": 0.6,
            "total_pnl": 1000.0,
        }

        # With default thresholds, sharpe 0.3 fails micro-live (needs 0.5)
        result_default = evaluate_promotion_gate(metrics, "walk_forward")
        self.assertFalse(result_default["eligible_micro_live"])

        # With custom lower threshold
        custom = PromotionThresholds(micro_live_min_sharpe=0.2)
        result_custom = evaluate_promotion_gate(metrics, "walk_forward", thresholds=custom)
        self.assertTrue(result_custom["eligible_micro_live"])


class TestParamHashComputation(unittest.TestCase):
    """Tests for compute_param_hash function."""

    def test_param_hash_deterministic(self):
        """Same params produce same hash."""
        from services.promotion_gate import compute_param_hash

        params = {"conviction_floor": 0.7, "max_risk_pct": 0.02}

        hash1 = compute_param_hash(params)
        hash2 = compute_param_hash(params)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA256 hex

    def test_param_hash_different_for_different_params(self):
        """Different params produce different hash."""
        from services.promotion_gate import compute_param_hash

        params1 = {"conviction_floor": 0.7}
        params2 = {"conviction_floor": 0.8}

        self.assertNotEqual(compute_param_hash(params1), compute_param_hash(params2))

    def test_param_hash_none_handled(self):
        """None params produce consistent hash."""
        from services.promotion_gate import compute_param_hash

        hash1 = compute_param_hash(None)
        hash2 = compute_param_hash(None)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_param_hash_empty_dict(self):
        """Empty dict produces same hash as None."""
        from services.promotion_gate import compute_param_hash

        hash_none = compute_param_hash(None)
        hash_empty = compute_param_hash({})

        self.assertEqual(hash_none, hash_empty)

    def test_param_hash_key_order_independent(self):
        """Hash is same regardless of key insertion order."""
        from services.promotion_gate import compute_param_hash

        params1 = {"a": 1, "b": 2, "c": 3}
        params2 = {"c": 3, "a": 1, "b": 2}

        self.assertEqual(compute_param_hash(params1), compute_param_hash(params2))


class TestDedupeHelper(unittest.TestCase):
    """Tests for dedupe helper logic (unit tests without full import)."""

    def _find_existing_backtest_id(
        self,
        supabase,
        user_id: str,
        strategy_name: str,
        ticker: str,
        run_mode: str,
        engine_version: str,
        data_hash: str,
        config_hash: str,
        param_hash: str,
    ):
        """Local copy of dedupe logic for testing."""
        try:
            result = (
                supabase.table("strategy_backtests")
                .select("id")
                .eq("user_id", user_id)
                .eq("strategy_name", strategy_name)
                .eq("ticker", ticker)
                .eq("run_mode", run_mode)
                .eq("engine_version", engine_version)
                .eq("data_hash", data_hash)
                .eq("config_hash", config_hash)
                .eq("param_hash", param_hash)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["id"]
            return None
        except Exception:
            return None

    def test_dedupe_finds_existing(self):
        """Returns existing ID when duplicate found."""
        mock_supabase = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"id": "existing-uuid-123"}]

        # Chain the mock calls
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        result = self._find_existing_backtest_id(
            supabase=mock_supabase,
            user_id="user-1",
            strategy_name="test-strategy",
            ticker="SPY",
            run_mode="walk_forward",
            engine_version="v3",
            data_hash="abc123",
            config_hash="def456",
            param_hash="ghi789",
        )

        self.assertEqual(result, "existing-uuid-123")

    def test_dedupe_returns_none_when_not_found(self):
        """Returns None when no duplicate exists."""
        mock_supabase = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []

        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        result = self._find_existing_backtest_id(
            supabase=mock_supabase,
            user_id="user-1",
            strategy_name="test-strategy",
            ticker="SPY",
            run_mode="walk_forward",
            engine_version="v3",
            data_hash="abc123",
            config_hash="def456",
            param_hash="ghi789",
        )

        self.assertIsNone(result)

    def test_dedupe_handles_exception(self):
        """Returns None on exception (fail-open for inserts)."""
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = Exception("DB connection error")

        result = self._find_existing_backtest_id(
            supabase=mock_supabase,
            user_id="user-1",
            strategy_name="test-strategy",
            ticker="SPY",
            run_mode="walk_forward",
            engine_version="v3",
            data_hash="abc123",
            config_hash="def456",
            param_hash="ghi789",
        )

        self.assertIsNone(result)


class TestPersistV3ResultsPromotion(unittest.TestCase):
    """Tests that promotion gate is correctly integrated with persist flow."""

    def test_promotion_gate_called_with_wf_metrics(self):
        """Promotion gate is called with metrics from walk_forward output."""
        from services.promotion_gate import evaluate_promotion_gate

        # Simulate what _persist_v3_results does with WF metrics
        metrics = {
            "sharpe": 1.5,
            "max_drawdown": 0.10,
            "trades_count": 100,
            "win_rate": 0.55,
            "total_pnl": 5000.0,
            "stability_score": 70.0,
            "pct_positive_folds": 0.8,
        }

        # Build promotion_metrics as persist function does
        promotion_metrics = {
            "sharpe": metrics.get("sharpe", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 1.0),
            "total_trades": metrics.get("trades_count", 0),
            "win_rate": metrics.get("win_rate", 0.0),
            "stability_score": metrics.get("stability_score", 0.0),
            "pct_positive_folds": metrics.get("pct_positive_folds", 0.0),
            "total_pnl": metrics.get("total_pnl", 0.0),
        }

        promotion = evaluate_promotion_gate(promotion_metrics, "walk_forward")

        # Verify promotion columns would be populated
        self.assertIn("eligible_micro_live", promotion)
        self.assertIn("eligible_live", promotion)
        self.assertIn("promotion_tier", promotion)
        self.assertIn("promotion_reasons", promotion)

        # With these good metrics, should be eligible for live
        self.assertTrue(promotion["eligible_live"])
        self.assertEqual(promotion["promotion_tier"], "live")

    def test_promotion_gate_row_integration(self):
        """Simulates row building with promotion columns."""
        from services.promotion_gate import evaluate_promotion_gate

        # Simulate metrics from a backtest result
        metrics = {
            "sharpe": 0.6,
            "max_drawdown": 0.20,
            "trades_count": 30,
            "win_rate": 0.42,
            "total_pnl": 1000.0,
            "stability_score": 35.0,
            "pct_positive_folds": 0.5,
        }

        promotion_metrics = {
            "sharpe": metrics.get("sharpe", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 1.0),
            "total_trades": metrics.get("trades_count", 0),
            "win_rate": metrics.get("win_rate", 0.0),
            "stability_score": metrics.get("stability_score", 0.0),
            "pct_positive_folds": metrics.get("pct_positive_folds", 0.0),
            "total_pnl": metrics.get("total_pnl", 0.0),
        }

        promotion = evaluate_promotion_gate(promotion_metrics, "walk_forward")

        # Build row as persist function does
        row = {
            "user_id": "test-user",
            "strategy_name": "test-strategy",
            "eligible_micro_live": promotion["eligible_micro_live"],
            "eligible_live": promotion["eligible_live"],
            "promotion_tier": promotion["promotion_tier"],
            "promotion_reasons": promotion["promotion_reasons"],
        }

        # Check row has all columns
        self.assertIn("eligible_micro_live", row)
        self.assertIn("eligible_live", row)
        self.assertIn("promotion_tier", row)
        self.assertIn("promotion_reasons", row)

        # With these mid-tier metrics, should be micro_live only
        self.assertTrue(row["eligible_micro_live"])
        self.assertFalse(row["eligible_live"])
        self.assertEqual(row["promotion_tier"], "micro_live")

    def test_dedupe_logic_returns_early(self):
        """Verifies dedupe logic pattern returns existing ID."""
        # This tests the dedupe pattern independently

        def mock_persist_with_dedupe(existing_id):
            """Simulates the dedupe check in _persist_v3_results."""
            if existing_id:
                return existing_id
            # Would normally do insert here
            return "new-id"

        # When existing record found
        result = mock_persist_with_dedupe("existing-backtest-id")
        self.assertEqual(result, "existing-backtest-id")

        # When no existing record
        result = mock_persist_with_dedupe(None)
        self.assertEqual(result, "new-id")


class TestPromotionTierLogic(unittest.TestCase):
    """Tests for promotion tier edge cases."""

    def test_zero_trades_not_eligible(self):
        """Strategy with zero trades is not eligible."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": 2.0,
            "max_drawdown": 0.05,
            "total_trades": 0,  # No trades
            "win_rate": 0.0,
            "stability_score": 80.0,
            "pct_positive_folds": 1.0,
            "total_pnl": 0.0,
        }

        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertFalse(result["eligible_micro_live"])

    def test_none_values_handled(self):
        """None values in metrics are handled gracefully."""
        from services.promotion_gate import evaluate_promotion_gate

        metrics = {
            "sharpe": None,
            "max_drawdown": None,
            "total_trades": None,
            "win_rate": None,
            "stability_score": None,
            "pct_positive_folds": None,
            "total_pnl": None,
        }

        # Should not raise
        result = evaluate_promotion_gate(metrics, "walk_forward")

        self.assertFalse(result["eligible_micro_live"])
        self.assertFalse(result["eligible_live"])
        self.assertEqual(result["promotion_tier"], "rejected")


if __name__ == "__main__":
    unittest.main()
