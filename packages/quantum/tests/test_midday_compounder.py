import unittest
from packages.quantum.services.analytics.small_account_compounder import SmallAccountCompounder, CapitalTier, SizingConfig

class TestSmallAccountCompounder(unittest.TestCase):

    def setUp(self):
        self.candidates = [
            {"score": 90, "ticker": "AAA"},
            {"score": 80, "ticker": "BBB"},
            {"score": 70, "ticker": "CCC"},
            {"score": 60, "ticker": "DDD"},
            {"score": 40, "ticker": "EEE"}, # Below 50 cutoff
            {"score": 85, "ticker": "FFF"},
        ]

    def test_tier_detection(self):
        self.assertEqual(SmallAccountCompounder.get_tier(500).name, "micro")
        self.assertEqual(SmallAccountCompounder.get_tier(1000).name, "small")
        self.assertEqual(SmallAccountCompounder.get_tier(4999).name, "small")
        self.assertEqual(SmallAccountCompounder.get_tier(5000).name, "standard")
        self.assertEqual(SmallAccountCompounder.get_tier(10000).name, "standard")

    def test_rank_and_select_micro_budget(self):
        capital = 500
        # Micro Tier: Base risk 5% ($25 per trade base)
        # Score 90 -> 1.12x -> 1.2x boost -> ~6.72% -> $33.60
        # Score 85 -> 1.08x -> 1.2x boost -> ~6.48% -> $32.40
        # Score 80 -> 1.04x -> 1.2x boost -> ~6.24% -> $31.20

        # Total for top 2 (AAA + FFF) = 33.6 + 32.4 = 66.0

        # Test 1: Budget 40.0 -> Only AAA fits ($33.6 < 40)
        selected = SmallAccountCompounder.rank_and_select(
            self.candidates, capital, risk_budget=40.0,
            config=SizingConfig(compounding_enabled=True)
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["ticker"], "AAA")

        # Test 2: Budget 70.0 -> AAA ($33.6) + FFF ($32.4) = 66.0 < 70. BBB ($31.2) won't fit (97.2 > 70).
        selected = SmallAccountCompounder.rank_and_select(
            self.candidates, capital, risk_budget=70.0,
            config=SizingConfig(compounding_enabled=True)
        )
        self.assertEqual(len(selected), 2)
        self.assertIn("AAA", [c["ticker"] for c in selected])
        self.assertIn("FFF", [c["ticker"] for c in selected])
        self.assertNotIn("BBB", [c["ticker"] for c in selected])

    def test_rank_and_select_standard(self):
        capital = 10000
        # Standard tier 2% ($200)
        selected = SmallAccountCompounder.rank_and_select(
            self.candidates, capital, risk_budget=5000,
            config=SizingConfig(compounding_enabled=False)
        )
        # AAA, FFF, BBB, CCC, DDD -> 5 trades
        self.assertEqual(len(selected), 5)
        tickers = [c["ticker"] for c in selected]
        self.assertIn("DDD", tickers)
        self.assertNotIn("EEE", tickers)

    def test_sizing_compounding_off(self):
        # Micro account, compounding OFF -> Should fallback to 2% base
        capital = 500
        tier = SmallAccountCompounder.get_tier(capital)
        cand = {"score": 75} # 1.0x score mult

        sizing = SmallAccountCompounder.calculate_variable_sizing(
            cand, capital, tier, compounding=False
        )

        # 2% of 500 is $10
        self.assertAlmostEqual(sizing["risk_pct"], 0.02)
        self.assertAlmostEqual(sizing["risk_budget"], 10.0)

    def test_sizing_compounding_on(self):
        # Micro account, compounding ON -> Should use 5% base
        capital = 500
        tier = SmallAccountCompounder.get_tier(capital)
        cand = {"score": 75} # 1.0x score mult

        sizing = SmallAccountCompounder.calculate_variable_sizing(
            cand, capital, tier, compounding=True
        )

        # 5% of 500 is $25
        self.assertAlmostEqual(sizing["risk_pct"], 0.05)
        self.assertAlmostEqual(sizing["risk_budget"], 25.0)

    def test_sizing_compounding_boost_high_score(self):
        # Micro account, compounding ON, High Score -> Boost
        capital = 500
        tier = SmallAccountCompounder.get_tier(capital)
        cand = {"score": 90}
        # Base 5%
        # Score 90 -> 1.12x
        # Boost: 1.2x (if score >= 80)

        sizing = SmallAccountCompounder.calculate_variable_sizing(
            cand, capital, tier, compounding=True
        )

        expected = 0.05 * 1.12 * 1.0 * 1.2
        self.assertAlmostEqual(sizing["risk_pct"], expected)

if __name__ == '__main__':
    unittest.main()
