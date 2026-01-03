
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import uuid
from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.services.provider_guardrails import get_circuit_breaker, CircuitState

class TestOutcomesPolygonRateLimit(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_polygon = MagicMock()

        # Reset circuit breaker
        cb = get_circuit_breaker("polygon")
        cb.state = CircuitState.CLOSED
        cb.failures = 0
        cb.total_rate_limits = 0

        self.aggregator = OutcomeAggregator(self.mock_supabase, self.mock_polygon)
        self.valid_uuid = str(uuid.uuid4())
        self.valid_exec_id = str(uuid.uuid4())
        self.valid_sugg_id = str(uuid.uuid4())

    def test_partial_status_on_rate_limit(self):
        # 1. Setup Mock Decision & Execution
        decision = {"trace_id": self.valid_uuid, "decision_type": "morning_suggestion"}
        executions = [{"id": self.valid_exec_id, "symbol": "AAPL", "quantity": 10, "fill_price": 150}]

        # 2. Simulate Polygon Circuit Open (Rate Limited)
        cb = get_circuit_breaker("polygon")
        cb.state = CircuitState.OPEN # Forced OPEN

        # 3. Simulate missing Vol due to circuit open
        # _calculate_execution_pnl calls get_historical_prices which returns None (or mock returns None)
        self.mock_polygon.get_historical_prices.return_value = None

        # 4. Run Process (private method for direct test)
        # Mock fetchers to return our data
        with patch.object(self.aggregator, '_calculate_execution_pnl', return_value=(0.0, None)): # None vol triggers logic
            with patch('packages.quantum.services.outcome_aggregator.log_outcome') as mock_log:
                self.aggregator._process_single_outcome(
                    decision=decision,
                    inference_log=None,
                    suggestions=[],
                    executions=executions
                )

                # 5. Verify Outcome Log
                mock_log.assert_called_once()
                args = mock_log.call_args[1]

                self.assertEqual(args['status'], "PARTIAL")
                self.assertIn("provider_down", args['reason_codes'])

    def test_counterfactual_partial_on_missing_data(self):
        decision = {"trace_id": self.valid_uuid, "decision_type": "morning_suggestion"}
        suggestions = [{"id": self.valid_sugg_id, "ticker": "SPY", "created_at": datetime.now().isoformat()}]

        # Polygon returns None
        self.mock_polygon.get_historical_prices.return_value = None

        with patch('packages.quantum.services.outcome_aggregator.log_outcome') as mock_log:
            self.aggregator._process_single_outcome(
                decision=decision,
                inference_log=None,
                suggestions=suggestions,
                executions=[]
            )

            args = mock_log.call_args[1]
            self.assertEqual(args['status'], "PARTIAL")
            self.assertIn("missing_counterfactual", args['reason_codes'])

if __name__ == '__main__':
    unittest.main()
