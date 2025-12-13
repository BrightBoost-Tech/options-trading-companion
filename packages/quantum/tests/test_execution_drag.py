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
        self.mock_supabase.table.return_value.select.return_value \
            .eq.return_value.in_.return_value.neq.return_value.neq.return_value.gte.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = executions

        # We need to handle the second query (suggestions)
        # The service calls: table(logs).select(...).in_(...).execute()
        # Since the first query chain is long, we can reset or use side_effect if needed.
        # But simpler: check table name called.

        def table_side_effect(name):
            mock_builder = MagicMock()
            if name == "trade_executions":
                mock_builder.select.return_value.eq.return_value.in_.return_value \
                    .neq.return_value.neq.return_value.gte.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = executions
            elif name == "suggestion_logs":
                mock_builder.select.return_value.in_.return_value.execute.return_value.data = suggestions
            return mock_builder

        self.mock_supabase.table.side_effect = table_side_effect

        stats = self.service.get_batch_execution_drag_stats(
            self.user_id, ["A", "B"], min_samples=3
        )

        # Verify Symbol A
        self.assertIn("A", stats)
        # A stats:
        # slips: 0.10, 0.20, 0.05 -> avg 0.1166...
        # fees: 0.05
        # drag: 0.166...
        self.assertAlmostEqual(stats["A"]["avg_abs_slip"], (0.10 + 0.20 + 0.05)/3)
        self.assertAlmostEqual(stats["A"]["avg_fees"], 0.05)
        self.assertAlmostEqual(stats["A"]["avg_drag"], ((0.10+0.05) + (0.20+0.05) + (0.05+0.05))/3)
        self.assertEqual(stats["A"]["n"], 3)

        # Verify Symbol B is missing (n=2 < 3)
        self.assertNotIn("B", stats)

    @patch("packages.quantum.options_scanner.PolygonService")
    @patch("packages.quantum.options_scanner.UniverseService")
    @patch("packages.quantum.options_scanner.StrategySelector")
    @patch("packages.quantum.options_scanner.ExecutionService")
    @patch("packages.quantum.options_scanner.RegimeEngineV3")
    @patch("packages.quantum.options_scanner.IVRepository")
    def test_scanner_rejection_logic(self, MockIVRepo, MockRegimeEngine, MockExecService, MockSelector, MockUniverse, MockPolygon):
        from packages.quantum.options_scanner import scan_for_opportunities

        # Setup Services
        mock_poly = MockPolygon.return_value
        mock_exec = MockExecService.return_value
        mock_selector = MockSelector.return_value
        mock_regime = MockRegimeEngine.return_value

        # 1. Mock Universe
        symbols = ["HIGH_COST"]

        # 2. Mock Execution Stats (High Drag)
        # EV will be 0.05, Drag will be 0.10 -> Should reject
        mock_exec.get_batch_execution_drag_stats.return_value = {
            "HIGH_COST": {"avg_drag": 0.10, "n": 5}
        }

        # 3. Mock Market Data
        mock_poly.get_recent_quote.return_value = {
            "price": 100.0, "bid_price": 99.90, "ask_price": 100.10 # spread 0.20
        }
        mock_poly.get_historical_prices.return_value = [{"close": 100} for _ in range(60)]

        # Mock Option Chain
        mock_poly.get_option_chain.return_value = [
            {"ticker": "OPT1", "strike": 100, "expiration": "2025-01-01", "type": "call",
             "delta": 0.5, "price": 2.0, "bid": 1.9, "ask": 2.1}
        ]

        # 4. Mock Strategy
        mock_selector.determine_strategy.return_value = {
            "strategy": "long_call",
            "legs": [{"side": "buy", "type": "call", "delta_target": 0.5}]
        }

        # 5. Mock Regime
        mock_regime.compute_global_snapshot.return_value.state.value = "normal"
        mock_regime.compute_symbol_snapshot.return_value.iv_rank = 50

        # 6. Run Scanner
        # EV is calculated internally.
        # A long call with delta 0.5 approx.
        # We need to make sure EV < 0.10.
        # calculate_ev logic depends on parameters.
        # If we can mock calculate_ev, that's best.

        with patch("packages.quantum.options_scanner.calculate_ev") as mock_calc_ev:
            mock_ev_obj = MagicMock()
            mock_ev_obj.expected_value = 0.05 # EV < Drag (0.10)
            mock_calc_ev.return_value = mock_ev_obj

            with patch("packages.quantum.options_scanner.calculate_unified_score") as mock_score:
                mock_score.return_value.score = 80.0 # High score otherwise

                results = scan_for_opportunities(
                    symbols=symbols,
                    supabase_client=self.mock_supabase, # triggers usage of exec service
                    user_id=self.user_id
                )

                # Should be empty because it was rejected
                self.assertEqual(len(results), 0)

        # Test Acceptance Case (EV > Drag)
        mock_exec.get_batch_execution_drag_stats.return_value = {
            "LOW_COST": {"avg_drag": 0.02, "n": 5}
        }

        with patch("packages.quantum.options_scanner.calculate_ev") as mock_calc_ev:
            mock_ev_obj = MagicMock()
            mock_ev_obj.expected_value = 0.05 # EV > Drag (0.02)
            mock_calc_ev.return_value = mock_ev_obj

            with patch("packages.quantum.options_scanner.calculate_unified_score") as mock_score:
                mock_score.return_value.score = 80.0
                mock_score.return_value.components.dict.return_value = {}
                mock_score.return_value.badges = []

                results = scan_for_opportunities(
                    symbols=["LOW_COST"],
                    supabase_client=self.mock_supabase,
                    user_id=self.user_id
                )

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["symbol"], "LOW_COST")
                self.assertEqual(results[0]["execution_drag_estimate"], 0.02)

if __name__ == '__main__':
    unittest.main()
