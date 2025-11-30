import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import json
from optimizer import optimize_portfolio, OptimizationRequest, PositionInput

class TestOptimizerIntegration(unittest.IsolatedAsyncioTestCase):

    @patch("optimizer.PolygonService")
    @patch("optimizer.calculate_portfolio_inputs")
    @patch("optimizer.load_symbol_adapters")
    @patch("optimizer.apply_biases")
    @patch("optimizer.log_global_context")
    @patch("optimizer.compute_macro_features")
    @patch("optimizer.infer_global_context")
    @patch("optimizer.refresh_session_from_db")
    @patch("optimizer.get_current_user_id")
    async def test_nested_integration(self,
                                      mock_get_user,
                                      mock_refresh_session,
                                      mock_infer_context,
                                      mock_compute_macro,
                                      mock_log_context,
                                      mock_apply_biases,
                                      mock_load_adapters,
                                      mock_calculate_inputs,
                                      mock_polygon_service):

        # Setup Mocks
        import numpy as np

        # Mock calculate_portfolio_inputs to return fake mu/sigma
        mock_calculate_inputs.return_value = {
            'expected_returns': [0.05],
            'covariance_matrix': [[0.01]],
            'symbols': ['AAPL'],
            'data_points': 100,
            'is_mock': True
        }
        mock_get_user.return_value = "test_user_int"

        # L2 Mocks
        mock_compute_macro.return_value = {"spy_trend": "up"}
        mock_context_obj = MagicMock()
        mock_context_obj.global_regime = "bull"
        mock_context_obj.global_risk_scaler = 1.0 # Neutral
        mock_context_obj.market_volatility_state = "low"
        # asdict behavior
        from dataclasses import asdict
        # We can't easily mock asdict unless we return a real dataclass or mock asdict
        # The code calls asdict(global_ctx). Let's return a real dataclass if possible
        # Or just ensure global_ctx is compatible.
        from nested.backbone import GlobalContext
        mock_infer_context.return_value = GlobalContext("bull", "low", 1.0)

        # L0 Mocks
        mock_session_state = MagicMock()
        mock_session_state.confidence = 1.0
        mock_refresh_session.return_value = mock_session_state

        # Polygon Service Mock for market data inside optimizer
        service_instance = mock_polygon_service.return_value
        service_instance.get_historical_prices.return_value = {'prices': [100.0, 101.0]}
        service_instance.get_recent_quote.return_value = {'bid': 100.0, 'ask': 101.0}
        service_instance.get_iv_rank.return_value = 50.0
        service_instance.get_trend.return_value = "UP"

        # Request
        req = OptimizationRequest(
            positions=[
                PositionInput(symbol="AAPL", current_value=5000, current_quantity=50, current_price=100)
            ],
            risk_aversion=1.0,
            profile="balanced"
        )

        # 1. Test with ALL FLAGS OFF
        with patch.dict(os.environ, {"NESTED_L2_ENABLED": "False", "NESTED_L0_ENABLED": "False"}):
            res = await optimize_portfolio(req, user_id="test_user_int")
            # Verify L2/L0 logic NOT called
            mock_compute_macro.assert_not_called()
            mock_refresh_session.assert_not_called()
            # Verify basic structure
            self.assertEqual(res["status"], "success")

        # 2. Test with L2 ENABLED (Neutral)
        mock_compute_macro.reset_mock()
        with patch.dict(os.environ, {"NESTED_L2_ENABLED": "True", "NESTED_L0_ENABLED": "False"}):
            res = await optimize_portfolio(req, user_id="test_user_int")
            mock_compute_macro.assert_called_once()
            # Check diagnostics
            self.assertIn("diagnostics", res)
            self.assertIn("l2", res["diagnostics"]["nested"])
            self.assertEqual(res["diagnostics"]["nested"]["l2"]["global_regime"], "bull")

        # 3. Test with L2 ENABLED (Crisis/Shock)
        mock_compute_macro.reset_mock()
        mock_infer_context.return_value = GlobalContext("shock", "high", 0.6) # Shock!

        with patch.dict(os.environ, {"NESTED_L2_ENABLED": "True", "NESTED_L0_ENABLED": "False"}):
            req.profile = "balanced" # Reset
            res = await optimize_portfolio(req, user_id="test_user_int")
            # Should force conservative
            # Note: optimizer modifies req.profile in place? No, req is pydantic.
            # But the response "profile" field should reflect it if passed through.
            # Actually optimizer returns `profile: req.profile`.
            # Check response
            self.assertEqual(res["profile"], "conservative")
            self.assertEqual(res["diagnostics"]["nested"]["crisis_mode_triggered_by"], "l2_shock")

        # 4. Test with L0 ENABLED (Low Confidence)
        mock_infer_context.return_value = GlobalContext("bull", "low", 1.0) # Reset L2
        mock_session_state.confidence = 0.3 # Low confidence

        with patch.dict(os.environ, {"NESTED_L2_ENABLED": "False", "NESTED_L0_ENABLED": "True"}):
            req.profile = "balanced" # Reset
            res = await optimize_portfolio(req, user_id="test_user_int")
            mock_refresh_session.assert_called()
            self.assertEqual(res["profile"], "conservative")
            self.assertEqual(res["diagnostics"]["nested"]["crisis_mode_triggered_by"], "l0_low_confidence")

if __name__ == '__main__':
    unittest.main()
