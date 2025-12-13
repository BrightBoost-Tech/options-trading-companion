import unittest
from unittest.mock import MagicMock, patch
import os
import numpy as np
from datetime import datetime
from packages.quantum.nested.backbone import infer_global_context, compute_macro_features
from packages.quantum.nested.session import update_session_state, get_session_sigma_scale, load_session_state, refresh_session_from_db, _SESSION_STORE

class TestNestedPhase3(unittest.TestCase):

    def setUp(self):
        # Clear session store
        _SESSION_STORE.clear()

    def test_l2_backbone_inference(self):
        # 1. Bear Case
        features_bear = {"spy_trend": "down", "vix_level": 25.0}
        ctx = infer_global_context(features_bear)
        self.assertEqual(ctx.global_regime, "bear")
        self.assertEqual(ctx.market_volatility_state, "medium")
        self.assertLess(ctx.global_risk_scaler, 1.0)

        # 2. Shock Case
        features_shock = {"spy_trend": "down", "vix_level": 35.0}
        ctx = infer_global_context(features_shock)
        self.assertEqual(ctx.global_regime, "shock")
        self.assertEqual(ctx.market_volatility_state, "high")
        self.assertEqual(ctx.global_risk_scaler, 0.6)

        # 3. Bull Case
        features_bull = {"spy_trend": "up", "vix_level": 15.0}
        ctx = infer_global_context(features_bull)
        self.assertEqual(ctx.global_regime, "bull")
        self.assertEqual(ctx.global_risk_scaler, 1.0)

    def test_l0_session_adapter(self):
        account_id = "acc_test_123"

        # Initial State
        state = load_session_state(account_id)
        self.assertEqual(state.confidence, 1.0)

        # Update with bad news (High Surprise)
        # avg surprise 3.0 -> > 2.0 -> penalty 0.2
        update_session_state(account_id, recent_surprises=[3.0, 3.0], recent_pnls=[10.0])
        state = load_session_state(account_id)
        self.assertAlmostEqual(state.confidence, 0.8)

        # Update again with SAME data (Idempotency check)
        update_session_state(account_id, recent_surprises=[3.0, 3.0], recent_pnls=[10.0])
        state = load_session_state(account_id)
        # Should stay 0.8, NOT decay further
        self.assertAlmostEqual(state.confidence, 0.8)

        # Check Sigma Scale
        # Confidence 0.8
        # Scale = 1.0 + (1-0.8)*0.625 = 1 + 0.2*0.625 = 1.125
        scale = get_session_sigma_scale(state.confidence)
        self.assertEqual(scale, 1.125)

        # Extreme bad case
        state.confidence = 0.2
        scale = get_session_sigma_scale(state.confidence)
        # 1 + 0.8 * 0.625 = 1.5
        self.assertEqual(scale, 1.5)

    def test_l0_recovery(self):
        account_id = "acc_recovery"
        state = load_session_state(account_id)
        state.confidence = 0.5

        # Good news (low surprise, pos pnl)
        update_session_state(account_id, recent_surprises=[0.5], recent_pnls=[100.0])
        state = load_session_state(account_id)
        self.assertGreater(state.confidence, 0.5)

    @patch("nested.session._get_supabase_client")
    def test_l0_db_refresh(self, mock_get_client):
        # Mock DB response
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock data: High surprise (3.0) and negative PnL (-50)
        # This should tank confidence
        mock_response = MagicMock()
        mock_response.data = [
            {"surprise_score": 3.0, "realized_pl_1d": -50.0},
            {"surprise_score": 2.5, "realized_pl_1d": -10.0}
        ]
        mock_client.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = mock_response

        account_id = "acc_db_test"

        # Initial: 1.0
        state = load_session_state(account_id)
        self.assertEqual(state.confidence, 1.0)

        # Refresh
        new_state = refresh_session_from_db(account_id)

        # Should be lower than 1.0 because of high surprise
        self.assertLess(new_state.confidence, 1.0)

        # Verify call args (ensure it queried correct table)
        mock_client.table.assert_called_with("outcomes_log")

if __name__ == '__main__':
    unittest.main()
