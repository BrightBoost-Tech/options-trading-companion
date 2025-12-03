import pytest
from unittest.mock import MagicMock
from analytics.iv_regime_service import IVRegimeService

def test_iv_regime_classification():
    # Helper to access the static/class method logic if available,
    # or instance method.

    mock_supabase = MagicMock()
    service = IVRegimeService(mock_supabase)

    # Mock scanner_universe response
    # The service code directly returns what is in the DB.
    # It does NOT calculate regime on the fly.
    # So we must provide iv_regime in the mock data.

    mock_execute = MagicMock()
    mock_execute.data = [
        {"symbol": "LOW", "iv_rank": 10, "iv_regime": "suppressed"},
        {"symbol": "MID", "iv_rank": 40, "iv_regime": "normal"},
        {"symbol": "HIGH", "iv_rank": 80, "iv_regime": "elevated"},
        {"symbol": "NONE", "iv_rank": None, "iv_regime": None}
    ]

    mock_supabase.table.return_value \
        .select.return_value \
        .in_.return_value \
        .execute.return_value = mock_execute

    ctx = service.get_iv_context_for_symbols(["LOW", "MID", "HIGH", "NONE"])

    # Check assertions.
    assert ctx["LOW"]["iv_regime"] == "suppressed"
    assert ctx["MID"]["iv_regime"] == "normal"
    assert ctx["HIGH"]["iv_regime"] == "elevated"
    assert ctx["NONE"]["iv_regime"] is None
