import unittest
from unittest.mock import MagicMock, Mock
import math
from packages.quantum.analytics.conviction_service import ConvictionService

class TestConvictionMultipliers(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = ConvictionService(supabase=self.mock_supabase)
        self.user_id = "test-user-123"

    def test_v3_logic_calculations(self):
        """
        Verifies that V3 logic computes multipliers correctly based on leakage, shrinkage, and gating.
        """
        # Data for V3 table
        v3_rows = [
            # Case 1: Strong positive signal
            # Predicted 100, Leakage +20 (Realized 120). Raw = 1.2
            # Trades = 30. Shrink = 30 / (30+30) = 0.5.
            # Final = 1 + 0.5 * (0.2) = 1.1
            # Signal Check: avg_realized=120, std=50. SE=50/sqrt(30)=9.1. 120 > 9.1. Pass.
            {
                "strategy": "debit_call", "window": "paper_trading", "regime": "normal",
                "total_trades": 30,
                "avg_ev_leakage": 20.0, "avg_predicted_ev": 100.0,
                "avg_realized_pnl": 120.0, "std_realized_pnl": 50.0
            },
            # Case 2: Insufficient trades (< 20) -> Should default to 1.0 explicitly
            {
                "strategy": "credit_put", "window": "paper_trading", "regime": "normal",
                "total_trades": 10,
                "avg_ev_leakage": 20.0, "avg_predicted_ev": 100.0,
            },
            # Case 3: Weak signal (Noise)
            # Trades 100. SE = 100/10 = 10.
            # Avg Realized = 5. 5 < 10. -> Multiplier 1.0
            {
                "strategy": "iron_condor", "window": "paper_trading", "regime": "elevated",
                "total_trades": 100,
                "avg_ev_leakage": 50.0, "avg_predicted_ev": 100.0, # would be huge multiplier
                "avg_realized_pnl": 5.0, "std_realized_pnl": 100.0
            },
            # Case 4: Strong Negative signal
            # Predicted 100, Leakage -50. Raw = 0.5.
            # Trades 30. Shrink 0.5.
            # Final = 1 + 0.5 * (-0.5) = 0.75.
            # Clamp [0.7, 1.3] -> 0.75 is valid.
            {
                "strategy": "long_call", "window": "paper_trading", "regime": "normal",
                "total_trades": 30,
                "avg_ev_leakage": -50.0, "avg_predicted_ev": 100.0,
                "avg_realized_pnl": 50.0, "std_realized_pnl": 10.0 # Strong signal
            }
        ]

        # Setup mock for V3 table
        mock_query_v3 = self.mock_supabase.table.return_value.select.return_value.eq.return_value
        # We need to distinguish calls.
        # But since we call table("learning_performance_summary_v3") first, we can mock based on call args?
        # Or simpler: The service calls table(name).

        # Configure the mock to return v3_rows when called with v3 table name
        def side_effect(table_name):
            mock_builder = MagicMock()
            if table_name == "learning_performance_summary_v3":
                 mock_builder.select.return_value.eq.return_value.execute.return_value = Mock(data=v3_rows)
            else:
                 # Return empty for others to ensure no interference
                 mock_builder.select.return_value.eq.return_value.execute.return_value = Mock(data=[])
            return mock_builder

        self.mock_supabase.table.side_effect = side_effect

        multipliers = self.service._get_performance_multipliers(self.user_id)

        # Case 1: debit_call
        key1 = "debit_call:paper_trading:normal"
        self.assertIn(key1, multipliers)
        self.assertAlmostEqual(multipliers[key1], 1.1, places=2)
        # Check legacy key populated from 'normal' regime
        self.assertIn(("debit_call", "paper_trading"), multipliers)
        self.assertAlmostEqual(multipliers[("debit_call", "paper_trading")], 1.1, places=2)

        # Case 2: credit_put (insufficient trades) -> Should be present and 1.0
        key2 = "credit_put:paper_trading:normal"
        self.assertIn(key2, multipliers)
        self.assertEqual(multipliers[key2], 1.0)
        # Verify legacy key is also 1.0 (since regime is normal)
        self.assertEqual(multipliers[("credit_put", "paper_trading")], 1.0)

        # Case 3: iron_condor (gated by noise check -> 1.0)
        key3 = "iron_condor:paper_trading:elevated"
        self.assertIn(key3, multipliers)
        self.assertEqual(multipliers[key3], 1.0)

        # Case 4: long_call (negative)
        key4 = "long_call:paper_trading:normal"
        self.assertIn(key4, multipliers)
        self.assertAlmostEqual(multipliers[key4], 0.75, places=2)

    def test_fallback_to_legacy(self):
        """
        Verifies that if V3 table query fails (throws exception), we fall back to learning_feedback_loops.
        """
        legacy_rows = [
             {
                "strategy": "legacy_strat",
                "window": "paper_trading",
                "total_trades": 10,
                "avg_return": 0.5, # +0.5 -> 1.5
            }
        ]

        def side_effect(table_name):
            mock_builder = MagicMock()
            if table_name == "learning_performance_summary_v3":
                 # Simulate error
                 mock_builder.select.return_value.eq.return_value.execute.side_effect = Exception("View not found")
            elif table_name == "learning_feedback_loops":
                 mock_builder.select.return_value.eq.return_value.execute.side_effect = None
                 mock_builder.select.return_value.eq.return_value.execute.return_value = Mock(data=legacy_rows)
            return mock_builder

        self.mock_supabase.table.side_effect = side_effect

        multipliers = self.service._get_performance_multipliers(self.user_id)

        # Verify we got legacy result
        self.assertIn(("legacy_strat", "paper_trading"), multipliers)
        self.assertAlmostEqual(multipliers[("legacy_strat", "paper_trading")], 1.5)

    def test_adjust_suggestion_scores_keys(self):
        """
        Tests that adjust_suggestion_scores uses the correct priority of keys.
        """
        # Mock _get_performance_multipliers to return specific keys
        self.service._get_performance_multipliers = MagicMock(return_value={
            "strat_A:window_A:normal": 1.2,
            "strat_A:window_A:unknown": 1.1,
            ("strat_A", "window_A"): 1.05
        })

        suggestions = [
            {"strategy": "strat_A", "window": "window_A", "regime": "normal", "score": 10.0},
            {"strategy": "strat_A", "window": "window_A", "regime": "shock", "score": 10.0}, # Should fallback to unknown or generic
            {"strategy": "strat_A", "window": "window_A", "regime": "unknown", "score": 10.0}
        ]

        # We need to refine the mock return value to support fallback lookup.
        # The logic in adjust_suggestion_scores:
        # 1. key = strat:window:regime
        # 2. key = strat:window:unknown
        # 3. key = (strat, window)

        # For suggestions[0] (normal):
        # key "strat_A:window_A:normal" exists -> 1.2. Score 10 -> 12.

        # For suggestions[1] (shock):
        # key "strat_A:window_A:shock" missing.
        # key "strat_A:window_A:unknown" exists -> 1.1. Score 10 -> 11.

        # For suggestions[2] (unknown):
        # key "strat_A:window_A:unknown" exists -> 1.1. Score 10 -> 11.

        adjusted = self.service.adjust_suggestion_scores(suggestions, self.user_id)

        self.assertEqual(adjusted[0]["score"], 12.0)
        self.assertEqual(adjusted[1]["score"], 11.0)
        self.assertEqual(adjusted[2]["score"], 11.0)

if __name__ == '__main__':
    unittest.main()
