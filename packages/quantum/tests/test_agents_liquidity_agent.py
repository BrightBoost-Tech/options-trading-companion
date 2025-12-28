import pytest
import os
from unittest.mock import patch
from packages.quantum.agents.agents.liquidity_agent import LiquidityAgent

# Helper to create context
def create_context(legs):
    return {"legs": legs}

@pytest.fixture
def agent():
    return LiquidityAgent()

def test_liquidity_agent_identification(agent):
    assert agent.id == "liquidity"

def test_tight_spreads_pass(agent):
    # Bid 9.95, Ask 10.05, Mid 10.00 -> Spread 0.1 / 10.0 = 1%
    # Threshold default 12%
    legs = [{"bid": 9.95, "ask": 10.05, "mid": 10.00}]
    signal = agent.evaluate(create_context(legs))

    assert signal.veto is False
    assert signal.score > 80
    assert signal.metadata["liquidity.observed_spread_pct"] == pytest.approx(0.01)
    # Check constraints wrapper
    assert "constraints" in signal.metadata
    assert signal.metadata["constraints"]["liquidity.observed_spread_pct"] == pytest.approx(0.01)
    assert signal.metadata["constraints"]["liquidity.require_limit_orders"] is True

def test_wide_spread_veto(agent):
    # Bid 8.00, Ask 12.00, Mid 10.00 -> Spread 4.0 / 10.0 = 40%
    # Threshold 12%
    legs = [{"bid": 8.00, "ask": 12.00, "mid": 10.00}]
    signal = agent.evaluate(create_context(legs))

    assert signal.veto is True
    assert signal.score == 0.0
    assert any("exceeds limit" in r for r in signal.reasons)

def test_missing_quotes_penalty(agent):
    # One good leg, one missing
    legs = [
        {"bid": 9.95, "ask": 10.05, "mid": 10.00},
        {"bid": None, "ask": None, "mid": None}
    ]
    signal = agent.evaluate(create_context(legs))

    assert signal.veto is False # Not > 50% missing (wait 1/2 is not > 1/2)
    assert "Missing/Invalid quotes" in str(signal.reasons)
    assert signal.score < 100 # Should be penalized

def test_too_many_missing_veto(agent):
    # 2/3 missing -> > 50%
    legs = [
        {"bid": 9.95, "ask": 10.05, "mid": 10.00},
        {"bid": None, "ask": None},
        {"bid": None, "ask": None}
    ]
    signal = agent.evaluate(create_context(legs))

    assert signal.veto is True
    assert "Too many missing" in str(signal.reasons)

def test_invalid_quotes_edge_cases(agent):
    # Mid <= 0
    # Crossed market (Ask < Bid)
    legs = [
        {"bid": 10, "ask": 10, "mid": 0}, # Invalid
        {"bid": 10, "ask": 9, "mid": 9.5}  # Invalid
    ]
    signal = agent.evaluate(create_context(legs))

    assert signal.veto is True # All invalid
    assert "No valid quotes" in str(signal.reasons)

def test_empty_legs(agent):
    signal = agent.evaluate(create_context([]))
    assert signal.veto is True
    assert "No legs" in str(signal.reasons)

@patch.dict(os.environ, {"QUANT_AGENT_LIQUIDITY_MAX_SPREAD_PCT": "0.05"})
def test_custom_threshold_env():
    # Re-init agent to pick up env
    agent = LiquidityAgent()
    # Spread 8%
    legs = [{"bid": 9.6, "ask": 10.4, "mid": 10.0}] # 0.8 diff / 10 = 8%

    signal = agent.evaluate(create_context(legs))
    assert signal.veto is True
    assert "exceeds limit 5.0%" in str(signal.reasons)

@patch.dict(os.environ, {"QUANT_AGENT_LIQUIDITY_MODE": "worst"})
def test_worst_case_mode():
    agent = LiquidityAgent()
    # Leg 1: 1% spread (Pass)
    # Leg 2: 20% spread (Fail)
    legs = [
        {"bid": 9.95, "ask": 10.05, "mid": 10.00},
        {"bid": 8.00, "ask": 10.00, "mid": 9.00} # 2/9 = 22%
    ]

    signal = agent.evaluate(create_context(legs))
    assert signal.metadata["liquidity.mode"] == "worst"
    assert signal.veto is True # Because "worst" spread is 22% > 12%

def test_median_mode_default(agent):
    # Leg 1: 1%
    # Leg 2: 1%
    # Leg 3: 20% (Outlier)
    # Median should be 1%, so Pass
    legs = [
        {"bid": 9.95, "ask": 10.05, "mid": 10.00},
        {"bid": 9.95, "ask": 10.05, "mid": 10.00},
        {"bid": 8.00, "ask": 10.00, "mid": 9.00}
    ]

    signal = agent.evaluate(create_context(legs))
    assert signal.metadata["liquidity.mode"] == "median"
    assert signal.veto is False
    assert signal.metadata["liquidity.observed_spread_pct"] == pytest.approx(0.01)
