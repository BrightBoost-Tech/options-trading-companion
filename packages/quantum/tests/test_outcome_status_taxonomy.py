import unittest
from unittest.mock import MagicMock, patch, ANY
from datetime import datetime
import uuid
from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.common_enums import OutcomeStatus

class TestOutcomeStatusTaxonomy(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_polygon = MagicMock()
        self.aggregator = OutcomeAggregator(self.mock_supabase, self.mock_polygon)

        # Mock fetch_decisions to return one decision
        self.trace_id = str(uuid.uuid4())
        self.decision = {
            "trace_id": self.trace_id,
            "decision_type": "morning_suggestion",
            "created_at": datetime.now().isoformat(),
            "content": {}
        }

        # Mock fetch_decisions
        self.aggregator._fetch_decisions = MagicMock(return_value=[self.decision])

        # Mock outcome_exists to False
        self.aggregator._outcome_exists = MagicMock(return_value=False)

        # Mock fetch_inference_log
        self.aggregator._fetch_inference_log = MagicMock(return_value={
            "inputs_snapshot": {"total_equity": 10000.0},
            "predicted_sigma": {"sigma_matrix": [[0.01]]}
        })

        # Setup log_outcome patch
        self.log_patcher = patch('packages.quantum.services.outcome_aggregator.log_outcome')
        self.mock_log = self.log_patcher.start()

    def tearDown(self):
        self.log_patcher.stop()

    async def test_complete_status(self):
        # Case: Execution exists with PnL and Vol
        self.aggregator._fetch_suggestions = MagicMock(return_value=[{"id": str(uuid.uuid4())}])

        # Mock executions returning valid PnL and Vol
        self.aggregator._fetch_executions = MagicMock(return_value=[{"id": str(uuid.uuid4()), "symbol": "AAPL", "quantity": 1, "fill_price": 100}])
        self.aggregator._calculate_execution_pnl = MagicMock(return_value=(100.0, 0.02)) # pnl, vol

        await self.aggregator.run(datetime.now(), datetime.now())

        # Check call arguments without **ANY because it causes TypeError in assert_called_with
        # We check specific args and then just assert called
        call_args = self.mock_log.call_args
        self.assertIsNotNone(call_args)
        kwargs = call_args.kwargs

        self.assertEqual(kwargs['status'], OutcomeStatus.COMPLETE.value)
        self.assertEqual(kwargs['attribution_type'], "execution")
        self.assertEqual(kwargs['realized_pl_1d'], 100.0)
        self.assertEqual(kwargs['realized_vol_1d'], 0.02)
        self.assertEqual(kwargs['reason_codes'], [])

    async def test_partial_status_missing_vol(self):
        # Case: Execution exists but Vol is None (missing underlying data)
        self.aggregator._fetch_suggestions = MagicMock(return_value=[{"id": str(uuid.uuid4())}])
        self.aggregator._fetch_executions = MagicMock(return_value=[{"id": str(uuid.uuid4())}])
        self.aggregator._calculate_execution_pnl = MagicMock(return_value=(100.0, None)) # pnl, vol=None

        await self.aggregator.run(datetime.now(), datetime.now())

        call_args = self.mock_log.call_args
        kwargs = call_args.kwargs

        self.assertEqual(kwargs['status'], OutcomeStatus.PARTIAL.value)
        self.assertEqual(kwargs['attribution_type'], "execution")
        self.assertEqual(kwargs['realized_pl_1d'], 100.0)
        self.assertEqual(kwargs['realized_vol_1d'], 0.0)
        self.assertEqual(kwargs['reason_codes'], ["missing_vol"])

    async def test_incomplete_status_missing_equity_snapshot(self):
        # Case: Optimizer simulation but missing equity snapshot
        self.decision["decision_type"] = "optimizer_weights"
        self.decision["content"] = {"target_weights": {"AAPL": 0.5}}

        # Mock inference log missing
        self.aggregator._fetch_inference_log = MagicMock(return_value=None)

        # Mock suggestions/executions empty
        self.aggregator._fetch_suggestions = MagicMock(return_value=[])
        self.aggregator._fetch_executions = MagicMock(return_value=[])

        # Mock portfolio snapshot fallback failing
        self.aggregator.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

        await self.aggregator.run(datetime.now(), datetime.now())

        call_args = self.mock_log.call_args
        kwargs = call_args.kwargs

        self.assertEqual(kwargs['status'], OutcomeStatus.INCOMPLETE.value)
        self.assertEqual(kwargs['attribution_type'], "incomplete_data")
        self.assertEqual(kwargs['reason_codes'], ["missing_equity_snapshot"])

    async def test_incomplete_status_no_action_missing_counterfactual(self):
        # Case: No action (suggestion ignored), but market data missing for counterfactual
        self.aggregator._fetch_suggestions = MagicMock(return_value=[{"id": str(uuid.uuid4())}])
        self.aggregator._fetch_executions = MagicMock(return_value=[])

        # Mock counterfactual calculation failing
        self.aggregator._calculate_counterfactual_pnl = MagicMock(return_value=(0.0, False))

        await self.aggregator.run(datetime.now(), datetime.now())

        call_args = self.mock_log.call_args
        kwargs = call_args.kwargs

        self.assertEqual(kwargs['status'], OutcomeStatus.INCOMPLETE.value)
        self.assertEqual(kwargs['attribution_type'], "no_action")
        self.assertEqual(kwargs['reason_codes'], ["counterfactual_missing", "missing_equity"])

if __name__ == '__main__':
    unittest.main()
