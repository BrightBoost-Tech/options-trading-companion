"""
Tests for v5 unified single-run metrics in BacktestEngine.

Tests:
1. Single-run metrics include v4 fields (turnover, fill_rate, cost_drag_bps)
2. Turnover is computed correctly (not placeholder 0.0)
3. fill_rate computed from events when provided
4. cost_drag_bps computed from slippage + commission
"""

import unittest
import sys
import os

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBacktestEngineMetricsV4(unittest.TestCase):
    """Tests for unified v4 metrics in BacktestEngine._calculate_metrics."""

    def test_calculate_metrics_returns_v4_fields(self):
        """_calculate_metrics returns all v4 metric fields."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 100.0,
                "slippage_paid": 2.0,
                "commission_paid": 1.0
            }
        ]

        equity_curve = [
            {"date": "2024-01-01", "equity": 10000.0},
            {"date": "2024-01-02", "equity": 10100.0}
        ]

        metrics = engine._calculate_metrics(trades, equity_curve, 10000.0)

        # V4 fields must be present
        self.assertIn("turnover", metrics)
        self.assertIn("fill_rate", metrics)
        self.assertIn("cost_drag_bps", metrics)
        self.assertIn("sharpe", metrics)
        self.assertIn("max_drawdown", metrics)
        self.assertIn("trades_count", metrics)

    def test_turnover_not_placeholder(self):
        """Turnover is computed correctly (not placeholder 0.0)."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 100.0,
                "slippage_paid": 2.0,
                "commission_paid": 1.0
            }
        ]

        equity_curve = [
            {"date": "2024-01-01", "equity": 10000.0},
            {"date": "2024-01-02", "equity": 10100.0}
        ]

        metrics = engine._calculate_metrics(trades, equity_curve, 10000.0)

        # Turnover = (100*10*1 + 110*10*1) / avg_equity
        # = 2100 / 10050 ≈ 0.209
        self.assertGreater(metrics["turnover"], 0.0, "Turnover should not be placeholder 0.0")
        self.assertAlmostEqual(metrics["turnover"], 2100.0 / 10050.0, places=2)

    def test_fill_rate_from_events(self):
        """fill_rate computed from events when provided."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 8,
                "multiplier": 1.0,
                "pnl": 80.0,
                "slippage_paid": 2.0,
                "commission_paid": 1.0
            }
        ]

        events = [
            {
                "event_type": "ENTRY_FILLED",
                "details": {
                    "requested_qty": 10,
                    "filled_qty": 8,
                    "multiplier": 1.0
                }
            },
            {
                "event_type": "EXIT_FILLED",
                "details": {
                    "requested_qty": 8,
                    "filled_qty": 8,
                    "multiplier": 1.0
                }
            }
        ]

        equity_curve = [
            {"date": "2024-01-01", "equity": 10000.0}
        ]

        metrics = engine._calculate_metrics(trades, equity_curve, 10000.0, events=events)

        # fill_rate = (8 + 8) / (10 + 8) = 16/18 ≈ 0.889
        expected_fill_rate = 16.0 / 18.0
        self.assertAlmostEqual(metrics["fill_rate"], expected_fill_rate, places=2)

    def test_fill_rate_default_without_events(self):
        """fill_rate defaults to 1.0 when events not provided."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 100.0,
                "slippage_paid": 2.0,
                "commission_paid": 1.0
            }
        ]

        metrics = engine._calculate_metrics(trades, [], 10000.0, events=None)

        self.assertEqual(metrics["fill_rate"], 1.0)

    def test_cost_drag_bps_computed(self):
        """cost_drag_bps computed from slippage + commission."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 100.0,
                "slippage_paid": 10.0,
                "commission_paid": 5.0
            }
        ]

        metrics = engine._calculate_metrics(trades, [], 10000.0)

        # cost_drag_bps = ((10 + 5) / 10000) * 10000 = 15 bps
        self.assertAlmostEqual(metrics["cost_drag_bps"], 15.0, places=1)

    def test_empty_trades_returns_safe_defaults(self):
        """Empty trades returns safe default metrics."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        metrics = engine._calculate_metrics([], [], 10000.0)

        self.assertEqual(metrics["turnover"], 0.0)
        self.assertEqual(metrics["fill_rate"], 1.0)
        self.assertEqual(metrics["cost_drag_bps"], 0.0)
        self.assertEqual(metrics["trades_count"], 0)

    def test_options_multiplier_in_turnover(self):
        """Turnover calculation respects multiplier=100 for options."""
        from services.backtest_engine import BacktestEngine

        engine = BacktestEngine(polygon_service=None)

        trades = [
            {
                "entry_price": 5.0,  # Option premium
                "exit_price": 6.0,
                "quantity": 2,  # 2 contracts
                "multiplier": 100.0,  # Options
                "pnl": 200.0,
                "slippage_paid": 5.0,
                "commission_paid": 4.0
            }
        ]

        metrics = engine._calculate_metrics(trades, [], 10000.0)

        # Notional = (5*2*100) + (6*2*100) = 1000 + 1200 = 2200
        # Turnover = 2200 / 10000 = 0.22
        self.assertAlmostEqual(metrics["turnover"], 0.22, places=2)


if __name__ == "__main__":
    unittest.main()
