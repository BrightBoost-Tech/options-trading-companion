import pytest
from packages.quantum.options_scanner import _validate_spread_economics

def test_validate_spread_economics_valid_debit_spread():
    # Valid Debit Call Spread
    # Long 100 Call @ 5.0, Short 105 Call @ 3.0 -> Cost = 2.0. Width = 5.0.
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 105.0, "side": "sell", "type": "call", "expiry": "2025-01-01"},
    ]
    total_cost = 2.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is True
    assert reason == ""

def test_validate_spread_economics_valid_credit_spread():
    # Valid Credit Put Spread
    # Short 100 Put @ 5.0, Long 95 Put @ 3.0 -> Cost = -2.0 (Credit). Width = 5.0.
    legs = [
        {"strike": 100.0, "side": "sell", "type": "put", "expiry": "2025-01-01"},
        {"strike": 95.0, "side": "buy", "type": "put", "expiry": "2025-01-01"},
    ]
    total_cost = -2.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is True
    assert reason == ""

def test_validate_spread_economics_zero_width():
    # Zero Width
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 100.0, "side": "sell", "type": "call", "expiry": "2025-01-01"},
    ]
    total_cost = 0.1
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "zero_width"

def test_validate_spread_economics_zero_premium():
    # Zero Premium (or cost is 0)
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 105.0, "side": "sell", "type": "call", "expiry": "2025-01-01"},
    ]
    total_cost = 0.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "zero_premium"

def test_validate_spread_economics_premium_ge_width_debit():
    # Premium >= Width (Debit)
    # Width 5, Cost 6 -> Guaranteed Loss
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 105.0, "side": "sell", "type": "call", "expiry": "2025-01-01"},
    ]
    total_cost = 6.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "premium_ge_width"

def test_validate_spread_economics_premium_ge_width_credit():
    # Premium >= Width (Credit)
    # Width 5, Credit 6 -> Guaranteed Arbitrage? (Or simply impossible/bad data)
    # Actually if credit > width, it's an arbitrage if you can fill it, but usually indicates bad data.
    # The requirement is to validate premium_share < width_share
    legs = [
        {"strike": 100.0, "side": "sell", "type": "put", "expiry": "2025-01-01"},
        {"strike": 95.0, "side": "buy", "type": "put", "expiry": "2025-01-01"},
    ]
    total_cost = -6.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "premium_ge_width"

def test_validate_spread_economics_expiry_mismatch():
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 105.0, "side": "sell", "type": "call", "expiry": "2025-02-01"},
    ]
    total_cost = 2.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "expiry_mismatch"

def test_validate_spread_economics_missing_legs():
    # Only 1 leg
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
    ]
    # For 1 leg, the function should probably return True (sanity check passed or skipped)
    # OR we define it only for 2/4 legs.
    # The requirement says "For any 2-leg spread".
    # If I pass 1 leg, it should return True,"" based on the spec "if len(legs)!=2: return True,''"
    # (assuming we only validate 2 leg spreads, or handle 4 leg separately)
    # Let's verify what the spec says: "For any 2-leg spread: ... if invalid return False".
    # Implementation Plan says: "if len(legs)!=2: return True,"""

    total_cost = 2.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is True
    assert reason == ""

def test_validate_spread_economics_missing_long_or_short_in_2leg():
    # Two long legs (no spread)
    legs = [
        {"strike": 100.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
        {"strike": 105.0, "side": "buy", "type": "call", "expiry": "2025-01-01"},
    ]
    total_cost = 8.0
    valid, reason = _validate_spread_economics(legs, total_cost)
    assert valid is False
    assert reason == "missing_long_or_short"
