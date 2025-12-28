import pytest
from packages.quantum.agents.agents.strategy_design_agent import StrategyDesignAgent

@pytest.fixture
def design_agent():
    return StrategyDesignAgent()

def test_shock_regime_override(design_agent):
    context = {
        "legacy_strategy": "IRON CONDOR",
        "effective_regime": "SHOCK",
        "iv_rank": 50.0
    }
    signal = design_agent.evaluate(context)
    constraints = signal.metadata["constraints"]

    assert constraints["strategy.override_selector"] is True
    assert constraints["strategy.recommended"] == "CASH"

def test_chop_regime_long_premium_override(design_agent):
    context = {
        "legacy_strategy": "LONG CALL",
        "effective_regime": "CHOP",
        "iv_rank": 40.0
    }
    signal = design_agent.evaluate(context)
    constraints = signal.metadata["constraints"]

    assert constraints["strategy.override_selector"] is True
    assert constraints["strategy.recommended"] == "IRON CONDOR"

def test_high_iv_override(design_agent):
    context = {
        "legacy_strategy": "LONG CALL", # Debit
        "effective_regime": "BULLISH",
        "iv_rank": 70.0 # High
    }
    signal = design_agent.evaluate(context)
    constraints = signal.metadata["constraints"]

    assert constraints["strategy.override_selector"] is True
    assert constraints["strategy.recommended"] == "CREDIT PUT SPREAD" # Bullish Credit

def test_no_override(design_agent):
    context = {
        "legacy_strategy": "LONG CALL",
        "effective_regime": "BULLISH",
        "iv_rank": 30.0
    }
    signal = design_agent.evaluate(context)
    constraints = signal.metadata["constraints"]

    assert constraints["strategy.override_selector"] is False
    assert constraints["strategy.recommended"] == "LONG CALL"
