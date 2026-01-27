import unittest
from unittest.mock import MagicMock, patch
import sys
# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.services.go_live_validation_service import GoLiveValidationService, chicago_day_window_utc
from datetime import datetime, timezone, timedelta


class TestChicagoDayWindow(unittest.TestCase):
    """Unit tests for DST-safe Chicago day window computation."""

    def test_chicago_window_cst_winter(self):
        """Test Chicago window during CST (winter, UTC-6)."""
        # January 15, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now_utc = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CST: Chicago midnight = 06:00 UTC
        expected_start = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 1, 16, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_cdt_summer(self):
        """Test Chicago window during CDT (summer, UTC-5)."""
        # July 15, 2024, 14:00 UTC (9:00 AM Chicago CDT)
        now_utc = datetime(2024, 7, 15, 14, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CDT: Chicago midnight = 05:00 UTC
        expected_start = datetime(2024, 7, 15, 5, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 7, 16, 5, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_dst_spring_forward(self):
        """Test Chicago window around DST spring forward (March 2024)."""
        # March 10, 2024 is DST spring forward day
        # At 2:00 AM Chicago, clocks spring forward to 3:00 AM
        # Before DST: CST (UTC-6), After DST: CDT (UTC-5)

        # March 11, 2024, 12:00 UTC (first full day after spring forward, 7:00 AM CDT)
        now_utc = datetime(2024, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CDT: Chicago midnight = 05:00 UTC
        expected_start = datetime(2024, 3, 11, 5, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 3, 12, 5, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_dst_fall_back(self):
        """Test Chicago window around DST fall back (November 2024)."""
        # November 3, 2024 is DST fall back day
        # At 2:00 AM Chicago, clocks fall back to 1:00 AM
        # Before DST: CDT (UTC-5), After DST: CST (UTC-6)

        # November 4, 2024, 12:00 UTC (first full day after fall back, 6:00 AM CST)
        now_utc = datetime(2024, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CST: Chicago midnight = 06:00 UTC
        expected_start = datetime(2024, 11, 4, 6, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 11, 5, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

class TestGoLiveHardening(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"
        self.service = GoLiveValidationService(self.mock_client)
        
        # Setup default mocks for pandas_market_calendars to assume TRADING DAY
        # This allows tests to proceed past the Holiday check unless specified otherwise
        self.mock_mcal = MagicMock()
        # Setup get_calendar('NYSE').schedule(...).empty = False
        mock_nyse = self.mock_mcal.get_calendar.return_value
        # schedule() returns a DataFrame-like object, checking .empty
        mock_nyse.schedule.return_value.empty = False
        
        self.mcal_patcher = patch.dict(sys.modules, {"pandas_market_calendars": self.mock_mcal})
        self.mcal_patcher.start()
        self.addCleanup(self.mcal_patcher.stop)

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

        # Create response objects
        def make_res(data):
            r = MagicMock()
            r.data = data
            return r

        # Generic recursive mock that returns self for any call until execute()
        def create_chain_mock(return_value):
            chain = MagicMock()
            # execute() returns the final result
            chain.execute.return_value = return_value
            # Any other attribute access returns the chain itself (builder pattern)
            # We use side_effect to return self for any method call
            def return_self(*args, **kwargs):
                return chain
            
            # We need to catch all common builder methods
            # Using __getattr__ on a MagicMock is tricky, so we just set commonly used ones
            for method in ['select', 'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in_', 'order', 'limit', 'single']:
                setattr(chain, method, MagicMock(side_effect=return_self))
            
            return chain

        # Mock for ingestion lag (empty by default to pass check)
        mock_orders_lag_res = make_res([])
        # Mock for autopilot (actual test data)
        mock_orders_autopilot_res = make_res(orders)

        # Restore missing mocks
        mock_state_res = make_res(state)
        mock_outcomes_res = make_res(outcomes)
        mock_positions_res = make_res(positions)
        mock_suggestions_res = make_res(suggestions)
        mock_orders_res = make_res(orders) # Fallback if needed, but we use specific ones above
        mock_portfolios_res = make_res([{"id": "port1"}])

        def table_mock(table_name):
            if table_name == "v3_go_live_state":
                return create_chain_mock(mock_state_res)
            elif table_name == "learning_trade_outcomes_v3":
                return create_chain_mock(mock_outcomes_res)
            elif table_name == "paper_positions":
                return create_chain_mock(mock_positions_res)
            elif table_name == "trade_suggestions":
                # Suggestions query needs to return suggestions
                # Logic: We might query suggestions twice? (Checking code...)
                # Code queries suggestions once in step D.
                return create_chain_mock(mock_suggestions_res)
            elif table_name == "paper_orders":
                # Called twice: 1. Ingestion Lag, 2. Autopilot
                # We return a NEW mock each time
                # We can't use side_effect on the return value of THIS function easily if we use it directly as side_effect of table()
                # Instead, let's make a stateful mock for this table or use side_effect on the result
                pass
            elif table_name == "v3_go_live_runs":
                chain = MagicMock()
                chain.insert.return_value.execute.return_value = MagicMock()
                return chain
            elif table_name == "paper_portfolios":
                return create_chain_mock(mock_portfolios_res)
            return MagicMock()

        # To handle sequential calls to .table("paper_orders"), we set the side_effect on the client.table mock itself?
        # But we act as the dispatcher.
        # Let's make table_mock stateful
        paper_orders_call_count = [0]
        
        def stateful_table_mock(table_name):
            if table_name == "paper_orders":
                count = paper_orders_call_count[0]
                paper_orders_call_count[0] += 1
                if count == 0:
                    # 1. Ingestion Lag Check -> Return Empty (No lag)
                    return create_chain_mock(mock_orders_lag_res)
                else:
                    # 2. Autopilot Check -> Return Actual Orders
                    return create_chain_mock(mock_orders_autopilot_res)
            
            # Delegate to static dispatcher for others
            return table_mock(table_name)

        self.mock_client.table = MagicMock(side_effect=stateful_table_mock)

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

    def test_skip_non_trading_day_unknown(self):
        """Task: Skip reset if holiday check fails (fail-open)."""
        self._mock_db_responses(outcomes=[])
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        # We'll mock the internal holiday check to raise/fail if possible, 
        # or just assume the implementation returns this status when dependencies missing.
        # Check if 'pandas_market_calendars' is in sys.modules, if not, we can simulate import error.
        # But easier to patch the class method if it's mocking the library.
        # But wait, the code imports it *inside* the function.
        # We can use patch.dict on sys.modules to effectively hide it
        with patch.dict(sys.modules, {"pandas_market_calendars": None}):
             # Note: If it was already imported, this might not work without reload, but new shell per test run helps?
             # No, using pytest, imports persist.
             # Alternatively, we patch the 'get_calendar' if we can import it in test
             # Let's try to pass a side_effect that raises Exception
             result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_non_trading_day_unknown")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_autopilot_inactive(self):
        """Task: Skip if suggestions exist but no LINKED orders created."""
        # Suggestions exist (pending)
        # No LINKED orders (simulate query returning empty)
        self._mock_db_responses(
            outcomes=[], 
            positions=[],
            suggestions=[{"id": "sugg1", "status": "pending"}],
            orders=[] # Query returns empty
        )
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_orders_exist_but_no_positions_or_outcomes(self):
        """Task: Skip if LINKED orders exist but no fills (ambiguous/no-fill)."""
        # Suggestions exist
        # Orders exist AND linked
        self._mock_db_responses(
            outcomes=[], 
            positions=[],
            suggestions=[{"id": "sugg1", "status": "pending"}],
            orders=[{"id": "ord1", "suggestion_id": "sugg1", "status": "new"}]
        )
        
        # Weekday
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
        
        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)
        
        self.assertEqual(result["status"], "skipped_no_fill_activity")
        self.assertEqual(result["paper_consecutive_passes"], 5)
