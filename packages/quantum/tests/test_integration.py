import unittest
from unittest.mock import patch, MagicMock
import uuid
import sys
import os
import json
import numpy as np

# Ensure we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.optimizer import optimize_portfolio, OptimizationRequest, PositionInput
from packages.quantum.nested_logging import log_inference

class TestIntegration(unittest.IsolatedAsyncioTestCase):

    @patch('packages.quantum.optimizer.log_inference')
    @patch('packages.quantum.optimizer.PolygonService')
    @patch('packages.quantum.optimizer.calculate_portfolio_inputs')
    async def test_optimize_calls_logging(self, mock_calc_inputs, mock_poly_service, mock_log):
        # Setup Mocks
        mock_calc_inputs.return_value = {
            'expected_returns': [0.01, 0.02],
            'covariance_matrix': [[0.01, 0.0], [0.0, 0.02]]
        }

        mock_poly = MagicMock()
        mock_poly_service.return_value = mock_poly
        # Mock market data calls
        mock_poly.get_historical_prices.return_value = {'prices': [100.0, 101.0]}
        mock_poly.get_recent_quote.return_value = {'bid': 100.0, 'ask': 101.0}
        mock_poly.get_iv_rank.return_value = 50.0
        mock_poly.get_trend.return_value = "Bullish"
        mock_poly.get_ticker_details.return_value = {}

        mock_log.return_value = uuid.uuid4()

        # Prepare Request
        req = OptimizationRequest(
            positions=[
                PositionInput(symbol="AAPL", current_value=1000.0, current_quantity=10, current_price=100.0),
                PositionInput(symbol="GOOG", current_value=1000.0, current_quantity=10, current_price=100.0)
            ],
            risk_aversion=2.0,
            skew_preference=0.0,
            cash_balance=500.0,
            profile="balanced"
        )

        # Execute
        result = await optimize_portfolio(req)

        # Assertions
        self.assertEqual(result["status"], "success")

        # Verify Log Inference was called
        mock_log.assert_called_once()

        # Check args passed to logging
        args, kwargs = mock_log.call_args

        # Args are passed as keywords in optimizer.py
        # log_inference(symbol_universe=..., ...)
        call_kwargs = kwargs

        self.assertEqual(set(call_kwargs['symbol_universe']), {"AAPL", "GOOG"})
        self.assertEqual(call_kwargs['optimizer_profile'], "balanced")
        self.assertIn("sigma_matrix", call_kwargs['predicted_sigma'])
        self.assertIn("positions_count", call_kwargs['inputs_snapshot'])

    def test_outcome_script_import(self):
        # Basic smoke test to ensure script is importable and has main function
        from packages.quantum.scripts import update_outcomes
        self.assertTrue(hasattr(update_outcomes, 'update_outcomes'))

if __name__ == '__main__':
    unittest.main()
