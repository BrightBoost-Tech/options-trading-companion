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


from packages.quantum.agents.runner import build_agent_pipeline
import os
from unittest.mock import patch

def test_build_agent_pipeline_disabled_master():
    """Test that build_agent_pipeline returns empty list when QUANT_AGENTS_ENABLED is false."""
    with patch.dict(os.environ, {"QUANT_AGENTS_ENABLED": "false"}):
        agents = build_agent_pipeline()
        assert len(agents) == 0

def test_build_agent_pipeline_defaults():
    """Test that all agents are enabled by default if QUANT_AGENTS_ENABLED is true."""
    # Assuming QUANT_AGENTS_ENABLED defaults to False if not present, but here we set it to true.
    # Individual toggles default to True in build_agent_pipeline.
    with patch.dict(os.environ, {"QUANT_AGENTS_ENABLED": "true"}):
        # We need to ensure specific toggles are NOT set (or set to invalid), so defaults kick in.
        # patch.dict only affects what we set. If we don't set sub-toggles, os.environ.get returns None -> default True.

        # However, we must ensure we are not inheriting environment variables from the real env if any are set.
        # But for unit tests, typically they are clean.
        agents = build_agent_pipeline()

        # There are 8 agents in total
        expected_agents = 8
        assert len(agents) == expected_agents

        # Verify types
        agent_ids = [a.id for a in agents]
        assert "regime_agent" in agent_ids
        assert "vol_surface" in agent_ids
        assert "liquidity" in agent_ids
        assert "event_risk" in agent_ids
        assert "strategy_design" in agent_ids
        assert "sizing" in agent_ids
        assert "exit_plan" in agent_ids
        assert "post_trade_review" in agent_ids

def test_build_agent_pipeline_selective_disable():
    """Test disabling a specific agent via env var."""
    with patch.dict(os.environ, {
        "QUANT_AGENTS_ENABLED": "true",
        "QUANT_AGENT_LIQUIDITY_ENABLED": "false"
    }):
        agents = build_agent_pipeline()
        agent_ids = [a.id for a in agents]

        assert "liquidity" not in agent_ids
        assert "regime_agent" in agent_ids # Others should be present
        assert len(agents) == 7

def test_build_agent_pipeline_all_disabled_via_subtoggles():
    """Test disabling all agents individually results in empty list."""
    env_vars = {
        "QUANT_AGENTS_ENABLED": "true",
        "QUANT_AGENT_REGIME_ENABLED": "0",
        "QUANT_AGENT_VOL_SURFACE_ENABLED": "no",
        "QUANT_AGENT_LIQUIDITY_ENABLED": "false",
        "QUANT_AGENT_EVENT_RISK_ENABLED": "false",
        "QUANT_AGENT_STRATEGY_DESIGN_ENABLED": "false",
        "QUANT_AGENT_SIZING_ENABLED": "false",
        "QUANT_AGENT_EXIT_PLAN_ENABLED": "false",
        "QUANT_AGENT_POST_TRADE_REVIEW_ENABLED": "false",
    }
    with patch.dict(os.environ, env_vars):
        agents = build_agent_pipeline()
        assert len(agents) == 0

def test_pipeline_integration_with_runner():
    """Test that the built pipeline works with the runner."""
    # We will just use one agent enabled for simplicity
    with patch.dict(os.environ, {
        "QUANT_AGENTS_ENABLED": "true",
        "QUANT_AGENT_REGIME_ENABLED": "true",
        # Disable others
        "QUANT_AGENT_VOL_SURFACE_ENABLED": "false",
        "QUANT_AGENT_LIQUIDITY_ENABLED": "false",
        "QUANT_AGENT_EVENT_RISK_ENABLED": "false",
        "QUANT_AGENT_STRATEGY_DESIGN_ENABLED": "false",
        "QUANT_AGENT_SIZING_ENABLED": "false",
        "QUANT_AGENT_EXIT_PLAN_ENABLED": "false",
        "QUANT_AGENT_POST_TRADE_REVIEW_ENABLED": "false",
    }):
        agents = build_agent_pipeline()
        assert len(agents) == 1
        assert agents[0].id == "regime_agent"

        # Run it
        # Regime agent expects context keys or defaults
        signals, summary = AgentRunner.run_agents({}, agents)

        # Verify result
        assert summary["agent_count"] == 1
        assert "regime_agent" in signals
        # Just check it ran without error
        assert summary["vetoed"] is False # Default regime is Normal -> score 90 -> no veto
