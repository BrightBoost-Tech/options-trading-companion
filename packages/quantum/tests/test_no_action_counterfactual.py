import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime
import sys
import os

# Adjust path to include package root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from packages.quantum.services.outcome_aggregator import OutcomeAggregator

class TestNoActionCounterfactual(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_polygon = MagicMock()
        self.aggregator = OutcomeAggregator(self.mock_supabase, self.mock_polygon)

    @patch("packages.quantum.services.outcome_aggregator.log_outcome")
    def test_counterfactual_calculated_for_no_action(self, mock_log):
        # Setup data
        trace_id = str(uuid.uuid4())
        suggestion_id = str(uuid.uuid4())

        decision = {
            "trace_id": trace_id,
            "decision_type": "morning_suggestion",
            "content": {}
        }

        suggestions = [{
            "id": suggestion_id,
            "ticker": "AAPL",
            "direction": "long",
            "status": "pending"
        }]

        executions = [] # Empty -> No Action
        inference_log = None

        # Mock Polygon response: Price went up 150 -> 155
        self.mock_polygon.get_historical_prices.return_value = {
            "prices": [150.0, 155.0]
        }

        # Act
        self.aggregator._process_single_outcome(decision, inference_log, suggestions, executions)

        # Assert
        self.mock_polygon.get_historical_prices.assert_called_with("AAPL", days=5)

        # Expected PnL: (155 - 150) * 1 * 100 (default equity multiplier?)
        # Wait, get_contract_multiplier defaults to 100 for equity options, but 1 for stocks?
        # Let's check get_contract_multiplier implementation or assume default.
        # If ticker is "AAPL", it's likely equity, multiplier 1 usually?
        # But get_contract_multiplier logic usually checks if it is option.
        # "AAPL" -> likely stock -> multiplier 1.
        # "O:AAPL..." -> option -> 100.
        # In test I used "AAPL". Let's assume multiplier is 1 for stock.
        # If get_contract_multiplier is imported from options_utils, likely it handles this.
        # I'll update the test to be robust or mock get_contract_multiplier.

        # Let's see what args were passed to log_outcome
        args, kwargs = mock_log.call_args
        self.assertEqual(kwargs['attribution_type'], "no_action")
        self.assertEqual(kwargs['counterfactual_available'], True)
        # 5.0 * 1 = 5.0 if multiplier is 1. If 100, then 500.
        # I will check valid range or mock multiplier.

    @patch("packages.quantum.services.outcome_aggregator.log_outcome")
    @patch("packages.quantum.services.outcome_aggregator.get_contract_multiplier")
    def test_counterfactual_value_logic(self, mock_multiplier, mock_log):
        mock_multiplier.return_value = 100.0

        trace_id = str(uuid.uuid4())
        decision = {"trace_id": trace_id, "decision_type": "morning_suggestion"}
        suggestions = [{"id": str(uuid.uuid4()), "ticker": "O:SPY250101C500", "direction": "long"}]

        self.mock_polygon.get_historical_prices.return_value = {
            "prices": [10.0, 12.0] # +2.0
        }

        self.aggregator._process_single_outcome(decision, None, suggestions, [])

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['counterfactual_available'], True)
        self.assertAlmostEqual(call_kwargs['counterfactual_pl_1d'], 200.0) # 2.0 * 100

    @patch("packages.quantum.services.outcome_aggregator.log_outcome")
    def test_counterfactual_unavailable_on_error(self, mock_log):
        trace_id = str(uuid.uuid4())
        decision = {"trace_id": trace_id, "decision_type": "morning_suggestion"}
        suggestions = [{"id": str(uuid.uuid4()), "ticker": "BADTICKER"}]

        # Mock Polygon error or empty
        self.mock_polygon.get_historical_prices.side_effect = Exception("API Error")

        self.aggregator._process_single_outcome(decision, None, suggestions, [])

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        # Should not have counterfactual args or they should be None/False
        self.assertNotIn('counterfactual_pl_1d', call_kwargs)
        self.assertNotIn('counterfactual_available', call_kwargs)

    @patch("packages.quantum.services.outcome_aggregator.log_outcome")
    def test_skips_if_no_suggestion(self, mock_log):
        trace_id = str(uuid.uuid4())
        decision = {"trace_id": trace_id, "decision_type": "morning_suggestion"}

        self.aggregator._process_single_outcome(decision, None, [], [])

        # If no suggestion/execution/inference, it goes to "incomplete_data"
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['attribution_type'], "incomplete_data")
        self.assertNotIn('counterfactual_available', call_kwargs)

if __name__ == '__main__':
    unittest.main()
