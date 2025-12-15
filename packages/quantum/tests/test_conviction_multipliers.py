import unittest
from unittest.mock import MagicMock, Mock
from packages.quantum.analytics.conviction_service import ConvictionService

class TestConvictionMultipliers(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ConvictionService(supabase=self.mock_supabase)
        self.user_id = "test-user-123"

    def test_get_performance_multipliers(self):
        # Mock data representing rows from learning_feedback_loops
        mock_data = [
            # High positive return, sufficient trades
            {
                "strategy": "debit_call",
                "window": "paper_trading",
                "total_trades": 10,
                "avg_return": 0.5, # Should be clamped to 0.5
            },
            # High negative return, sufficient trades
            {
                "strategy": "credit_put",
                "window": "paper_trading",
                "total_trades": 10,
                "avg_return": -0.4, # Should be clamped to -0.3
            },
            # Moderate return
            {
                "strategy": "iron_condor",
                "window": "historical_sim",
                "total_trades": 20,
                "avg_return": 0.1, # +0.1
            },
            # Insufficient trades (should be ignored)
            {
                "strategy": "butterfly",
                "window": "paper_trading",
                "total_trades": 2,
                "avg_return": 1.0,
            },
             # Missing fields (defaults)
            {
                "strategy": "unknown_strat",
                # window missing -> unknown
            }
        ]

        # Setup mock chain
        # supabase.table().select().eq().execute() -> res.data
        mock_query = self.mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value

        mock_query.execute.return_value = Mock(data=mock_data)

        # Execute method
        multipliers = self.service._get_performance_multipliers(self.user_id)

        # Verify query structure
        self.mock_supabase.table.assert_called_with("learning_feedback_loops")
        self.mock_supabase.table().select.assert_called_with("*")
        self.mock_supabase.table().select().eq.assert_called_with("user_id", self.user_id)

        # Check results

        # 1. debit_call: base 1.0 + clamp(0.5) -> 1.5. Clamp(1.5) -> 1.5.
        self.assertIn(("debit_call", "paper_trading"), multipliers)
        self.assertAlmostEqual(multipliers[("debit_call", "paper_trading")], 1.5)

        # 2. credit_put: base 1.0 + clamp(-0.4 -> -0.3) -> 0.7. Clamp(0.7) -> 0.7.
        self.assertIn(("credit_put", "paper_trading"), multipliers)
        self.assertAlmostEqual(multipliers[("credit_put", "paper_trading")], 0.7)

        # 3. iron_condor: base 1.0 + 0.1 -> 1.1.
        self.assertIn(("iron_condor", "historical_sim"), multipliers)
        self.assertAlmostEqual(multipliers[("iron_condor", "historical_sim")], 1.1)

        # 4. butterfly: ignored (trades < 5)
        self.assertNotIn(("butterfly", "paper_trading"), multipliers)

        # 5. unknown_strat: ignored (trades default 0 < 5)
        self.assertNotIn(("unknown_strat", "unknown"), multipliers)

if __name__ == '__main__':
    unittest.main()
