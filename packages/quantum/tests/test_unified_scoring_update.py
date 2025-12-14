import unittest
from packages.quantum.analytics.scoring import calculate_unified_score
from packages.quantum.common_enums import UnifiedScoreComponent, RegimeState

class TestUnifiedScoringUpdate(unittest.TestCase):
    def test_calculate_unified_score_proxy_cost(self):
        """
        Tests that proxy execution cost is calculated correctly using:
        (entry_cost * bid_ask_spread_pct * 0.5) + (num_legs * 0.0065)
        """
        # Setup inputs
        # entry_cost = 1.00
        # bid_ask_spread_pct = 0.10 (10%)
        # num_legs = 2

        # Expected cost calculation:
        # width = 1.00 * 0.10 = 0.10
        # half_spread = 0.05
        # leg_fees = 2 * 0.0065 = 0.013
        # total_cost = 0.063

        entry_cost = 1.00
        spread_pct = 0.10
        num_legs = 2
        expected_cost = 0.063

        # UnifiedScore logic:
        # cost_roi = estimated_cost_per_share / cost_basis
        # cost_roi = 0.063 / 1.00 = 0.063
        # SCALING_FACTOR = 500.0
        # cost_points = 0.063 * 500.0 = 31.5
        expected_cost_points = 31.5

        trade_dict = {
            "ev": 0.5, # Dummy EV
            "suggested_entry": entry_cost,
            "bid_ask_spread": entry_cost * spread_pct, # 0.10
            "strategy": "iron_condor", # example multi-leg
            "type": "credit",
            "legs": [{}, {}] # Dummy legs, len=2
        }

        market_data = {
            "bid_ask_spread_pct": spread_pct
        }

        regime_snapshot = {
            "state": "normal"
        }

        # Act
        # We pass num_legs and entry_cost explicitly as per new requirement
        score_obj = calculate_unified_score(
            trade=trade_dict,
            regime_snapshot=regime_snapshot,
            market_data=market_data,
            execution_drag_estimate=0.0, # Force proxy calculation
            num_legs=num_legs,
            entry_cost=entry_cost
        )

        # Assert
        actual_cost_points = score_obj.components.execution_cost

        # Allow small float error
        self.assertAlmostEqual(actual_cost_points, expected_cost_points, places=2,
                               msg=f"Expected cost points {expected_cost_points} (cost {expected_cost}), got {actual_cost_points}")

if __name__ == '__main__':
    unittest.main()
