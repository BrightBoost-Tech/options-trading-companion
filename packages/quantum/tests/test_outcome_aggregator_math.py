import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime
from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.services.options_utils import get_contract_multiplier

class TestOutcomeAggregatorMath(unittest.TestCase):
    def test_get_contract_multiplier(self):
        # Options
        self.assertEqual(get_contract_multiplier("O:SPY231215C00450000"), 100.0)
        self.assertEqual(get_contract_multiplier("O:AMZN230616P00120000"), 100.0)
        self.assertEqual(get_contract_multiplier("SPY231215C00450000"), 100.0) # Without O: prefix if handled

        # Equities
        self.assertEqual(get_contract_multiplier("SPY"), 1.0)
        self.assertEqual(get_contract_multiplier("AAPL"), 1.0)
        self.assertEqual(get_contract_multiplier("CUR:USD"), 1.0)

        # Short ticker
        self.assertEqual(get_contract_multiplier("F"), 1.0)

    def test_calculate_execution_pnl_option(self):
        # Mock dependencies
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()
        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        # Setup mock price history
        # Last price 5.0
        mock_polygon.get_historical_prices.return_value = {"prices": [4.0, 4.5, 5.0]}

        executions = [{
            "symbol": "O:TEST230101C00100000",
            "quantity": 1,
            "fill_price": 2.0 # Bought at 2.0
        }]

        # Expect: (5.0 - 2.0) * 1 * 100 = 300.0
        pnl, vol = aggregator._calculate_execution_pnl(executions)
        self.assertAlmostEqual(pnl, 300.0)

    def test_calculate_execution_pnl_stock(self):
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()
        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        mock_polygon.get_historical_prices.return_value = {"prices": [140.0, 145.0, 150.0]}

        executions = [{
            "symbol": "AAPL",
            "quantity": 10,
            "fill_price": 100.0 # Bought at 100.0
        }]

        # Expect: (150.0 - 100.0) * 10 * 1 = 500.0
        pnl, vol = aggregator._calculate_execution_pnl(executions)
        self.assertAlmostEqual(pnl, 500.0)

    def test_incomplete_equity_handling(self):
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()
        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        decision = {
            "trace_id": str(uuid.uuid4()),
            "decision_type": "optimizer_weights",
            "content": {"target_weights": {"SPY": 1.0}}
        }

        # Log without equity
        inference_log = {"inputs_snapshot": {}} # No total_equity

        with patch("packages.quantum.services.outcome_aggregator.log_outcome") as mock_log:
            aggregator._process_single_outcome(decision, inference_log, [], [])

            # Should log as incomplete
            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            self.assertEqual(kwargs["attribution_type"], "incomplete_data")
            self.assertEqual(kwargs["realized_pl_1d"], 0.0)

    def test_sim_pnl_with_equity(self):
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()
        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        # SPY went up 10% (100 -> 110)
        mock_polygon.get_historical_prices.return_value = {"prices": [100.0, 110.0]}

        decision = {
            "trace_id": str(uuid.uuid4()),
            "decision_type": "optimizer_weights",
            "content": {"target_weights": {"SPY": 1.0}}
        }

        inference_log = {"inputs_snapshot": {"total_equity": 50000.0}}

        with patch("packages.quantum.services.outcome_aggregator.log_outcome") as mock_log:
            aggregator._process_single_outcome(decision, inference_log, [], [])

            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args

            # PnL = 1.0 * 50000 * 0.10 = 5000.0
            self.assertAlmostEqual(kwargs["realized_pl_1d"], 5000.0)
            self.assertEqual(kwargs["attribution_type"], "optimizer_simulation")

    def test_calculate_portfolio_pnl(self):
        """Test the portfolio snapshot attribution logic."""
        mock_supabase = MagicMock()
        mock_polygon = MagicMock()
        aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

        # Setup mock: SPY +10%, AAPL -5%
        # SPY: 100 -> 110
        # AAPL: 100 -> 95
        def get_prices(sym, days=5):
            if sym == "SPY": return {"prices": [100.0, 110.0]}
            if sym == "AAPL": return {"prices": [100.0, 95.0]}
            return {}
        mock_polygon.get_historical_prices.side_effect = get_prices

        # Inference log with positions
        inference_log = {
            "symbol_universe": ["SPY", "AAPL"],
            "inputs_snapshot": {
                "positions": [
                    {"symbol": "SPY", "current_quantity": 10},
                    {"symbol": "AAPL", "current_quantity": 20}
                ]
            }
        }

        # SPY PnL: (110 - 100) * 10 = 100
        # AAPL PnL: (95 - 100) * 20 = -100
        # Total PnL = 0.0

        # Vol: SPY abs(0.10), AAPL abs(-0.05) -> avg(0.10, 0.05) = 0.075

        pnl, vol = aggregator._calculate_portfolio_pnl(inference_log)

        self.assertAlmostEqual(pnl, 0.0)
        self.assertAlmostEqual(vol, 0.075)

if __name__ == '__main__':
    unittest.main()
