import unittest
from unittest.mock import MagicMock, patch, ANY
import uuid
from datetime import datetime
import asyncio
import sys
import os

# Add package root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.nested_logging import log_decision, log_outcome

class TestOutcomeLinking(unittest.TestCase):

    def test_log_decision_returns_stable_id(self):
        """Verify log_decision returns the trace_id passed to it."""
        trace_id = uuid.uuid4()
        with patch('packages.quantum.nested_logging._get_supabase_client') as mock_client:
            returned_id = log_decision(trace_id, "user1", "test_type", {})
            self.assertEqual(returned_id, trace_id)

    @patch('packages.quantum.services.outcome_aggregator.log_outcome')
    def test_morning_suggestion_linking(self, mock_log_outcome):
        """
        Verify that OutcomeAggregator picks up a 'morning_suggestion'
        (which has NO inference log) and correctly links it.
        """
        # Mock dependencies
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()

        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        # Setup Data
        trace_id = str(uuid.uuid4())
        suggestion_id = str(uuid.uuid4())

        # 1. Mock _fetch_decisions to return a morning decision
        mock_supabase.table.return_value.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [{
            "trace_id": trace_id,
            "decision_type": "morning_suggestion",
            "content": {},
            "created_at": datetime.now().isoformat()
        }]

        # 2. Mock _outcome_exists -> False
        # (Need to carefully mock the chain: table().select().eq().execute().data)
        # We'll rely on side_effects or specific call args matching if needed,
        # but simple return_value setting on the chain helps.

        # To handle multiple table calls, we need a side_effect on table(name)
        def table_side_effect(name):
            query = MagicMock()
            if name == "decision_logs":
                # Already mocked above for the first call, but let's be robust
                query.select.return_value.in_.return_value.gte.return_value.lte.return_value.execute.return_value.data = [{
                    "trace_id": trace_id,
                    "decision_type": "morning_suggestion",
                    "content": {},
                    "created_at": datetime.now().isoformat()
                }]
            elif name == "outcomes_log":
                # Return empty to simulate "not processed yet"
                query.select.return_value.eq.return_value.execute.return_value.data = []
            elif name == "inference_log":
                # Return empty to simulate "Morning Cycle" (no inference log)
                query.select.return_value.eq.return_value.execute.return_value.data = []
            elif name == "trade_suggestions":
                # Return the linked suggestion
                query.select.return_value.eq.return_value.execute.return_value.data = [{
                    "id": suggestion_id,
                    "status": "pending",
                    "ticker": "SPY"
                }]
            elif name == "trade_executions":
                # Return empty execution (so it falls to Priority 2: Suggestion/No Action)
                query.select.return_value.in_.return_value.execute.return_value.data = []

            return query

        mock_supabase.table.side_effect = table_side_effect

        # Run
        start = datetime.now()
        end = datetime.now()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(aggregator.run(start, end))
        loop.close()

        # Assert
        # Check that log_outcome was called with attribution_type='no_action' and correct IDs
        mock_log_outcome.assert_called_once()
        call_kwargs = mock_log_outcome.call_args.kwargs

        self.assertEqual(str(call_kwargs['trace_id']), trace_id)
        self.assertEqual(call_kwargs['attribution_type'], "no_action")
        self.assertEqual(str(call_kwargs['related_id']), suggestion_id)
        # Surprise should be 0.0 because no inference log
        self.assertEqual(call_kwargs['surprise_score'], 0.0)

if __name__ == '__main__':
    unittest.main()
