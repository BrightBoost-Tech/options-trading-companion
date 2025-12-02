import unittest
from packages.quantum.analytics.regime_scoring import ScoringEngine, ConvictionTransform
from packages.quantum.analytics.risk_manager import RiskBudgetManager, MorningManager
from packages.quantum.analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES,
    run_scoring_pipeline
)

class TestRegimeScoring(unittest.TestCase):

    def setUp(self):
        self.engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )
        self.conviction = ConvictionTransform(DEFAULT_REGIME_PROFILES)

    def test_scoring_basic(self):
        data = {
            "symbol": "TEST",
            "factors": {"trend": 80, "value": 50, "volatility": 20},
            "liquidity_tier": "top"
        }
        # Normal regime: trend 0.4, value 0.3, vol 0.3
        # Score = 0.4*80 + 0.3*50 + 0.3*20 = 32 + 15 + 6 = 53
        res = self.engine.calculate_score(data, "normal")
        self.assertAlmostEqual(res['raw_score'], 53.0)
        self.assertEqual(res['regime_used'], "normal")

    def test_scoring_regime_change(self):
        data = {
            "symbol": "TEST",
            "factors": {"trend": 80, "value": 50, "volatility": 20},
            "liquidity_tier": "top"
        }
        # High Vol regime: trend 0.2, value 0.3, vol 0.5
        # Score = 0.2*80 + 0.3*50 + 0.5*20 = 16 + 15 + 10 = 41
        res = self.engine.calculate_score(data, "high_vol")
        self.assertAlmostEqual(res['raw_score'], 41.0)

    def test_scoring_liquidity_penalty(self):
        data = {
            "symbol": "ILLIQ",
            "factors": {"trend": 100, "value": 100, "volatility": 100},
            "liquidity_tier": "lower" # 0.7 scalar
        }
        res = self.engine.calculate_score(data, "normal")
        # Raw weighted avg = 100. Scaled by 0.7 = 70.
        self.assertAlmostEqual(res['raw_score'], 70.0)

    def test_conviction_hard_floor(self):
        # Normal regime floor is 30.0
        c_i = self.conviction.get_conviction(29.0, "normal", universe_median=50.0)
        self.assertEqual(c_i, 0.0)

    def test_conviction_relativity_trap(self):
        # Crash scenario: Universe median is 20.0 (terrible).
        # My score is 25.0 (best of trash).
        # Normal Regime: floor is 30.0.
        # Pivot calc: blended = 0.5*20 + 0.5*50 = 35.
        # Mu effective = max(35, 30) = 35.
        # Raw score 25 < floor 30 -> Should be 0.0 regardless of relativity.

        c_i = self.conviction.get_conviction(25.0, "normal", universe_median=20.0)
        self.assertEqual(c_i, 0.0)

        # Now assume a regime with lower floor, e.g. "panic" floor=20.
        # Pivot calculation would differ.
        # But specifically testing the "trap" means avoiding giving high score just because > median.
        # If I have 32 (above floor 30), but median is 20.
        # blended = 35. score 32 < 35. Should be < 0.5.
        c_i_valid = self.conviction.get_conviction(32.0, "normal", universe_median=20.0)
        self.assertTrue(0.0 < c_i_valid < 0.5)

    def test_panic_regime_scaling(self):
        # Panic scale is 0.5
        # If raw score is very high, sigmoid -> 1.0. Final -> 0.5.
        c_i = self.conviction.get_conviction(100.0, "panic", universe_median=50.0)
        self.assertAlmostEqual(c_i, 0.5, delta=0.01)

    def test_pipeline_integration(self):
        universe = [
            {"symbol": "A", "factors": {"trend": 90}, "liquidity_tier": "top"},
            {"symbol": "B", "factors": {"trend": 10}, "liquidity_tier": "top"},
            {"symbol": "C", "factors": {"trend": 50}, "liquidity_tier": "top"},
        ]
        # Regime normal only cares about trend if other weights 0?
        # Default weights has trend 0.4, others non-zero.
        # Let's mock a simpler engine for this test or just use default.
        # With default, missing factors default to 0.

        results = run_scoring_pipeline(universe, "normal", self.engine, self.conviction)
        self.assertEqual(len(results), 3)
        self.assertTrue('conviction' in results[0])
        # A should have highest score, B lowest.
        self.assertTrue(results[0]['raw_score'] > results[2]['raw_score'] > results[1]['raw_score'])

class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.budgets = {
            'normal': {'trend': 0.5}
        }
        self.rm = RiskBudgetManager(self.budgets)

    def test_budget_check_pass(self):
        portfolio = {
            'equity': 10000.0,
            'max_risk_pct': 0.10, # 1000 global risk
            'factor_risk': {'trend': 200.0}
        }
        # Trend budget = 0.5 * 1000 = 500.
        # Used 200. Available 300.

        trade = {
            'max_risk': 100.0,
            'factor_contribution': {'trend': 50.0, 'vol': 10.0} # Trend is primary
        }

        self.assertTrue(self.rm.check_trade_viability(trade, portfolio, 'normal'))

    def test_budget_check_fail(self):
        portfolio = {
            'equity': 10000.0,
            'max_risk_pct': 0.10, # 1000 global risk
            'factor_risk': {'trend': 450.0}
        }
        # Trend budget = 500. Used 450. Available 50.

        trade = {
            'max_risk': 100.0, # Exceeds available
            'factor_contribution': {'trend': 50.0}
        }

        self.assertFalse(self.rm.check_trade_viability(trade, portfolio, 'normal'))

class TestMorningManager(unittest.TestCase):
    def setUp(self):
        self.mm = MorningManager(theta_sensitivity=10.0, base_floor=0.5)

    def test_high_theta_low_conviction(self):
        # NAV 10k. Theta -100. Ratio 0.01.
        # Penalty = 0.01 * 10 = 0.1.
        # Floor = 0.5 + 0.1 = 0.6.
        # Conviction 0.4.
        # Gap = 0.2. Urgency = 0.2 / 0.6 = 0.33

        pos = {'theta': -100.0}
        urgency = self.mm.get_exit_urgency(pos, current_c_i=0.4, nav=10000.0, vol_regime='normal')
        self.assertTrue(urgency > 0.0)

    def test_high_conviction_holds(self):
        # Same setup. Floor 0.6.
        # Conviction 0.8.
        # Should be 0 urgency.
        pos = {'theta': -100.0}
        urgency = self.mm.get_exit_urgency(pos, current_c_i=0.8, nav=10000.0, vol_regime='normal')
        self.assertEqual(urgency, 0.0)

if __name__ == '__main__':
    unittest.main()
