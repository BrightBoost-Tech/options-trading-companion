import pytest
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal
from packages.quantum.agents.runner import AgentRunner

class MockAgent(BaseQuantAgent):
    def __init__(self, id_val, score, veto=False, reasons=None, constraints=None):
        super().__init__()
        self._id = id_val
        self._score = score
        self._veto = veto
        self._reasons = reasons or []
        self._constraints = constraints or {}

    @property
    def id(self):
        return self._id

    def evaluate(self, context):
        return AgentSignal(
            agent_id=self.id,
            score=self._score,
            veto=self._veto,
            reasons=self._reasons,
            metadata={"constraints": self._constraints}
        )

def test_runner_aggregation():
    agents = [
        MockAgent("a1", 80.0, reasons=["Reason A"]),
        MockAgent("a2", 60.0, constraints={"limit": 10})
    ]

    signals, summary = AgentRunner.run_agents({}, agents)

    assert len(signals) == 2
    assert signals["a1"]["score"] == 80.0
    assert summary["overall_score"] == 70.0 # Mean
    assert summary["vetoed"] is False
    assert "limit" in summary["active_constraints"]
    assert summary["active_constraints"]["limit"] == 10
    assert len(summary["top_reasons"]) >= 1

def test_runner_veto():
    agents = [
        MockAgent("a1", 80.0),
        MockAgent("vetoer", 0.0, veto=True, reasons=["Block!"])
    ]

    signals, summary = AgentRunner.run_agents({}, agents)

    assert summary["vetoed"] is True
    assert summary["decision"] == "reject"
    assert "overall_score" in summary # Should be calculable (e.g. 80.0 from valid agents or 0 if policy)
    # Our implementation: valid_scores only includes non-veto agents.
    # So overall_score = 80.0 (mean of a1).
    assert summary["overall_score"] == 80.0

def test_empty_agents():
    signals, summary = AgentRunner.run_agents({}, [])
    assert summary["overall_score"] == 50.0
    assert summary["vetoed"] is False
