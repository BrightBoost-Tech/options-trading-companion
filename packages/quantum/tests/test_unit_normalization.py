import unittest
from packages.quantum.analytics.scoring import calculate_unified_score, CONTRACT_MULTIPLIER, to_contract_dollars
from packages.quantum.common_enums import UnifiedScore, RegimeState

class TestUnitNormalization(unittest.TestCase):

    def test_to_contract_dollars(self):
        """Test conversion helper."""
        self.assertEqual(to_contract_dollars(1.5), 150.0)
        self.assertEqual(to_contract_dollars(0.0), 0.0)
        self.assertEqual(to_contract_dollars(None), 0.0)
        self.assertEqual(to_contract_dollars("1.5"), 150.0)

    def test_roi_normalization_sanity(self):
        """
        1) ROI normalization sanity:
        - ev=50.0 (contract dollars)
        - entry_cost=1.00 (per share premium, $100 contract)
        - expect ev_roi == 0.5
        """
        trade = {
            "ev": 50.0,
            "suggested_entry": 1.00,
            "strategy": "debit_call"
        }

        # entry_cost param defaults to trade['suggested_entry'] if not provided
        score = calculate_unified_score(
            trade=trade,
            regime_snapshot={"state": "normal"},
            market_data={"bid_ask_spread_pct": 0.0},
            execution_drag_estimate=0.0
        )

        # Calculate expected EV ROI points
        # Cost Basis = 1.00 * 100 = 100.0
        # EV ROI = 50.0 / 100.0 = 0.5
        # SCALING_FACTOR = 500.0 (from scoring.py)
        # Expected Points = 0.5 * 500 = 250.0

        self.assertAlmostEqual(score.components.ev, 250.0)

    def test_proxy_exec_cost_normalization(self):
        """
        2) Proxy exec cost normalization:
        - entry_cost=1.00 (per share)
        - spread_pct=0.10
        - num_legs=2
        - per-share proxy = 1.00*0.10*0.5 + 2*0.0065 = 0.05 + 0.013 = 0.063
        - contract proxy = 6.3
        Assert scoring returns execution_cost_proxy ~= 6.3
        """
        trade = {
            "ev": 100.0, # High enough to not be negative score
            "suggested_entry": 1.00,
            "strategy": "debit_spread",
            "legs": [{}, {}] # 2 legs
        }

        score = calculate_unified_score(
            trade=trade,
            regime_snapshot={"state": "normal"},
            market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=0.0, # Force proxy usage
            num_legs=2,
            entry_cost=1.00
        )

        # Check execution_cost_dollars in the returned UnifiedScore object
        # Expected: 6.3
        self.assertAlmostEqual(score.execution_cost_dollars, 6.3)

        # Also check component score impact
        # Cost ROI = 6.3 / 100.0 = 0.063
        # Cost Points = 0.063 * 500.0 = 31.5
        self.assertAlmostEqual(score.components.execution_cost, 31.5)

    def test_hard_reject_logic_helper(self):
        """
        Verify that if execution cost > EV, we can detect it via returned values.
        """
        # Case where exec cost > EV
        # EV = 5.0 (contract dollars)
        # Entry = 1.00
        # Spread = 10% -> Proxy = 6.3 (from above)
        # 6.3 > 5.0, so this trade is inefficient.

        trade = {
            "ev": 5.0,
            "suggested_entry": 1.00,
            "strategy": "debit_spread"
        }

        score = calculate_unified_score(
            trade=trade,
            regime_snapshot={"state": "normal"},
            market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=0.0,
            num_legs=2,
            entry_cost=1.00
        )

        self.assertGreater(score.execution_cost_dollars, 5.0)

if __name__ == '__main__':
    unittest.main()
