import unittest
import sys
import os

# Ensure packages is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.analytics.strategy_policy import StrategyPolicy
from packages.quantum.analytics.strategy_selector import StrategySelector

class TestStrategyPolicy(unittest.TestCase):
    def test_default_policy(self):
        policy = StrategyPolicy()
        self.assertTrue(policy.is_allowed("short_put_credit_spread"))
        self.assertTrue(policy.is_allowed("long_call_debit_spread"))

    def test_explicit_ban(self):
        policy = StrategyPolicy(banned_strategies=["iron_condor"])
        self.assertFalse(policy.is_allowed("iron_condor"))
        self.assertTrue(policy.is_allowed("short_put_credit_spread"))

    def test_category_ban_credit_spreads(self):
        policy = StrategyPolicy(banned_strategies=["credit_spreads"])

        # Credit strategies should be banned
        self.assertFalse(policy.is_allowed("short_put_credit_spread"))
        self.assertFalse(policy.is_allowed("credit_call_spread"))
        self.assertFalse(policy.is_allowed("iron_condor"))
        self.assertFalse(policy.is_allowed("short_strangle"))

        # Debit strategies should be allowed
        self.assertTrue(policy.is_allowed("long_call_debit_spread"))
        self.assertTrue(policy.is_allowed("long_put"))

    def test_normalization_and_fuzzy_matching(self):
        policy = StrategyPolicy(banned_strategies=["credit_spreads"])

        # Case insensitive
        self.assertFalse(policy.is_allowed("SHORT_PUT_CREDIT_SPREAD"))
        self.assertFalse(policy.is_allowed("Credit_Put_Spread"))

        # Space vs Underscore
        self.assertFalse(policy.is_allowed("short put credit spread"))

    def test_rejection_reason(self):
        policy = StrategyPolicy(banned_strategies=["credit_spreads", "custom_strat"])

        reason = policy.get_rejection_reason("short_put_credit_spread")
        self.assertIn("No Credit Spreads Policy", reason)

        reason = policy.get_rejection_reason("custom_strat")
        self.assertIn("explicitly banned", reason)

        self.assertIsNone(policy.get_rejection_reason("allowed_strat"))

    def test_strategy_selector_integration(self):
        selector = StrategySelector()

        # Mock high vol bullish scenario -> usually SHORT_PUT_CREDIT_SPREAD
        ticker = "SPY"
        sentiment = "BULLISH"
        iv_rank = 90.0
        price = 400.0

        # 1. Without ban
        res = selector.determine_strategy(
            ticker, sentiment, price, iv_rank, effective_regime="ELEVATED"
        )
        self.assertTrue("CREDIT" in res["strategy"] or "SHORT_PUT" in res["strategy"])

        # 2. With ban
        res_banned = selector.determine_strategy(
            ticker, sentiment, price, iv_rank, effective_regime="ELEVATED",
            banned_strategies=["credit_spreads"]
        )

        # Should NOT be a credit strategy
        # Fallback for Bullish + High Vol is likely Debit Spread or HOLD
        strat = res_banned["strategy"]
        self.assertFalse("CREDIT" in strat)

        # Verify it fell back to Debit Spread
        if strat != "HOLD":
            self.assertTrue("DEBIT" in strat)

        # 3. Verify Iron Condor ban (Neutral + High Vol)
        res_ic = selector.determine_strategy(
            ticker, "NEUTRAL", price, iv_rank, effective_regime="ELEVATED",
             banned_strategies=["credit_spreads"]
        )
        # Should be HOLD because IC is banned and no good debit neutral fallback
        self.assertEqual(res_ic["strategy"], "HOLD")
        self.assertIn("banned", res_ic["rationale"])

if __name__ == "__main__":
    unittest.main()
