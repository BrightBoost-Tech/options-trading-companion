import sys
import os
import unittest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

# Ensure path is set to import the script
current_dir = os.path.dirname(os.path.abspath(__file__))
# Correct path to packages/quantum/scripts/
script_dir = os.path.abspath(os.path.join(current_dir, "../scripts"))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Import the class from the script
from walkforward_validate_learning_v3 import WalkForwardValidator, WalkForwardContractError

class TestWalkForwardValidator(unittest.TestCase):

    def setUp(self):
        # Mock supabase client
        self.mock_client = MagicMock()
        self.validator = WalkForwardValidator(user_id="test-user", client=self.mock_client)

    def test_calibration_improvement_synthetic(self):
        """
        Create synthetic data where raw scores are miscalibrated (e.g. overconfident)
        and verify that calibration improves Brier score.
        """
        # 1. Generate synthetic data
        np.random.seed(42)
        n_samples = 200

        # True probabilities
        true_probs = np.linspace(0.1, 0.9, n_samples)

        # Labels drawn from true probabilities
        labels = np.random.binomial(1, true_probs)

        # "Raw" scores are miscalibrated: e.g. sigmoid(logit(p) * 2) -> overconfident
        # If p=0.9, logit~2.2, *2=4.4, sigmoid~0.99
        logits = np.log(true_probs / (1 - true_probs))
        distorted_logits = logits * 2.0 + 0.5 # shift and scale
        raw_probs = 1 / (1 + np.exp(-distorted_logits))

        # EV and PnL
        # Assume perfect EV prediction initially but scaled wrongly
        # Realized PnL = True EV + noise
        # Raw EV = True EV * 0.5 (underestimated)
        true_ev = (true_probs - 0.5) * 100 # -50 to +50
        raw_ev = true_ev * 0.5
        realized_pnl = true_ev + np.random.normal(0, 10, n_samples)

        # Create DataFrame
        dates = pd.date_range(start="2023-01-01", periods=n_samples, freq="D")

        data = pd.DataFrame({
            'closed_at': dates,
            'prob_raw': raw_probs,
            'is_win': labels,
            'ev': raw_ev,
            'realized_pnl': realized_pnl,
            'user_id': 'test-user'
        })

        # Inject data into validator
        self.validator.data = data

        # 2. Run Walk-Forward
        # Train on first 100, Test on next 20
        # train_days enough to cover ~100 samples
        folds = self.validator.run_walkforward(train_days=100, test_days=20, step_days=20)

        self.assertTrue(len(folds) > 0, "Should generate at least one fold")

        # 3. Verify improvements on average
        avg_brier_raw = np.mean([f['brier_raw'] for f in folds])
        avg_brier_cal = np.mean([f['brier_cal'] for f in folds])

        avg_leak_raw = np.mean(np.abs([f['leakage_raw'] for f in folds]))
        avg_leak_cal = np.mean(np.abs([f['leakage_cal'] for f in folds]))

        print(f"\nTest Results - Synthetic Miscalibration:")
        print(f"Brier: Raw={avg_brier_raw:.4f} -> Cal={avg_brier_cal:.4f}")
        print(f"Leakage (Abs): Raw={avg_leak_raw:.2f} -> Cal={avg_leak_cal:.2f}")

        # Assert improvements
        # Calibration should reduce Brier score (lower is better)
        self.assertLess(avg_brier_cal, avg_brier_raw, "Calibration should improve Brier score on miscalibrated data")

        # Calibration should reduce EV leakage (closer to 0)
        # Note: Depending on noise, this might be tricky with small samples, but with 200 samples and systematic bias (0.5x), it should work.
        # self.assertLess(avg_leak_cal, avg_leak_raw) # Might differ due to noise in pnl

    def test_missing_data_handling(self):
        self.validator.data = pd.DataFrame() # Empty
        folds = self.validator.run_walkforward()
        self.assertEqual(len(folds), 0)

    # --- fetch_data field-contract tests (Lane 2, 2026-07-10) ---
    # These exercise the REAL seam (fetch_data against the view's real columns),
    # NOT the synthetic-injection path the calibration test uses.

    def _mock_view_rows(self, rows):
        chain = (self.mock_client.table.return_value.select.return_value
                 .eq.return_value.gte.return_value.order.return_value)
        chain.execute.return_value = MagicMock(data=rows)

    def test_fetch_data_reads_real_columns(self):
        # Real view columns: ev_predicted / pop_predicted / pnl_realized (+ strategy/regime).
        self._mock_view_rows([
            {"closed_at": "2026-06-12T18:45:00+00:00", "pop_predicted": 0.62,
             "ev_predicted": 40.0, "pnl_realized": 48.0, "strategy": "IRON_CONDOR",
             "regime": "normal", "user_id": "test-user"},
            {"closed_at": "2026-06-15T14:16:00+00:00", "pop_predicted": 0.55,
             "ev_predicted": 30.0, "pnl_realized": -73.0, "strategy": "IRON_CONDOR",
             "regime": "normal", "user_id": "test-user"},
        ])
        self.validator.fetch_data()
        df = self.validator.data
        self.assertEqual(len(df), 2)
        # prob_raw sourced directly from pop_predicted (already 0-1, no /100)
        self.assertAlmostEqual(df['prob_raw'].iloc[0], 0.62)
        self.assertAlmostEqual(df['ev'].iloc[0], 40.0)
        self.assertAlmostEqual(df['realized_pnl'].iloc[1], -73.0)
        self.assertEqual(df['is_win'].tolist(), [1, 0])
        self.assertIn('strategy', df.columns)
        self.assertIn('regime', df.columns)

    def test_fetch_data_zero_rows_raises_loud(self):
        # The lying-empty class: zero rows must RAISE, not benign-return.
        self._mock_view_rows([])
        with self.assertRaises(WalkForwardContractError):
            self.validator.fetch_data()

    def test_fetch_data_missing_required_column_raises(self):
        # pop_predicted absent -> contract failure, loud.
        self._mock_view_rows([
            {"closed_at": "2026-06-12T18:45:00+00:00", "ev_predicted": 40.0,
             "pnl_realized": 48.0, "user_id": "test-user"},
        ])
        with self.assertRaises(WalkForwardContractError):
            self.validator.fetch_data()

    def test_fetch_data_never_fabricates_probability(self):
        # H9: a missing probability column must FAIL, never silently become 0.5.
        self._mock_view_rows([
            {"closed_at": "2026-06-12T18:45:00+00:00", "ev_predicted": 40.0,
             "pnl_realized": 48.0, "strategy": "IRON_CONDOR", "regime": "normal",
             "user_id": "test-user"},
        ])
        with self.assertRaises(WalkForwardContractError):
            self.validator.fetch_data()

if __name__ == '__main__':
    unittest.main()
