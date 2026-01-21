"""
Tests for backtest_metrics.py v4 upgrades.

Tests:
1. Real turnover calculation (not placeholder 0.0)
2. Real fill_rate calculation from events
3. cost_drag_bps calculation
4. Backward compatibility with existing call signature
"""

import unittest
import sys
import os

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBacktestMetricsV4(unittest.TestCase):
    """Tests for v4 metric calculations."""

    def test_turnover_positive_with_trades(self):
        """Turnover > 0 when trades exist with prices and quantities."""
        from services.backtest_metrics import calculate_backtest_metrics

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 50.0,
                "slippage_paid": 1.0,
                "commission_paid": 2.0
            },
            {
                "entry_price": 200.0,
                "exit_price": 195.0,
                "quantity": 5,
                "multiplier": 1.0,
                "pnl": -25.0,
                "slippage_paid": 0.5,
                "commission_paid": 1.0
            }
        ]

        equity_curve = [
            {"date": "2024-01-01", "equity": 10000.0},
            {"date": "2024-01-02", "equity": 10050.0},
            {"date": "2024-01-03", "equity": 10025.0}
        ]

        metrics = calculate_backtest_metrics(trades, equity_curve, 10000.0)

        # Turnover should be > 0
        self.assertGreater(metrics["turnover"], 0.0)

        # Verify calculation:
        # Trade 1: (100*10*1) + (105*10*1) = 1000 + 1050 = 2050
        # Trade 2: (200*5*1) + (195*5*1) = 1000 + 975 = 1975
        # Total notional = 4025
        # Avg equity = (10000 + 10050 + 10025) / 3 = 10025
        # Turnover = 4025 / 10025 ≈ 0.4015
        expected_turnover = 4025.0 / 10025.0
        self.assertAlmostEqual(metrics["turnover"], expected_turnover, places=3)

    def test_turnover_with_multiplier(self):
        """Turnover calculation respects multiplier (e.g., 100 for options)."""
        from services.backtest_metrics import calculate_backtest_metrics

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

        metrics = calculate_backtest_metrics(trades, [], 10000.0)

        # Notional = (5*2*100) + (6*2*100) = 1000 + 1200 = 2200
        # Turnover = 2200 / 10000 = 0.22
        self.assertAlmostEqual(metrics["turnover"], 0.22, places=2)

    def test_fill_rate_from_events(self):
        """Fill rate calculated from event requested_qty/filled_qty."""
        from services.backtest_metrics import calculate_backtest_metrics

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "quantity": 8,
                "multiplier": 1.0,
                "pnl": 40.0,
                "slippage_paid": 1.0,
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

        metrics = calculate_backtest_metrics(trades, [], 10000.0, events=events)

        # Fill rate = (8 + 8) / (10 + 8) = 16 / 18 ≈ 0.889
        expected_fill_rate = 16.0 / 18.0
        self.assertAlmostEqual(metrics["fill_rate"], expected_fill_rate, places=3)

    def test_fill_rate_default_without_events(self):
        """Fill rate defaults to 1.0 when events not provided."""
        from services.backtest_metrics import calculate_backtest_metrics

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 50.0,
                "slippage_paid": 1.0,
                "commission_paid": 1.0
            }
        ]

        # No events provided
        metrics = calculate_backtest_metrics(trades, [], 10000.0)

        self.assertEqual(metrics["fill_rate"], 1.0)

    def test_cost_drag_bps_calculation(self):
        """cost_drag_bps calculated from slippage + commission."""
        from services.backtest_metrics import calculate_backtest_metrics

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 50.0,
                "slippage_paid": 10.0,
                "commission_paid": 5.0
            }
        ]

        metrics = calculate_backtest_metrics(trades, [], 10000.0)

        # cost_drag_bps = ((10 + 5) / 10000) * 10000 = 15 bps
        self.assertAlmostEqual(metrics["cost_drag_bps"], 15.0, places=1)

    def test_backward_compatibility_no_events(self):
        """Existing call sites without events parameter still work."""
        from services.backtest_metrics import calculate_backtest_metrics

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

        # Call without events parameter (backward compat)
        metrics = calculate_backtest_metrics(trades, equity_curve, 10000.0)

        # Should return all expected keys
        self.assertIn("sharpe", metrics)
        self.assertIn("turnover", metrics)
        self.assertIn("fill_rate", metrics)
        self.assertIn("cost_drag_bps", metrics)
        self.assertIn("commission_paid", metrics)
        self.assertIn("trades_count", metrics)

    def test_empty_trades_returns_safe_defaults(self):
        """Empty trades list returns safe default metrics."""
        from services.backtest_metrics import calculate_backtest_metrics

        metrics = calculate_backtest_metrics([], [], 10000.0)

        self.assertEqual(metrics["turnover"], 0.0)
        self.assertEqual(metrics["fill_rate"], 1.0)
        self.assertEqual(metrics["cost_drag_bps"], 0.0)
        self.assertEqual(metrics["trades_count"], 0)

    def test_empty_equity_curve_uses_initial_equity(self):
        """When equity_curve is empty, uses initial_equity for avg_equity."""
        from services.backtest_metrics import calculate_backtest_metrics

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 10,
                "multiplier": 1.0,
                "pnl": 100.0,
                "slippage_paid": 5.0,
                "commission_paid": 5.0
            }
        ]

        # Empty equity curve
        metrics = calculate_backtest_metrics(trades, [], 10000.0)

        # cost_drag_bps = ((5 + 5) / 10000) * 10000 = 10 bps
        self.assertAlmostEqual(metrics["cost_drag_bps"], 10.0, places=1)

        # Turnover = (1000 + 1100) / 10000 = 0.21
        self.assertAlmostEqual(metrics["turnover"], 0.21, places=2)


if __name__ == "__main__":
    unittest.main()
