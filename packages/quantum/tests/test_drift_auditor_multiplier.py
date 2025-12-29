import sys
import os
import pytest
from unittest.mock import MagicMock

# Add packages/quantum to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from packages.quantum.analytics.drift_auditor import _calculate_notional_size

def test_drift_auditor_multiplier_equity():
    """
    Test that equity symbols get a multiplier of 1.
    """
    holding = {
        "symbol": "AAPL",
        "quantity": 10,
        "current_price": 150.0,
        "current_value": 1500.0
    }
    # 10 * 150 * 1 = 1500
    assert _calculate_notional_size(holding) == 1500.0

def test_drift_auditor_multiplier_option():
    """
    Test that option symbols get a multiplier of 100.
    """
    # OCC Option Symbol: O:AAPL230616C00150000
    # Strike 150.
    holding = {
        "symbol": "O:AAPL230616C00150000",
        "quantity": 1,
        "current_price": 5.0, # Option price per share
        "current_value": 500.0 # Total value
    }
    # 1 * 5 * 100 = 500
    assert _calculate_notional_size(holding) == 500.0

def test_drift_auditor_multiplier_malformed_heuristic_failure():
    """
    Test a case where the old heuristic would fail (incorrectly apply 100x),
    but the new canonical logic should correctly apply 1x.

    Old heuristic: len > 6 and has digit.
    Symbol: "STOCK1" (len 6, has digit) -> Old: 1 (len must be > 6, so 7+).
    Symbol: "LONGSTOCK1" (len 10, has digit) -> Old: 100.

    We want "LONGSTOCK1" to be treated as equity (multiplier 1) because it's not a valid OCC string.
    """
    holding = {
        "symbol": "LONGSTOCK1",
        "quantity": 10,
        "current_price": 10.0,
        "current_value": 100.0
    }

    # If heuristic is still in place (len > 6 and digit), this will return 10 * 10 * 100 = 10000.
    # We want it to be 100.

    # NOTE: This test is expected to FAIL before the fix if the heuristic is present.
    # After fix, it should PASS.
    notional = _calculate_notional_size(holding)
    assert notional == 100.0, f"Expected 100.0, got {notional}. Heuristic likely incorrectly applied."

def test_drift_auditor_multiplier_suggestion_option():
    """
    Test calculation for suggestion (no current_value, uses order_json).
    """
    suggestion = {
        "strategy": "long_call",
        "ticker": "AAPL",
        "order_json": {
            "limit_price": 5.0,
            "quantity": 2
        }
    }
    # 2 * 5 * 100 = 1000
    assert _calculate_notional_size(suggestion) == 1000.0

def test_drift_auditor_multiplier_suggestion_equity():
    """
    Test calculation for suggestion (equity).
    """
    suggestion = {
        "strategy": "equity_buy",
        "ticker": "AAPL",
        "order_json": {
            "limit_price": 150.0,
            "quantity": 10
        }
    }
    # 10 * 150 * 1 = 1500
    assert _calculate_notional_size(suggestion) == 1500.0
