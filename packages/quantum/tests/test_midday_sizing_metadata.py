import pytest
import sys
import os

# Ensure packages.quantum can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.services.workflow_orchestrator import postprocess_midday_sizing

def test_sizing_metadata_fields_are_preserved():
    # Setup initial sizing dictionary (as returned by sizing_engine)
    initial_sizing = {
        "contracts": 2,
        "capital_required": 500.0,
        "max_loss_total": 750.0, # e.g. credit spread or specific risk profile
        "reason": "Test"
    }

    # Run post-processing using the REAL production function
    result = postprocess_midday_sizing(initial_sizing.copy(), max_loss_per_contract=375.0)

    # Assertions
    # 1. max_loss_total should remain 750.0, NOT be overwritten by capital_required (500.0)
    assert result["max_loss_total"] == 750.0, \
        f"max_loss_total should be 750.0, got {result['max_loss_total']}"

    # 2. capital_required_total should be present and equal to capital_required
    assert result["capital_required_total"] == 500.0, \
        f"capital_required_total should be 500.0, got {result.get('capital_required_total')}"

def test_missing_max_loss_total_is_computed():
    # Setup sizing without max_loss_total (simulate older sizing engine or edge case)
    initial_sizing = {
        "contracts": 3,
        "capital_required": 100.0,
        # max_loss_total missing
    }

    max_loss_per = 50.0
    result = postprocess_midday_sizing(initial_sizing.copy(), max_loss_per_contract=max_loss_per)

    assert result["max_loss_total"] == 150.0 # 3 * 50
    assert result["capital_required_total"] == 100.0
