import unittest
from packages.quantum.options_scanner import _apply_agent_constraints

class TestDefinedRiskCSPLogic(unittest.TestCase):
    def setUp(self):
        # Base candidate with require_defined_risk enabled in agent constraints
        self.base_candidate = {
            "agent_summary": {
                "active_constraints": {}  # populated by _apply
            },
            "agent_signals": {
                "mock_agent": {
                    "metadata": {
                        "constraints": {
                            "event.require_defined_risk": True
                        }
                    }
                }
            },
            "strategy_key": "unknown",
            "max_loss_per_contract": 100.0,
            "collateral_required_per_contract": 1000.0,
            "option_spread_pct": 0.01
        }

    def test_short_call_always_rejected(self):
        """Short call (single-leg) -> rejected (veto or filtered) with reason naked_short_call (implicit via None return)"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_call"
        candidate["max_loss_per_contract"] = float("inf")

        # Even with infinite cash, it should be rejected because max_loss is inf
        result = _apply_agent_constraints(candidate, portfolio_cash=100000.0)
        self.assertIsNone(result, "Short call with infinite max loss should be rejected")

    def test_short_put_sufficient_cash(self):
        """Short put (single-leg) with sufficient cash -> allowed (CSP)"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_put"
        candidate["max_loss_per_contract"] = 5000.0 # Finite
        candidate["collateral_required_per_contract"] = 5000.0

        # Sufficient cash
        result = _apply_agent_constraints(candidate, portfolio_cash=6000.0)
        self.assertIsNotNone(result, "Short put with sufficient cash should be allowed (CSP)")
        self.assertTrue(result["agent_summary"]["active_constraints"]["event.require_defined_risk"])

    def test_short_put_insufficient_cash(self):
        """Short put (single-leg) without sufficient cash -> rejected"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_put"
        candidate["max_loss_per_contract"] = 5000.0
        candidate["collateral_required_per_contract"] = 5000.0

        # Insufficient cash
        result = _apply_agent_constraints(candidate, portfolio_cash=4000.0)
        self.assertIsNone(result, "Short put without sufficient cash should be rejected")

    def test_short_put_unknown_cash(self):
        """Portfolio cash unknown -> conservative reject for CSP path"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_put"
        candidate["max_loss_per_contract"] = 5000.0
        candidate["collateral_required_per_contract"] = 5000.0

        # Unknown cash
        result = _apply_agent_constraints(candidate, portfolio_cash=None)
        self.assertIsNone(result, "Short put with unknown portfolio cash should be rejected")

    def test_long_options_allowed(self):
        """Long options -> allowed (defined risk)"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "long_call"
        candidate["max_loss_per_contract"] = 200.0
        # Collateral usually equals max loss (debit paid)
        candidate["collateral_required_per_contract"] = 200.0

        # Should be allowed regardless of cash check here?
        # Actually defined risk check doesn't block long options unless we check buying power,
        # but _apply_agent_constraints logic for defined risk only blocks NAKED shorts.
        # Long options are not "single short".

        result = _apply_agent_constraints(candidate, portfolio_cash=0.0)
        # Even with 0 cash, it passes the *defined risk* constraint check.
        # Sizing/Funding check happens later or elsewhere.
        # This constraint specifically checks for "Undefined Risk" (Naked).
        self.assertIsNotNone(result)

    def test_spreads_allowed(self):
        """Spreads/condors -> allowed (defined risk)"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "credit_spread"
        # Spreads might have "short" in legs but strategy_key contains "spread"
        # Logic: is_single_short = "short" in strategy_key and "spread" not in strategy_key ...

        candidate["max_loss_per_contract"] = 500.0
        candidate["collateral_required_per_contract"] = 500.0

        result = _apply_agent_constraints(candidate, portfolio_cash=100.0)
        self.assertIsNotNone(result, "Spreads should be allowed as defined risk")

    def test_iron_condor_allowed(self):
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "iron_condor"
        candidate["max_loss_per_contract"] = 500.0

        result = _apply_agent_constraints(candidate, portfolio_cash=100.0)
        self.assertIsNotNone(result, "Iron Condor should be allowed")

    def test_missing_collateral_fields(self):
        """Missing collateral fields -> conservative reject with reason missing_collateral"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_put"
        candidate["max_loss_per_contract"] = 5000.0
        # collateral missing
        if "collateral_required_per_contract" in candidate:
            del candidate["collateral_required_per_contract"]

        result = _apply_agent_constraints(candidate, portfolio_cash=10000.0)
        self.assertIsNone(result, "Missing collateral should trigger rejection for Short Put")

    def test_naked_short_call_explicit_strategy(self):
        """Test implicit rejection via explicit strategy check if max_loss somehow slipped"""
        candidate = self.base_candidate.copy()
        candidate["strategy_key"] = "short_call"
        candidate["max_loss_per_contract"] = 1000.0 # Wrongly finite for some reason

        # Explicit check for "call" in strategy key inside is_single_short block
        result = _apply_agent_constraints(candidate, portfolio_cash=100000.0)
        self.assertIsNone(result, "Short call should be rejected even if max_loss is finite (fallback)")

if __name__ == "__main__":
    unittest.main()
