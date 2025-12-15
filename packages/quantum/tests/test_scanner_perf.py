
import unittest
from unittest.mock import MagicMock, patch
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.analytics.regime_engine_v3 import GlobalRegimeSnapshot, RegimeState

class TestOptionsScanner(unittest.TestCase):

    @patch('packages.quantum.options_scanner.PolygonService')
    @patch('packages.quantum.options_scanner.StrategySelector')
    @patch('packages.quantum.options_scanner.RegimeEngineV3')
    @patch('packages.quantum.options_scanner.ExecutionService')
    @patch('packages.quantum.options_scanner.UniverseService')
    def test_scan_for_opportunities_parallel(self, mock_universe, mock_exec_service, mock_regime, mock_selector, mock_polygon):
        # Setup Mocks
        mock_poly_instance = mock_polygon.return_value
        mock_poly_instance.get_recent_quote.return_value = {"price": 100.0, "bid_price": 99.5, "ask_price": 100.5}
        mock_poly_instance.get_historical_prices.return_value = [{"close": 100}] * 60
        mock_poly_instance.get_option_chain.return_value = [{
            "ticker": "O:SYM123", "strike": 100, "expiration": "2023-12-01",
            "type": "call", "price": 2.0, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "theta": -0.1
        }]

        mock_regime_instance = mock_regime.return_value
        # Fixed constructor args to match actual definition (no regime_id)
        mock_regime_instance.compute_global_snapshot.return_value = GlobalRegimeSnapshot(
            as_of_ts="2023-01-01",
            state=RegimeState.NORMAL,
            risk_score=50.0,
            risk_scaler=1.0,
            trend_score=0.0,
            vol_score=0.0,
            corr_score=0.0,
            breadth_score=0.0,
            liquidity_score=0.0
        )
        mock_regime_instance.compute_symbol_snapshot.return_value = MagicMock(iv_rank=50)
        mock_regime_instance.get_effective_regime.return_value = RegimeState.NORMAL

        mock_selector_instance = mock_selector.return_value
        mock_selector_instance.determine_strategy.return_value = {
            "strategy": "LONG_CALL",
            "legs": [{"delta_target": 0.5, "side": "buy", "type": "call"}]
        }

        mock_exec_instance = mock_exec_service.return_value
        mock_exec_instance.get_batch_execution_drag_stats.return_value = {
            "AAPL": {"avg_drag": 0.05, "n": 10}
        }

        # Test
        candidates = scan_for_opportunities(symbols=["AAPL"], user_id="test_user")

        # Verify
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['symbol'], "AAPL")
        # Should be proxy because scan_for_opportunities called without supabase_client -> execution_service is None
        self.assertEqual(candidates[0]['execution_drag_source'], "proxy")

    @patch('packages.quantum.options_scanner.PolygonService')
    @patch('packages.quantum.options_scanner.StrategySelector')
    @patch('packages.quantum.options_scanner.RegimeEngineV3')
    @patch('packages.quantum.options_scanner.ExecutionService')
    def test_scan_with_client(self, mock_exec_service, mock_regime, mock_selector, mock_polygon):
        # This time with client so execution service is active
        mock_client = MagicMock()

        mock_poly_instance = mock_polygon.return_value
        mock_poly_instance.get_recent_quote.return_value = {"price": 100.0, "bid_price": 99.5, "ask_price": 100.5}
        mock_poly_instance.get_historical_prices.return_value = [{"close": 100}] * 60
        mock_poly_instance.get_option_chain.return_value = [{
            "ticker": "O:SYM123", "strike": 100, "expiration": "2023-12-01",
            "type": "call", "price": 2.0, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "theta": -0.1
        }]

        mock_regime_instance = mock_regime.return_value
        mock_regime_instance.compute_global_snapshot.return_value = GlobalRegimeSnapshot(
            as_of_ts="2023-01-01",
            state=RegimeState.NORMAL,
            risk_score=50.0,
            risk_scaler=1.0,
            trend_score=0.0,
            vol_score=0.0,
            corr_score=0.0,
            breadth_score=0.0,
            liquidity_score=0.0
        )
        mock_regime_instance.compute_symbol_snapshot.return_value = MagicMock(iv_rank=50)
        mock_regime_instance.get_effective_regime.return_value = RegimeState.NORMAL

        mock_selector_instance = mock_selector.return_value
        mock_selector_instance.determine_strategy.return_value = {
            "strategy": "LONG_CALL",
            "legs": [{"delta_target": 0.5, "side": "buy", "type": "call"}]
        }

        mock_exec_instance = mock_exec_service.return_value
        mock_exec_instance.get_batch_execution_drag_stats.return_value = {
            "AAPL": {"avg_drag": 0.05, "n": 10}
        }

        candidates = scan_for_opportunities(symbols=["AAPL"], supabase_client=mock_client, user_id="test_user")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['execution_drag_source'], "history")
        self.assertEqual(candidates[0]['execution_drag_estimate'], 0.05)

    @patch('packages.quantum.options_scanner.PolygonService')
    @patch('packages.quantum.options_scanner.StrategySelector')
    @patch('packages.quantum.options_scanner.RegimeEngineV3')
    @patch('packages.quantum.options_scanner.ExecutionService')
    @patch('packages.quantum.options_scanner.calculate_ev')
    @patch('packages.quantum.options_scanner.calculate_unified_score')
    def test_scan_no_requery_on_missing_stats(self, mock_unified_score, mock_calc_ev, mock_exec_service, mock_regime, mock_selector, mock_polygon):
        # Scenario: Batch stats missing for symbol.
        # Goal: Verify we fall back to proxy WITHOUT requerying history (user_id=None).

        mock_client = MagicMock()

        # Mock Polygon
        mock_poly_instance = mock_polygon.return_value
        mock_poly_instance.get_recent_quote.return_value = {"price": 100.0, "bid_price": 99.5, "ask_price": 100.5}
        mock_poly_instance.get_historical_prices.return_value = [{"close": 100}] * 60
        mock_poly_instance.get_option_chain.return_value = [{
            "ticker": "O:SYM123", "strike": 100, "expiration": "2023-12-01",
            "type": "call", "price": 2.0, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "theta": -0.1
        }]

        # Mock Regime
        mock_regime_instance = mock_regime.return_value
        mock_regime_instance.compute_global_snapshot.return_value = GlobalRegimeSnapshot(
            as_of_ts="2023-01-01",
            state=RegimeState.NORMAL,
            risk_score=50.0,
            risk_scaler=1.0,
            trend_score=0.0,
            vol_score=0.0,
            corr_score=0.0,
            breadth_score=0.0,
            liquidity_score=0.0
        )
        mock_regime_instance.compute_symbol_snapshot.return_value = MagicMock(iv_rank=50)
        mock_regime_instance.get_effective_regime.return_value = RegimeState.NORMAL

        # Mock Strategy
        mock_selector_instance = mock_selector.return_value
        mock_selector_instance.determine_strategy.return_value = {
            "strategy": "LONG_CALL",
            "legs": [{"delta_target": 0.5, "side": "buy", "type": "call"}]
        }

        # Mock Execution Service
        mock_exec_instance = mock_exec_service.return_value
        # 1. Batch fetch returns EMPTY dict (missing stats)
        mock_exec_instance.get_batch_execution_drag_stats.return_value = {}
        # 2. Fallback estimate call returns a dummy value
        mock_exec_instance.estimate_execution_cost.return_value = 1.23

        # Mock EV (ensure high enough EV to pass filter)
        mock_ev_obj = MagicMock()
        mock_ev_obj.expected_value = 10.0
        mock_calc_ev.return_value = mock_ev_obj

        # Mock Scoring
        mock_score_obj = MagicMock()
        mock_score_obj.score = 80.0
        mock_score_obj.execution_cost_dollars = 1.23
        mock_score_obj.components = MagicMock()
        mock_score_obj.components.dict.return_value = {}
        mock_score_obj.badges = []
        mock_unified_score.return_value = mock_score_obj

        # Action: Run Scan
        results = scan_for_opportunities(symbols=["AAPL"], supabase_client=mock_client, user_id="test_user")

        # Assertions
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["execution_drag_source"], "proxy")
        self.assertEqual(results[0]["execution_drag_estimate"], 1.23)

        # 1. Verify batch fetch called exactly once
        mock_exec_instance.get_batch_execution_drag_stats.assert_called_once()

        # 2. Verify estimate_execution_cost called exactly once
        # AND crucially, verify user_id was PASSED AS NONE to prevent requery
        mock_exec_instance.estimate_execution_cost.assert_called_once()
        call_args = mock_exec_instance.estimate_execution_cost.call_args
        self.assertIsNone(call_args.kwargs.get('user_id'), "user_id should be None to prevent extra DB query")
