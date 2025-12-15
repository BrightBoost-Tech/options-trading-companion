import pytest
from packages.quantum.options_scanner import _estimate_probability_of_profit

def test_pop_score_impact():
    """Test that higher scores result in higher Probability of Profit."""
    # Base candidate
    low_score_candidate = {
        "score": 50,
        "type": "debit_spread",
        "trend": "NEUTRAL"
    }
    high_score_candidate = {
        "score": 80,
        "type": "debit_spread",
        "trend": "NEUTRAL"
    }

    global_snapshot = {"state": "NORMAL"}

    p_low = _estimate_probability_of_profit(low_score_candidate, global_snapshot)
    p_high = _estimate_probability_of_profit(high_score_candidate, global_snapshot)

    assert p_high > p_low
    assert 0.01 <= p_low <= 0.99
    assert 0.01 <= p_high <= 0.99

def test_pop_strategy_adjustments():
    """Test that credit strategies get a bump and debit strategies get a penalty."""
    candidate_credit = {
        "score": 60,
        "type": "credit_spread",
        "trend": "NEUTRAL"
    }
    candidate_debit = {
        "score": 60,
        "type": "debit_spread",
        "trend": "NEUTRAL"
    }

    global_snapshot = {"state": "NORMAL"}

    p_credit = _estimate_probability_of_profit(candidate_credit, global_snapshot)
    p_debit = _estimate_probability_of_profit(candidate_debit, global_snapshot)

    # Credit spreads generally have higher PoP
    assert p_credit > p_debit

def test_pop_iron_condor():
    """Test that Iron Condor (which might only be in strategy/type name) gets credit adjustment."""
    # Case where strategy name is in 'type' but maybe 'strategy' is missing or same
    candidate_condor = {
        "score": 50,
        "type": "Iron Condor",
        "strategy": "Iron Condor", # Populate both as scanner does
        "trend": "NEUTRAL"
    }

    p = _estimate_probability_of_profit(candidate_condor)

    # Base for 50 is 0.5. Adjustment +0.08 => 0.58.
    assert abs(p - 0.58) < 0.01

    # Case where only type has it (simulating potential data mismatch)
    candidate_condor_type_only = {
        "score": 50,
        "type": "Iron Condor",
        "strategy": "",
        "trend": "NEUTRAL"
    }
    p2 = _estimate_probability_of_profit(candidate_condor_type_only)
    assert abs(p2 - 0.58) < 0.01

def test_pop_regime_impact():
    """Test that SHOCK regime reduces PoP."""
    candidate = {
        "score": 70,
        "type": "debit_spread",
        "trend": "BULLISH"
    }

    snapshot_normal = {"state": "NORMAL"}
    snapshot_shock = {"state": "SHOCK"}

    p_normal = _estimate_probability_of_profit(candidate, snapshot_normal)
    p_shock = _estimate_probability_of_profit(candidate, snapshot_shock)

    assert p_shock < p_normal

def test_pop_bounds():
    """Ensure PoP is clamped between 0.01 and 0.99."""
    # Extremely high score candidate
    super_candidate = {
        "score": 200, # Unrealistic high score
        "type": "credit_spread", # + adjustment
        "trend": "BULLISH"
    }

    # Extremely low score candidate
    terrible_candidate = {
        "score": 0,
        "type": "debit_spread", # - adjustment
        "trend": "BEARISH"
    }

    global_snapshot = {"state": "NORMAL"}

    p_super = _estimate_probability_of_profit(super_candidate, global_snapshot)
    p_terrible = _estimate_probability_of_profit(terrible_candidate, global_snapshot)

    assert p_super <= 0.99
    assert p_terrible >= 0.01
