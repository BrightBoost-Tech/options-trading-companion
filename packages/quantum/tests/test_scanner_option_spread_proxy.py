import unittest
from unittest.mock import MagicMock, patch
import os

# Set Env for test
os.environ["APP_ENV"] = "test"

from packages.quantum.options_scanner import _combo_width_share_from_legs, scan_for_opportunities

class TestScannerOptionSpreadProxy(unittest.TestCase):

    def test_combo_width_share_from_legs(self):
        # Setup mock truth layer
        mock_truth = MagicMock()

        # Scenario: 2 legs
        legs = [
            {"symbol": "AAPL230616C00150000"},
            {"symbol": "AAPL230616C00160000"}
        ]

        # Mock snapshot_many return
        mock_truth.normalize_symbol.side_effect = lambda x: "O:" + x

        mock_truth.snapshot_many.return_value = {
            "O:AAPL230616C00150000": {
                "quote": {"bid": 1.00, "ask": 1.10} # Spread 0.10
            },
            "O:AAPL230616C00160000": {
                "quote": {"bid": 0.50, "ask": 0.55} # Spread 0.05
            }
        }

        # Expected total width = 0.10 + 0.05 = 0.15
        result = _combo_width_share_from_legs(mock_truth, legs, fallback_width_share=9.99)
        self.assertAlmostEqual(result, 0.15)

    def test_combo_width_share_fallback(self):
        mock_truth = MagicMock()
        mock_truth.snapshot_many.return_value = {} # Empty

        legs = [{"symbol": "XYZ"}]
        result = _combo_width_share_from_legs(mock_truth, legs, fallback_width_share=0.50)
        self.assertEqual(result, 0.50)

    @patch("packages.quantum.options_scanner.MarketDataTruthLayer")
    @patch("packages.quantum.options_scanner.PolygonService")
    @patch("packages.quantum.options_scanner.StrategySelector")
    @patch("packages.quantum.options_scanner.RegimeEngineV3")
    @patch("packages.quantum.options_scanner.calculate_unified_score")
    @patch("packages.quantum.options_scanner.UniverseService")
    def test_scan_flow_uses_option_spread(self, MockUniverse, MockScore, MockRegime, MockSelector, MockPolygon, MockTruth):
        # Setup Mocks

        # Universe
        MockUniverse.return_value.get_universe.return_value = [{"symbol": "TEST"}]

        # Truth Layer (Global)
        mock_truth_instance = MockTruth.return_value

        # Strategy Selector
        mock_selector_instance = MockSelector.return_value
        mock_selector_instance.determine_strategy.return_value = {
            "strategy": "Vertical Call",
            "legs": [
                {"side": "buy", "type": "call", "delta_target": 0.5},
                {"side": "sell", "type": "call", "delta_target": 0.3}
            ]
        }

        # Polygon (Market Data)
        mock_poly_instance = MockPolygon.return_value
        mock_poly_instance.get_recent_quote.return_value = {
            "bid": 100.0, "ask": 100.10, "price": 100.05
        }
        # Option Chain
        mock_poly_instance.get_option_chain.return_value = [
            # Leg 1
            {
                "ticker": "TEST_LEG_1", "strike": 100, "expiration": "2023-01-01", "type": "call",
                "price": 5.0, "close": 5.0, "delta": 0.5, "gamma": 0.1, "vega": 0.1, "theta": -0.1
            },
            # Leg 2
            {
                "ticker": "TEST_LEG_2", "strike": 105, "expiration": "2023-01-01", "type": "call",
                "price": 2.0, "close": 2.0, "delta": 0.3, "gamma": 0.1, "vega": 0.1, "theta": -0.1
            }
        ]
        mock_poly_instance.get_historical_prices.return_value = [{"close": 100.0}] * 60

        # Regime
        mock_regime_instance = MockRegime.return_value
        mock_regime_instance.compute_global_snapshot.return_value.state = "NORMAL"
        mock_regime_instance.compute_global_snapshot.return_value.to_dict.return_value = {"state": "NORMAL"}
        mock_regime_instance.compute_symbol_snapshot.return_value.iv_rank = 50.0
        mock_regime_instance.get_effective_regime.return_value.value = "NORMAL"

        # Unified Score Mock Return
        mock_score_obj = MagicMock()
        mock_score_obj.score = 85.0
        mock_score_obj.execution_cost_dollars = 16.3
        mock_score_obj.components.dict.return_value = {}
        mock_score_obj.badges = []
        MockScore.return_value = mock_score_obj

        # Mock Truth Layer for LEG quotes
        # Leg 1: Price 5.0. Spread 0.20
        # Leg 2: Price 2.0. Spread 0.10
        # Total combo width = 0.30
        # Entry cost = 3.0
        # Option spread pct = 0.10

        mock_truth_instance.snapshot_many.return_value = {
            "O:TEST_LEG_1": {"quote": {"bid": 4.90, "ask": 5.10}},
            "O:TEST_LEG_2": {"quote": {"bid": 1.95, "ask": 2.05}},
        }
        mock_truth_instance.normalize_symbol.side_effect = lambda x: "O:" + x if not x.startswith("O:") else x

        # Run Scanner
        results = scan_for_opportunities(symbols=["TEST"])

        # Verification
        self.assertTrue(MockScore.called)
        call_args = MockScore.call_args
        kwargs = call_args[1]

        # Verify market_data["bid_ask_spread_pct"] passed is option_spread_pct
        market_data_arg = kwargs.get("market_data", {})
        bid_ask_pct = market_data_arg.get("bid_ask_spread_pct")
        self.assertAlmostEqual(bid_ask_pct, 0.10)

        # 2. Execution cost proxy
        # formula: (combo_width_share * 0.5) + (len(legs) * 0.0065)
        # width=0.30 -> 0.15 + 2*0.0065 = 0.15 + 0.013 = 0.163
        # in contract dollars -> 16.3
        exec_cost_arg = kwargs.get("execution_drag_estimate")
        self.assertAlmostEqual(exec_cost_arg, 16.3)
