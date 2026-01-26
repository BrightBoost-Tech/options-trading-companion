import unittest
from unittest.mock import MagicMock, patch
import sys
# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.services.go_live_validation_service import GoLiveValidationService
from datetime import datetime, timezone, timedelta

class TestGoLiveHardening(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"
        self.service = GoLiveValidationService(self.mock_client)
        
        # Default passing state
        self.default_state = {
            "user_id": self.user_id,
            "paper_window_start": "2024-01-01T00:00:00+00:00",
            "paper_window_end": "2024-01-22T00:00:00+00:00",
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 5,
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
        }

    def _mock_db_responses(self, state=None, outcomes=None, positions=None, suggestions=None, orders=None):
        """Helper to mock DB call chains"""
        if state is None: state = self.default_state
        if outcomes is None: outcomes = []
        if positions is None: positions = []
        if suggestions is None: suggestions = []
        if orders is None: orders = []

        mock_state_res = MagicMock()
        mock_state_res.data = state

        mock_outcomes_res = MagicMock()
        mock_outcomes_res.data = outcomes
        
        mock_positions_res = MagicMock()
        mock_positions_res.data = positions
        
        # We need to mock different table calls
        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_res
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_res
            elif table_name == "paper_positions":
                 # Mock query: select("id").eq("user_id", user_id).neq("quantity", 0).limit(1).execute()
                 pos_res = MagicMock()
                 pos_res.data = positions
                 # Setup chain: select -> eq -> neq -> limit -> execute
                 # Or shorter variants if code uses them differently
                 mock.select.return_value.eq.return_value.neq.return_value.limit.return_value.execute.return_value = pos_res
            elif table_name == "trade_suggestions":
                 # Mock query: select("id").eq...gte...eq("status", "pending").limit(1).execute()
                 sugg_res = MagicMock()
                 sugg_res.data = suggestions
                 # The chain is long and variable. Let's make a generous chain mock
                 # Code: .select().eq().gte().eq().limit().execute()
                 mock.select.return_value.eq.return_value.gte.return_value.eq.return_value.limit.return_value.execute.return_value = sugg_res
            elif table_name == "paper_orders":
                 # Mock query: .select().in_().gte().limit().execute()
                 ord_res = MagicMock()
                 ord_res.data = orders
                 mock.select.return_value.in_.return_value.gte.return_value.limit.return_value.execute.return_value = ord_res
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            elif table_name == "paper_portfolios":
                 # Mock for ingestion lag check needing portfolio id
                 port_res = MagicMock()
                 port_res.data = [{"id": "port1"}]
                 mock.select.return_value.eq.return_value.execute.return_value = port_res
            return mock

        self.mock_client.table = table_mock

    def test_skip_non_trading_day_weekend(self):
        """Task: Skip reset on weekends."""
        self._mock_db_responses(outcomes=[])
        
        # Saturday
        now = datetime(2024, 1, 20, 14, 0, 0, tzinfo=timezone.utc)
        
        # We assume implementation will use naive weekend check first
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        # Until implemented, this might fail (currently would return 'miss')
        self.assertEqual(result["status"], "skipped_non_trading_day")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_open_positions(self):
        """Task: Skip reset if open positions exist."""
        # No outcomes, but 1 open position
        self._mock_db_responses(outcomes=[], positions=[{"id": "pos1", "quantity": 1}])
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        self.assertEqual(result["status"], "skipped_no_close_activity")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_no_suggestions(self):
        """Task: Skip reset if no suggestions today."""
        # No outcomes, no positions, no suggestions
        self._mock_db_responses(outcomes=[], positions=[], suggestions=[])
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_autopilot_inactive(self):
        """Task: Skip reset if suggestions exist but autopilot didn't execute (no orders)."""
        # No outcomes, no positions
        # Suggestions exist (pending)
        # No orders created today
        self._mock_db_responses(
            outcomes=[], 
            positions=[],
            suggestions=[{"id": "sugg1", "status": "pending"}],
            orders=[]
        )
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        self.assertEqual(result["status"], "skipped_no_signal_day")
        # Optional: check reason but status is main contract
        self.assertEqual(result["paper_consecutive_passes"], 5)
