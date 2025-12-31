import unittest
from packages.quantum.services.decision_lineage_builder import DecisionLineageBuilder

class TestDecisionLineageBuilder(unittest.TestCase):
    def test_deterministic_output(self):
        """Test that the builder produces deterministic output regardless of insertion order."""
        builder1 = DecisionLineageBuilder()
        builder1.add_agent("Scanner")
        builder1.add_agent("SizingAgent")
        builder1.add_constraint("risk_limit", 100)
        builder1.add_constraint("max_contracts", 5)

        builder2 = DecisionLineageBuilder()
        builder2.add_agent("SizingAgent")
        builder2.add_agent("Scanner")
        builder2.add_constraint("max_contracts", 5)
        builder2.add_constraint("risk_limit", 100)

        output1 = builder1.build()
        output2 = builder2.build()

        self.assertEqual(output1, output2)
        self.assertEqual(output1["agents_involved"], ["Scanner", "SizingAgent"])
        self.assertEqual(list(output1["active_constraints"].keys()), ["max_contracts", "risk_limit"])

    def test_full_lifecycle(self):
        """Test a complete lifecycle of building a lineage object."""
        builder = DecisionLineageBuilder()
        builder.set_strategy("iron_condor")
        builder.add_agent("Scanner")
        builder.add_agent("SizingAgent")
        builder.set_sizing_source("SizingAgent")
        builder.add_constraint("delta_max", 0.2)
        builder.mark_veto("RiskAgent") # Should also add to agents_involved
        builder.set_fallback("NetworkError")

        result = builder.build()

        expected = {
            "agents_involved": ["RiskAgent", "Scanner", "SizingAgent"],
            "vetoed_agents": ["RiskAgent"],
            "active_constraints": {"delta_max": 0.2},
            "strategy_chosen": "iron_condor",
            "sizing_source": "SizingAgent",
            "fallback_reason": "NetworkError"
        }

        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
