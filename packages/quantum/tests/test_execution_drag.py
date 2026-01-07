import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from packages.quantum.services.execution_service import ExecutionService, ExecutionDragStats

class TestExecutionDrag(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ExecutionService(self.mock_supabase)
        self.user_id = "test-user-123"

    def test_get_batch_execution_drag_stats(self):
        # Mock Executions
        # Symbol A: 3 executions, consistent slippage
        # Symbol B: 2 executions (should be skipped due to min_samples=3)
        executions = [
            {"symbol": "A", "fill_price": 10.10, "fees": 0.05, "suggestion_id": "s1"},
            {"symbol": "A", "fill_price": 10.20, "fees": 0.05, "suggestion_id": "s2"},
            {"symbol": "A", "fill_price": 10.05, "fees": 0.05, "suggestion_id": "s3"},
            {"symbol": "B", "fill_price": 5.10, "fees": 0.05, "suggestion_id": "s4"},
            {"symbol": "B", "fill_price": 5.20, "fees": 0.05, "suggestion_id": "s5"},
        ]

        # Mock Suggestions (targets)
        # s1: target 10.00 -> slip 0.10
        # s2: target 10.00 -> slip 0.20
        # s3: target 10.00 -> slip 0.05
        # s4: target 5.00 -> slip 0.10
        # s5: target 5.00 -> slip 0.20
        suggestions = [
            {"id": "s1", "target_price": 10.00},
            {"id": "s2", "target_price": 10.00},
            {"id": "s3", "target_price": 10.00},
            {"id": "s4", "target_price": 5.00},
            {"id": "s5", "target_price": 5.00},
        ]

        # Mock Supabase responses
        def table_side_effect(name):
            if name == "trade_executions":
                chain_mock = MagicMock()
                chain_mock.select.return_value = chain_mock
                chain_mock.eq.return_value = chain_mock
                chain_mock.in_.return_value = chain_mock
                chain_mock.gte.return_value = chain_mock
                chain_mock.order.return_value = chain_mock

                not_mock = MagicMock()
                not_mock.is_.return_value = chain_mock
                type(chain_mock).not_ = unittest.mock.PropertyMock(return_value=not_mock)

                res_mock = MagicMock()
                res_mock.data = executions
                chain_mock.execute.return_value = res_mock

                return chain_mock

            elif name == "suggestion_logs":
                mock_builder = MagicMock()
                mock_builder.select.return_value.in_.return_value.execute.return_value.data = suggestions
                return mock_builder
            return MagicMock()

        self.mock_supabase.table.side_effect = table_side_effect

        stats = self.service.get_batch_execution_drag_stats(
            self.user_id, ["A", "B"], min_samples=3
        )

        # Verify Symbol A
        self.assertIn("A", stats)
        # Slippage in contract dollars (x100 for options)
        # slip 0.10 share -> 10.00 contract
        # slip 0.20 share -> 20.00 contract
        # slip 0.05 share -> 5.00 contract
        expected_avg_abs_slip = (10.0 + 20.0 + 5.0) / 3

        # Fees per contract
        # 0.05 per trade, qty=1 (implied) -> 0.05
        expected_avg_fees = 0.05

        # Drag = slip + fees
        expected_avg_drag = expected_avg_abs_slip + expected_avg_fees

        self.assertAlmostEqual(stats["A"]["avg_abs_slip"], expected_avg_abs_slip)
        self.assertAlmostEqual(stats["A"]["avg_fees"], expected_avg_fees)
        self.assertAlmostEqual(stats["A"]["avg_drag"], expected_avg_drag)
        self.assertEqual(stats["A"]["n"], 3)

        # Verify Symbol B is missing (n=2 < 3)
        self.assertNotIn("B", stats)

    @patch("packages.quantum.options_scanner.PolygonService")
    @patch("packages.quantum.options_scanner.UniverseService")
    @patch("packages.quantum.options_scanner.StrategySelector")
    @patch("packages.quantum.options_scanner.ExecutionService")
    @patch("packages.quantum.options_scanner.RegimeEngineV3")
    @patch("packages.quantum.options_scanner.IVRepository")
    @patch("packages.quantum.options_scanner.MarketDataTruthLayer")
    def test_scanner_rejection_logic(self, MockMDTL, MockIVRepo, MockRegimeEngine, MockExecService, MockSelector, MockUniverse, MockPolygon):
        from packages.quantum.options_scanner import scan_for_opportunities

        # Setup Services
        mock_poly = MockPolygon.return_value
        mock_exec = MockExecService.return_value
        mock_selector = MockSelector.return_value
        mock_regime = MockRegimeEngine.return_value
        mock_mdtl = MockMDTL.return_value

        # 1. Mock Universe
        symbols = ["HIGH_COST"]

        # 2. Mock Execution Stats (High Drag)
        # EV will be 0.05, Drag will be 0.10 -> Should reject
        # Note: Proxy drag for spread 0.20 is ~10.65. Rejection uses max(history, proxy).
        # So 0.05 EV < 10.65 Cost -> Reject.
        mock_exec.get_batch_execution_drag_stats.return_value = {
            "HIGH_COST": {"avg_drag": 0.10, "n": 5}
        }

        # 3. Mock Market Data (MDTL and Polygon)
        # Fix mock to accept key lookups
        def snapshot_side_effect(symbols):
            return {
                "HIGH_COST": {
                    "quote": {"bid": 99.90, "ask": 100.10, "mid": 100.0, "last": 100.0}
                },
                "LOW_COST": {
                    "quote": {"bid": 99.90, "ask": 100.10, "mid": 100.0, "last": 100.0}
                },
                "OPT1": {
                    # Tighter spread (0.10 width on 2.00 price = 5%) to pass 10% liquidity check
                    "quote": {"bid": 1.95, "ask": 2.05, "mid": 2.0, "last": 2.0},
                    "greeks": {"delta": 0.5, "gamma": 0.01, "vega": 0.01, "theta": -0.01},
                    "contract": "OPT1", "strike": 100, "expiry": "2025-01-01", "right": "call"
                }
            }
        mock_mdtl.snapshot_many.side_effect = snapshot_side_effect
        mock_mdtl.normalize_symbol.side_effect = lambda x: x

        # Mock daily bars for trend/regime
        # Must return at least 50 bars
        prices = [100.0] * 60
        mock_mdtl.daily_bars.return_value = [{"close": p} for p in prices]

        # Mock Polygon fallback if needed (but MDTL mocks should cover it)
        mock_poly.get_recent_quote.return_value = {
            "price": 100.0, "bid_price": 99.90, "ask_price": 100.10
        }
        mock_poly.get_historical_prices.return_value = [{"close": 100} for _ in range(60)]

        # Mock Option Chain
        # IMPORTANT: Expiry must be within 25-45 days
        future_date = (datetime.now() + timedelta(days=35)).strftime("%Y-%m-%d")

        chain_data = [
            {"contract": "OPT1", "strike": 100, "expiry": future_date, "right": "call",
             "greeks": {"delta": 0.5, "gamma": 0.01, "vega": 0.01, "theta": -0.01},
             # Tighter spread here too for consistency
             "quote": {"mid": 2.0, "last": 2.0, "bid": 1.95, "ask": 2.05}}
        ]
        mock_mdtl.option_chain.return_value = chain_data

        # 4. Mock Strategy
        mock_selector.determine_strategy.return_value = {
            "strategy": "long_call",
            "legs": [{"side": "buy", "type": "call", "delta_target": 0.5}]
        }

        # 5. Mock Regime
        mock_regime.compute_global_snapshot.return_value.state.value = "normal"
        # Return object that has .value
        mock_regime.compute_symbol_snapshot.return_value.iv_rank = 50
        mock_regime.get_effective_regime.return_value.value = "normal"

        # 6. Run Scanner
        # EV is calculated internally.
        # A long call with delta 0.5 approx.
        # We need to make sure EV < 0.10.

        with patch("packages.quantum.options_scanner.calculate_ev") as mock_calc_ev:
            mock_ev_obj = MagicMock()
            mock_ev_obj.expected_value = 0.05 # EV < Cost (10.65)
            mock_calc_ev.return_value = mock_ev_obj

            with patch("packages.quantum.options_scanner.calculate_unified_score") as mock_score:
                mock_score.return_value.score = 80.0
                # Cost for tighter spread (0.10 width):
                # (0.10 * 0.5 + 0.0065) * 100 = 5.65
                mock_score.return_value.execution_cost_dollars = 5.65

                results = scan_for_opportunities(
                    symbols=symbols,
                    supabase_client=self.mock_supabase, # triggers usage of exec service
                    user_id=self.user_id
                )

                # Should be empty because it was rejected (EV 0.05 < Cost 5.65)
                self.assertEqual(len(results), 0)

        # Test Acceptance Case (EV > Drag)
        mock_exec.get_batch_execution_drag_stats.return_value = {
            "LOW_COST": {"avg_drag": 0.02, "n": 5}
        }

        # Ensure MDTL returns valid quotes for LOW_COST

        with patch("packages.quantum.options_scanner.calculate_ev") as mock_calc_ev:
            mock_ev_obj = MagicMock()
            mock_ev_obj.expected_value = 20.0 # EV (20.0) > Cost (~5.65)
            mock_calc_ev.return_value = mock_ev_obj

            with patch("packages.quantum.options_scanner.calculate_unified_score") as mock_score:
                mock_score.return_value.score = 80.0
                mock_score.return_value.components.dict.return_value = {}
                mock_score.return_value.badges = []
                mock_score.return_value.execution_cost_dollars = 5.65

                results = scan_for_opportunities(
                    symbols=["LOW_COST"],
                    supabase_client=self.mock_supabase,
                    user_id=self.user_id
                )

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["symbol"], "LOW_COST")
                # Expected cost calculation:
                # spread_width = 2.05 - 1.95 = 0.10
                # proxy_cost = (0.10 * 0.5 + 0.0065) * 100 = 5.65
                self.assertAlmostEqual(results[0]["execution_drag_estimate"], 5.65)

if __name__ == '__main__':
    unittest.main()
