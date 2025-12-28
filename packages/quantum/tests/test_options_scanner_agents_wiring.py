
import unittest
from unittest.mock import MagicMock, patch, ANY
import os
from datetime import datetime, timedelta
from packages.quantum.options_scanner import scan_for_opportunities

class TestOptionsScannerAgentsWiring(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_universe = MagicMock()
        self.mock_regime = MagicMock()
        self.mock_market_data = MagicMock()

        # Patch dependencies
        self.patchers = []

        # 1. MarketDataTruthLayer
        self.truth_patch = patch('packages.quantum.options_scanner.MarketDataTruthLayer')
        self.mock_truth = self.truth_patch.start()
        # Mock quotes
        self.mock_truth.return_value.snapshot_many.return_value = {
            "SPY": {
                "quote": {"bid": 400.0, "ask": 400.10, "last": 400.05}
            }
        }
        self.mock_truth.return_value.daily_bars.return_value = [{"close": 400.0} for _ in range(60)]
        self.mock_truth.return_value.option_chain.return_value = [] # Fallback to market_data
        self.patchers.append(self.truth_patch)

        # 2. PolygonService (fallback)
        self.poly_patch = patch('packages.quantum.options_scanner.PolygonService')
        self.mock_poly = self.poly_patch.start()
        # Mock option chain
        self.mock_poly.return_value.get_option_chain.return_value = [
            {
                "ticker": "O:SPY230519C00400000",
                "strike": 400.0,
                "expiration": (datetime.now().date() + timedelta(days=35)).isoformat(),
                "type": "call",
                "price": 5.0,
                "bid": 4.90,
                "ask": 5.10,
                "delta": 0.5,
                "gamma": 0.05,
                "vega": 0.1,
                "theta": -0.1
            },
            {
                "ticker": "O:SPY230519P00400000",
                "strike": 400.0,
                "expiration": (datetime.now().date() + timedelta(days=35)).isoformat(),
                "type": "put",
                "price": 5.0,
                "bid": 4.90,
                "ask": 5.10,
                "delta": -0.5,
                "gamma": 0.05,
                "vega": 0.1,
                "theta": -0.1
            }
        ]
        self.patchers.append(self.poly_patch)

        # 3. RegimeEngineV3
        self.regime_patch = patch('packages.quantum.options_scanner.RegimeEngineV3')
        self.mock_regime = self.regime_patch.start()
        # Global Snapshot
        self.mock_gs = MagicMock()
        self.mock_gs.state.value = "normal"
        self.mock_gs.to_dict.return_value = {"state": "normal"}
        self.mock_regime.return_value.compute_global_snapshot.return_value = self.mock_gs
        # Symbol Snapshot
        self.mock_ss = MagicMock()
        self.mock_ss.iv_rank = 50.0
        self.mock_regime.return_value.compute_symbol_snapshot.return_value = self.mock_ss
        # Effective Regime
        self.mock_effective = MagicMock()
        self.mock_effective.value = "normal"
        self.mock_regime.return_value.get_effective_regime.return_value = self.mock_effective
        self.patchers.append(self.regime_patch)

        # 4. StrategySelector
        self.selector_patch = patch('packages.quantum.options_scanner.StrategySelector')
        self.mock_selector = self.selector_patch.start()
        self.mock_selector.return_value.determine_strategy.return_value = {
            "strategy": "long_call",
            "legs": [{"type": "call", "side": "buy", "delta_target": 0.5}]
        }
        self.patchers.append(self.selector_patch)

        # 5. AgentRunner
        self.runner_patch = patch('packages.quantum.options_scanner.AgentRunner')
        self.mock_runner = self.runner_patch.start()
        # Default mock return
        self.mock_runner.run_agents.return_value = ({}, {})
        self.patchers.append(self.runner_patch)

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_scanner_includes_regime_and_vol_agents(self):
        """
        Verify that RegimeAgent and VolSurfaceAgent are instantiated and run when QUANT_AGENTS_ENABLED=true.
        """
        # Enable Agents by patching the global variable in options_scanner
        with patch('packages.quantum.options_scanner.QUANT_AGENTS_ENABLED', True):
            # We mock the Agent constructors to verify they are called
            with patch('packages.quantum.options_scanner.RegimeAgent') as MockRegimeAgent, \
                 patch('packages.quantum.options_scanner.VolSurfaceAgent') as MockVolSurfaceAgent, \
                 patch('packages.quantum.options_scanner.LiquidityAgent') as MockLiquidityAgent, \
                 patch('packages.quantum.options_scanner.EventRiskAgent') as MockEventRiskAgent, \
                 patch('packages.quantum.options_scanner.StrategyDesignAgent') as MockStrategyDesignAgent:

                # Set up mocks
                mock_regime_instance = MockRegimeAgent.return_value
                mock_vol_instance = MockVolSurfaceAgent.return_value

                # Run scanner for 1 symbol
                candidates = scan_for_opportunities(symbols=["SPY"])

                # Verification
                self.assertTrue(len(candidates) > 0, "Should return at least one candidate")

                # Check AgentRunner was called
                # Note: It might be called multiple times (StrategyDesignAgent separately, then the rest)

                # We expect the SECOND call to run_agents (for canonical agents) to include our new agents
                # First call is StrategyDesignAgent
                # Second call is Liquidity + EventRisk + Regime + VolSurface

                # Find the call args where list of agents was passed
                run_calls = self.mock_runner.run_agents.call_args_list
                found_our_agents = False

                for call in run_calls:
                    args, kwargs = call
                    context = args[0]
                    agents_list = args[1]

                    # Check if list contains our new agents
                    if mock_regime_instance in agents_list and mock_vol_instance in agents_list:
                        found_our_agents = True

                        # Verify context contains required keys
                        self.assertIn("effective_regime", context)
                        self.assertIn("iv_rank", context)
                        self.assertEqual(context["effective_regime"], "normal")
                        self.assertEqual(context["iv_rank"], 50.0)
                        break

                self.assertTrue(found_our_agents, "RegimeAgent and VolSurfaceAgent were not passed to AgentRunner")

if __name__ == '__main__':
    unittest.main()
