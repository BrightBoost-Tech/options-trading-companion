import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, date

# Add packages/quantum to path

# Mock dependencies before imports
sys.modules['supabase'] = MagicMock()
sys.modules['supabase.client'] = MagicMock()

# Mock dependencies that might require env vars or external connection
sys.modules['market_data'] = MagicMock()
sys.modules['market_data.PolygonService'] = MagicMock()

class TestRegimeIntegration(unittest.TestCase):
    def test_map_market_regime(self):
        from packages.quantum.analytics.regime_integration import map_market_regime

        # Test 1: Shock -> Panic
        self.assertEqual(map_market_regime({'state': 'shock'}), 'panic')

        # Test 2: High Vol -> High Vol
        self.assertEqual(map_market_regime({'state': 'normal', 'vol_annual': 0.25}), 'high_vol')
        self.assertEqual(map_market_regime({'state': 'bull', 'vol_annual': 0.21}), 'high_vol')

        # Test 3: Bear -> High Vol
        self.assertEqual(map_market_regime({'state': 'bear', 'vol_annual': 0.10}), 'high_vol')

        # Test 4: Normal
        self.assertEqual(map_market_regime({'state': 'bull', 'vol_annual': 0.10}), 'normal')
        self.assertEqual(map_market_regime({'state': 'crab', 'vol_annual': 0.10}), 'normal')
        self.assertEqual(map_market_regime({'state': 'normal', 'vol_annual': 0.19}), 'normal')

    def test_run_historical_scoring(self):
        from packages.quantum.analytics.regime_integration import run_historical_scoring

        # Mock engine and transform
        mock_engine = MagicMock()
        mock_engine.calculate_score.return_value = {'raw_score': 60.0}

        mock_transform = MagicMock()
        mock_transform.get_conviction.return_value = 0.75

        symbol_data = {"symbol": "SPY", "factors": {}}
        res = run_historical_scoring(
            symbol_data,
            "normal",
            scoring_engine=mock_engine,
            conviction_transform=mock_transform
        )

        self.assertEqual(res['raw_score'], 60.0)
        self.assertEqual(res['conviction'], 0.75)
        mock_engine.calculate_score.assert_called_with(symbol_data, "normal")


class TestProgressEngine(unittest.TestCase):
    def test_week_id_helper(self):
        from packages.quantum.analytics.progress_engine import get_week_id_for_last_full_week

        d = date(2023, 10, 30) # Monday
        wid = get_week_id_for_last_full_week(d)
        self.assertEqual(wid, "2023-W43")

        d = date(2023, 10, 29) # Sunday
        wid = get_week_id_for_last_full_week(d)
        self.assertEqual(wid, "2023-W42")

class TestLossMinimizer(unittest.TestCase):
    def test_loss_analysis(self):
        from packages.quantum.analytics.loss_minimizer import LossMinimizer

        # Scenario 1: Scrap Value
        # Position: 10 contracts at $2.00 (Current) = $2000 value
        pos = {"quantity": 10, "current_price": 2.00}
        res = LossMinimizer.analyze_position(pos, user_threshold=100.0)
        self.assertIn("Scenario A", res.scenario)
        self.assertIn("LIMIT SELL", res.recommendation)

        # Scenario 2: Lottery Ticket
        # Position: 1 contract at $0.05 = $5 value
        pos_small = {"quantity": 1, "current_price": 0.05}
        res_small = LossMinimizer.analyze_position(pos_small, user_threshold=100.0)
        self.assertIn("Scenario B", res_small.scenario)
        self.assertIn("GTC", res_small.recommendation)

        # Test Default Threshold (should read env var or default 100)
        # 10 contracts at $0.09 = $90 value (< 100)
        pos_default = {"quantity": 10, "current_price": 0.09}
        res_default = LossMinimizer.analyze_position(pos_default) # No threshold arg
        self.assertIn("Scenario B", res_default.scenario)


class TestHistoricalCycleService(unittest.TestCase):
    @patch('packages.quantum.services.historical_simulation.PolygonService')
    def test_run_cycle_no_data(self, MockPolygon):
        # Explicit import inside test to avoid early resolution issues
        import services.historical_simulation as hs
        HistoricalCycleService = hs.HistoricalCycleService

        # Mock empty data
        mock_poly = MockPolygon.return_value
        mock_poly.get_historical_prices.return_value = {"dates": [], "prices": []}

        service = HistoricalCycleService(mock_poly)
        result = service.run_cycle("2023-01-01")

        self.assertTrue(result['done'])
        self.assertEqual(result['status'], "no_data")

    @patch('packages.quantum.services.historical_simulation.PolygonService')
    @patch('packages.quantum.services.historical_simulation.calculate_trend')
    @patch('packages.quantum.services.historical_simulation.calculate_volatility')
    @patch('packages.quantum.services.historical_simulation.calculate_rsi')
    @patch('packages.quantum.services.historical_simulation.infer_global_context')
    @patch('packages.quantum.services.historical_simulation.map_market_regime')
    @patch('packages.quantum.services.historical_simulation.run_historical_scoring')
    def test_run_cycle_happy_path(self, mock_scoring, mock_map, mock_ctx, mock_rsi, mock_vol, mock_trend, MockPolygon):
        import services.historical_simulation as hs
        HistoricalCycleService = hs.HistoricalCycleService

        # Setup mocks for one step iteration
        mock_poly = MockPolygon.return_value
        dates = ["2023-01-01", "2023-01-02", "2023-01-03"] * 30 # Ensure enough data length > lookback
        prices = [100.0 + i for i in range(len(dates))]
        mock_poly.get_historical_prices.return_value = {"dates": dates, "prices": prices}

        mock_trend.return_value = "UP"
        mock_vol.return_value = 0.10
        mock_rsi.return_value = 50

        mock_ctx_obj = MagicMock()
        mock_ctx_obj.global_regime = "bull"
        mock_ctx.return_value = mock_ctx_obj

        mock_map.return_value = "normal"

        # Mock Scoring to return High Conviction -> Trigger Entry
        # Then later low conviction?
        # For simplicity, we just want to ensure it runs without crashing and processes logic.
        mock_scoring.return_value = {"conviction": 0.8} # High conviction entry

        service = HistoricalCycleService(mock_poly)
        service.lookback_window = 1 # Shorten for test

        # Run
        # We start at date[0].
        # Logic finds start index.
        # Loop runs.
        # First iteration: Conviction 0.8 -> Entry.
        # Next iteration: We need to mock conviction dropping to exit.

        # Side effect for scoring: first call 0.8 (entry), second call 0.4 (exit)
        mock_scoring.side_effect = [{"conviction": 0.8}, {"conviction": 0.4}, {"conviction": 0.4}]

        result = service.run_cycle("2023-01-01")

        # It should have entered and exited
        self.assertFalse(result['done']) # Because it returns "done=False" on normal_exit
        self.assertEqual(result['status'], "normal_exit")
        # Start index logic might skip first element if date match is >= start_date.
        # With mocked dates matching exactly, start_idx should be found.
        # But maybe start_idx < lookback_window logic pushed it forward?
        # self.lookback_window = 1.
        # If start_idx found at 0. < lookback(1). Set to 1.
        # So entry is at index 1 -> price 101.0.
        self.assertEqual(result['entryPrice'], 101.0)
        self.assertTrue(result['pnl'] is not None)

if __name__ == '__main__':
    unittest.main()
