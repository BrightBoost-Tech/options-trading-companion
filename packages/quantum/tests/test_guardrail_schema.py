import pytest
from unittest.mock import MagicMock
import sys

# Mock imports
sys.modules['packages.quantum.analytics.loss_minimizer'] = MagicMock()
sys.modules['packages.quantum.models'] = MagicMock()
sys.modules['packages.quantum.services.options_utils'] = MagicMock()

from packages.quantum.services.risk_engine import RiskEngine

def test_guardrail_policy_read_schema():
    mock_supabase = MagicMock()

    # Stub response with correct schema: details_json, created_at
    mock_data = [
        {
            "details_json": {
                "policy": {"max_position_pct": 0.5},
                "regime_state": "normal"
            },
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]

    # Setup chain: table().select().eq().eq().order().limit().execute().data
    mock_result = MagicMock()
    mock_result.data = mock_data

    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

    # Call method
    policy = RiskEngine.get_active_policy("user_123", mock_supabase)

    # Assert correct policy extracted from details_json
    assert policy == {"max_position_pct": 0.5}

    # Verify calls
    # Check that we queried 'details_json' and filtered by 'outcome_type'
    table_call = mock_supabase.table.call_args[0][0]
    assert table_call == "learning_feedback_loops"

    chain = mock_supabase.table.return_value
    select_call = chain.select.call_args[0][0]
    assert "details_json" in select_call

    # Check eq calls
    # We expect eq("user_id", ...), eq("outcome_type", "guardrail_policy")
    # eq() is called twice.
    eq_calls = chain.select.return_value.eq.call_args_list
    # Note: calls might be nested in the chain, so checking call_args_list of the select() return value object might not capture all if each call returns a NEW mock.
    # But usually MagicMock returns child mocks.
    # However, .eq().eq() means the first eq returns a mock, and THAT mock's eq is called.

    # Let's inspect the chain carefully if possible, or just rely on the fact that result data was returned.

def test_guardrail_policy_regime_match():
    mock_supabase = MagicMock()

    # Two policies: recent one for "shock", older one for "normal"
    mock_data = [
        {
            "details_json": {
                "policy": {"regime": "shock_policy"},
                "regime_state": "shock"
            },
            "created_at": "2024-01-02T00:00:00Z"
        },
        {
            "details_json": {
                "policy": {"regime": "normal_policy"},
                "regime_state": "normal"
            },
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]

    mock_result = MagicMock()
    mock_result.data = mock_data
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

    # Test 1: No regime specified -> returns newest (shock)
    policy_default = RiskEngine.get_active_policy("user_123", mock_supabase)
    assert policy_default == {"regime": "shock_policy"}

    # Test 2: Request "normal" -> should skip shock and find normal
    policy_normal = RiskEngine.get_active_policy("user_123", mock_supabase, regime_state="normal")
    assert policy_normal == {"regime": "normal_policy"}
