import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.options_scanner import scan_for_opportunities, _apply_agent_constraints

class TestScannerAgentVetoConstraints(unittest.TestCase):

    def setUp(self):
        self.candidate = {
            "symbol": "TEST",
            "strategy": "short_put", # Undefined risk by default (single leg short)
            "legs": [{"side": "sell", "type": "put", "strike": 100}],
            "suggested_entry": 2.0,
            "bid_ask_spread": 0.1, # 5% spread
            "option_spread_pct": 0.05,
            "score": 80.0,
            "agent_summary": {
                "active_constraints": {},
                "vetoed": False
            },
            "agent_signals": {}
        }

    def test_veto_removes_candidate(self):
        """Test that if agent_summary has vetoed=True, the candidate is rejected."""
        self.candidate["agent_summary"]["vetoed"] = True

        result = _apply_agent_constraints(self.candidate)
        self.assertIsNone(result)

    def test_defined_risk_constraint_rejects_naked(self):
        """Test event.require_defined_risk=True rejects naked positions."""
        # Use agent_signals to trigger the constraint
        self.candidate["agent_signals"] = {
            "agent_1": {
                "metadata": {
                    "constraints": {
                        "event.require_defined_risk": True
                    }
                }
            }
        }

        # Naked short put
        self.candidate["strategy_key"] = "short_put"
        self.candidate["type"] = "credit" # Single leg credit

        result = _apply_agent_constraints(self.candidate)
        self.assertIsNone(result)

    def test_defined_risk_constraint_accepts_spread(self):
        """Test event.require_defined_risk=True accepts spreads."""
        self.candidate["agent_signals"] = {
            "agent_1": {
                "metadata": {
                    "constraints": {
                        "event.require_defined_risk": True
                    }
                }
            }
        }
        self.candidate["strategy_key"] = "credit_spread"
        # 2 legs for spread
        self.candidate["legs"].append({"side": "buy", "type": "put", "strike": 90})

        result = _apply_agent_constraints(self.candidate)
        self.assertIsNotNone(result)
        # Check that the summary was updated properly
        self.assertTrue(result["agent_summary"]["active_constraints"]["event.require_defined_risk"])

    def test_liquidity_max_spread_constraint(self):
        """Test liquidity.max_spread_pct rejects high spreads."""
        self.candidate["agent_signals"] = {
            "agent_1": {
                "metadata": {
                    "constraints": {
                        "liquidity.max_spread_pct": 0.04 # Max 4%
                    }
                }
            }
        }
        self.candidate["option_spread_pct"] = 0.05 # Actual 5%

        result = _apply_agent_constraints(self.candidate)
        self.assertIsNone(result)

        # Should pass if spread is lower
        self.candidate["option_spread_pct"] = 0.03
        result = _apply_agent_constraints(self.candidate)
        self.assertIsNotNone(result)

    def test_require_limit_orders(self):
        """Test liquidity.require_limit_orders marks suggestion."""
        self.candidate["agent_signals"] = {
            "agent_1": {
                "metadata": {
                    "constraints": {
                        "liquidity.require_limit_orders": True
                    }
                }
            }
        }

        result = _apply_agent_constraints(self.candidate)
        self.assertIsNotNone(result)
        self.assertTrue(result["order_type_force_limit"])

    def test_no_constraints_passes(self):
        """Test basic pass through."""
        result = _apply_agent_constraints(self.candidate)
        self.assertIsNotNone(result)
        self.assertFalse(result.get("order_type_force_limit", False))

    def test_precedence_rules(self):
        """Test conflict resolution."""
        # Agent A says max spread 10%
        # Agent B says max spread 2%
        # Candidate spread is 5%
        # Should be rejected (2% < 5%)
        self.candidate["agent_signals"] = {
            "agent_a": {
                "metadata": {"constraints": {"liquidity.max_spread_pct": 0.10}}
            },
            "agent_b": {
                "metadata": {"constraints": {"liquidity.max_spread_pct": 0.02}}
            }
        }
        self.candidate["option_spread_pct"] = 0.05
        result = _apply_agent_constraints(self.candidate)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
