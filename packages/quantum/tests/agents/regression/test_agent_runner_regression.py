import json
import os
import pytest
from typing import Dict, Any, List
from unittest.mock import MagicMock

# Agent Imports
from packages.quantum.agents.core import AgentSignal, BaseQuantAgent
from packages.quantum.agents.runner import AgentRunner

# Helper for fixtures
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def load_or_update_fixture(fixture_name: str, results: List[Dict[str, Any]]):
    filepath = os.path.join(FIXTURE_DIR, fixture_name)

    if os.environ.get("UPDATE_GOLDEN"):
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        return results

    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        return results

    with open(filepath, "r") as f:
        return json.load(f)

class MockAgent(BaseQuantAgent):
    def __init__(self, agent_id: str, signal: AgentSignal):
        super().__init__()
        self._id = agent_id
        self._signal = signal

    @property
    def id(self) -> str:
        return self._id

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        return self._signal

def run_runner_scenarios(scenarios: List[Dict[str, Any]]):
    results = []

    for scenario in scenarios:
        name = scenario["name"]
        agents_config = scenario["agents"] # List of {id, score, veto, constraints}

        # Build Mock Agents
        agents = []
        for ac in agents_config:
            sig = AgentSignal(
                agent_id=ac["id"],
                score=ac.get("score", 50.0),
                veto=ac.get("veto", False),
                reasons=ac.get("reasons", []),
                metadata={"constraints": ac.get("constraints", {})}
            )
            agents.append(MockAgent(ac["id"], sig))

        # Run Runner
        signals, summary = AgentRunner.run_agents({}, agents)

        results.append({
            "name": name,
            "summary": summary,
            "signals": signals
        })

    return results

def assert_results_match(actual, expected):
    assert len(actual) == len(expected)
    for act, exp in zip(actual, expected):
        assert act["name"] == exp["name"]

        # Summary checks
        assert act["summary"]["vetoed"] == exp["summary"]["vetoed"]
        assert act["summary"]["decision"] == exp["summary"]["decision"]
        assert act["summary"]["overall_score"] == pytest.approx(exp["summary"]["overall_score"], 0.1)

        # Constraints check (Constraint Precedence)
        act_const = act["summary"]["active_constraints"]
        exp_const = exp["summary"]["active_constraints"]
        for k, v in exp_const.items():
            assert act_const.get(k) == v, f"Constraint precedence failed for {k} in {act['name']}"

        # Veto behavior check
        if exp["summary"]["vetoed"]:
             assert act["summary"]["decision"] == "reject"

# ================= TESTS =================

def test_agent_runner_behavior():
    scenarios = [
        {
            "name": "all_pass_consensus",
            "agents": [
                {"id": "agent1", "score": 80.0},
                {"id": "agent2", "score": 90.0}
            ]
        },
        {
            "name": "single_veto_kills_deal",
            "agents": [
                {"id": "agent1", "score": 90.0},
                {"id": "agent2", "score": 10.0, "veto": True}
            ]
        },
        {
            "name": "multi_veto",
            "agents": [
                {"id": "agent1", "score": 10.0, "veto": True},
                {"id": "agent2", "score": 10.0, "veto": True}
            ]
        },
        {
            "name": "warning_low_score",
            "agents": [
                {"id": "agent1", "score": 30.0},
                {"id": "agent2", "score": 40.0}
            ]
        },
        {
            "name": "constraint_precedence_last_wins",
            "agents": [
                {
                    "id": "agent_early",
                    "score": 50.0,
                    "constraints": {"max_risk": 0.05}
                },
                {
                    "id": "agent_late",
                    "score": 50.0,
                    "constraints": {"max_risk": 0.02} # Should override
                }
            ]
        },
        {
            "name": "constraint_merging_disjoint",
            "agents": [
                {
                    "id": "agent1",
                    "score": 50.0,
                    "constraints": {"param_a": 1}
                },
                {
                    "id": "agent2",
                    "score": 50.0,
                    "constraints": {"param_b": 2}
                }
            ]
        }
    ]

    results = run_runner_scenarios(scenarios)

    # Check against golden fixture
    expected = load_or_update_fixture("agent_runner.json", results)
    assert_results_match(results, expected)
