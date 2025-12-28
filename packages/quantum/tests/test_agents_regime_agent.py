import pytest
from packages.quantum.agents.agents.regime_agent import RegimeAgent
from packages.quantum.common_enums import RegimeState

class TestRegimeAgent:

    @pytest.fixture
    def agent(self):
        return RegimeAgent()

    def test_evaluate_normal_regime(self, agent):
        context = {
            "effective_regime": "normal",
            "trend_strength": 0.5,
            "volatility_flags": []
        }
        signal = agent.evaluate(context)

        assert signal.agent_id == "regime_agent"
        assert signal.score == 90.0
        assert signal.veto is False
        assert signal.metadata["constraints"]["regime.state"] == "normal"
        assert signal.metadata["constraints"]["regime.allow_new_risk"] is True
        assert signal.metadata["constraints"]["regime.bias"] == "bullish"

    def test_evaluate_shock_regime(self, agent):
        context = {
            "effective_regime": "shock",
            "trend_strength": -0.8,
            "volatility_flags": ["HV_SPIKE"]
        }
        signal = agent.evaluate(context)

        # Shock should veto and force neutral/defensive settings
        assert signal.veto is True
        assert signal.score == 0.0
        assert signal.metadata["constraints"]["regime.state"] == "shock"
        assert signal.metadata["constraints"]["regime.allow_new_risk"] is False
        assert signal.metadata["constraints"]["regime.bias"] == "neutral"
        assert "New risk blocked by regime" in signal.reasons

    def test_evaluate_volatility_flags_penalty(self, agent):
        context = {
            "effective_regime": "elevated", # Base 70
            "trend_strength": -0.5,
            "volatility_flags": ["HV_SPIKE", "GAP_DOWN"] # 2 flags * 10 = 20 penalty
        }
        signal = agent.evaluate(context)

        # 70 - 20 = 50
        assert signal.score == 50.0
        assert signal.metadata["constraints"]["regime.state"] == "elevated"
        assert signal.metadata["constraints"]["regime.bias"] == "bearish"

    def test_evaluate_suppressed_regime(self, agent):
        context = {
            "effective_regime": "suppressed",
            "trend_strength": 0.05, # Neutral trend
            "volatility_flags": []
        }
        signal = agent.evaluate(context)

        assert signal.score == 95.0
        assert signal.metadata["constraints"]["regime.state"] == "suppressed"
        assert signal.metadata["constraints"]["regime.bias"] == "neutral"

    def test_evaluate_chop_regime(self, agent):
        context = {
            "effective_regime": "chop",
            "trend_strength": 0.0,
            "volatility_flags": []
        }
        signal = agent.evaluate(context)

        assert signal.score == 50.0
        assert signal.metadata["constraints"]["regime.state"] == "chop"
        assert signal.metadata["constraints"]["regime.bias"] == "neutral"

    def test_evaluate_invalid_regime_input(self, agent):
        context = {
            "effective_regime": "INVALID_REGIME",
            "trend_strength": 0.0,
            "volatility_flags": []
        }
        # Should fallback to NORMAL
        signal = agent.evaluate(context)

        assert signal.metadata["constraints"]["regime.state"] == "normal"
        assert signal.score == 90.0

    def test_evaluate_missing_inputs(self, agent):
        context = {}
        signal = agent.evaluate(context)

        # Defaults: Normal regime, 0 trend -> Neutral, Score 90
        assert signal.metadata["constraints"]["regime.state"] == "normal"
        assert signal.metadata["constraints"]["regime.bias"] == "neutral"
        assert signal.score == 90.0
