import unittest
from unittest.mock import MagicMock, patch
import os
import sys
from datetime import datetime

# Adjust path to import packages
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.analytics.regime_engine_v3 import RegimeState

class TestScannerUsesUniverseService(unittest.TestCase):
    def setUp(self):
        # Set APP_ENV to production to avoid dev limits interfering (or keep it as is, but explicit is better)
        self.original_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "production"

    def tearDown(self):
        if self.original_env:
            os.environ["APP_ENV"] = self.original_env
        else:
            del os.environ["APP_ENV"]

    @patch('packages.quantum.options_scanner.UniverseService')
    @patch('packages.quantum.options_scanner.MarketDataTruthLayer')
    @patch('packages.quantum.options_scanner.PolygonService')
    @patch('packages.quantum.options_scanner.StrategySelector')
    @patch('packages.quantum.options_scanner.calculate_ev')
    @patch('packages.quantum.options_scanner.calculate_unified_score')
    @patch('packages.quantum.options_scanner.RegimeEngineV3')
    @patch('packages.quantum.options_scanner.IVRepository')
    @patch('packages.quantum.options_scanner.IVPointService')
    def test_scanner_uses_universe_service(self,
                                           MockIVPointService,
                                           MockIVRepository,
                                           MockRegimeEngine,
                                           MockUnifiedScore,
                                           MockCalcEV,
                                           MockStrategySelector,
                                           MockPolygonService,
                                           MockTruthLayer,
                                           MockUniverseService):

        # 1. Setup Mock UniverseService
        mock_universe_instance = MockUniverseService.return_value
        # When get_scan_candidates is called, return our controlled symbol "ZZZ"
        mock_universe_instance.get_scan_candidates.return_value = [{"symbol": "ZZZ", "earnings_date": None}]

        # 2. Setup Mock TruthLayer (for quotes and chains)
        mock_truth_instance = MockTruthLayer.return_value

        # snapshot_many: return a valid quote for ZZZ
        mock_truth_instance.snapshot_many.return_value = {
            "ZZZ": {
                "quote": {
                    "bid": 100.0,
                    "ask": 101.0, # Spread $1.00
                    "last": 100.5,
                    "mid": 100.5
                }
            }
        }
        from datetime import timedelta
        # option_chain: return minimal valid chain
        mock_truth_instance.option_chain.return_value = [
            {
                "contract": "ZZZ_250101C100",
                "strike": 100.0,
                "expiry": (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "right": "call",
                "quote": {"mid": 5.0, "last": 5.0, "bid": 4.9, "ask": 5.1},
                "greeks": {"delta": 0.5, "gamma": 0.05, "vega": 0.1, "theta": -0.1}
            }
        ]
        # daily_bars: return enough bars to compute trend
        mock_truth_instance.daily_bars.return_value = [{"close": 100.0} for _ in range(60)]

        # 3. Setup Mock RegimeEngine
        mock_regime_instance = MockRegimeEngine.return_value
        mock_global_snapshot = MagicMock()
        mock_global_snapshot.state = RegimeState.NORMAL
        mock_global_snapshot.to_dict.return_value = {"state": "NORMAL"}
        mock_regime_instance.compute_global_snapshot.return_value = mock_global_snapshot

        mock_symbol_snapshot = MagicMock()
        mock_symbol_snapshot.iv_rank = 50.0
        mock_regime_instance.compute_symbol_snapshot.return_value = mock_symbol_snapshot

        mock_effective_regime = MagicMock()
        mock_effective_regime.value = "NORMAL"
        mock_regime_instance.get_effective_regime.return_value = mock_effective_regime

        # 4. Setup Mock StrategySelector
        mock_selector_instance = MockStrategySelector.return_value
        mock_selector_instance.determine_strategy.return_value = {
            "strategy": "Long Call",
            "legs": [{
                "delta_target": 0.5,
                "side": "buy",
                "type": "call"
            }]
        }

        # 5. Setup Mock EV and Score
        mock_ev_instance = MagicMock()
        mock_ev_instance.expected_value = 200.0 # High EV
        MockCalcEV.return_value = mock_ev_instance

        mock_unified_score_instance = MagicMock()
        mock_unified_score_instance.score = 80.0
        mock_unified_score_instance.execution_cost_dollars = 10.0
        mock_unified_score_instance.components = MagicMock()
        mock_unified_score_instance.components.dict.return_value = {}
        mock_unified_score_instance.badges = []
        MockUnifiedScore.return_value = mock_unified_score_instance

        # 6. Run the Scanner
        # Pass a Mock Supabase client to trigger UniverseService instantiation
        mock_supabase = MagicMock()
        results = scan_for_opportunities(symbols=None, supabase_client=mock_supabase)

        # 7. Assertions

        # Verify UniverseService was initialized
        MockUniverseService.assert_called()

        # Verify get_scan_candidates was called (the key fix!)
        mock_universe_instance.get_scan_candidates.assert_called_with(limit=30)

        # Verify we didn't use fallback
        # If fallback was used, we'd see SPY, QQQ etc. here instead of ZZZ
        self.assertTrue(len(results) > 0, "Scanner returned no results")
        for res in results:
            self.assertEqual(res["symbol"], "ZZZ", "Scanner fell back to hardcoded list!")

if __name__ == '__main__':
    unittest.main()
