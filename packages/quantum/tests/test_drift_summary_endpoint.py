import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# We need to make sure we can import from api
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api import app, get_current_user

# Mock authentication to bypass JWT check
app.dependency_overrides[get_current_user] = lambda: "test-user-id"

client = TestClient(app)

@patch("api.supabase")
def test_drift_summary_view_success(mock_supabase):
    """
    Test that the endpoint returns data from the view when available.
    """
    # Create a mock chain for the view query
    # supabase.table("discipline_score_per_user").select(...).eq(...).single().execute()

    mock_table_view = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_single = MagicMock()
    mock_execute = MagicMock()

    # Configure the successful return
    mock_execute.data = {
        "window_days": 7,
        "total_suggestions": 10,
        "disciplined_execution": 7,
        "impulse_trades": 2,
        "size_violations": 1,
        "disciplined_rate": 0.7,
        "impulse_rate": 0.2,
        "size_violation_rate": 0.1,
    }

    mock_supabase.table.return_value = mock_table_view
    mock_table_view.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.single.return_value = mock_single
    mock_single.execute.return_value = mock_execute

    response = client.get("/journal/drift-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["window_days"] == 7
    assert data["total_suggestions"] == 10
    assert data["disciplined_execution"] == 7
    assert data["impulse_trades"] == 2
    assert data["size_violations"] == 1
    assert data["disciplined_rate"] == 0.7
    assert data["impulse_rate"] == 0.2
    assert data["size_violation_rate"] == 0.1

    # Verify correct table was called
    mock_supabase.table.assert_called_with("discipline_score_per_user")

@patch("api.supabase")
def test_drift_summary_fallback(mock_supabase):
    """
    Test that the endpoint falls back to execution_drift_logs if the view fails.
    """
    # Define side effect for supabase.table
    def table_side_effect(name):
        if name == "discipline_score_per_user":
            raise Exception("View does not exist")
        elif name == "execution_drift_logs":
            return mock_table_logs
        return MagicMock()

    mock_supabase.table.side_effect = table_side_effect

    # Setup mock for fallback logs query
    # supabase.table("execution_drift_logs").select(...).eq(...).gte(...).execute()
    mock_table_logs = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_gte = MagicMock()
    mock_execute = MagicMock()

    mock_table_logs.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.gte.return_value = mock_gte
    mock_gte.execute.return_value = mock_execute

    # 3 disciplined, 1 impulse
    mock_execute.data = [
        {"tag": "disciplined_execution"},
        {"tag": "disciplined_execution"},
        {"tag": "disciplined_execution"},
        {"tag": "impulse_trade"}
    ]

    response = client.get("/journal/drift-summary")

    assert response.status_code == 200
    data = response.json()

    # 3 + 1 = 4 total
    assert data["total_suggestions"] == 4
    assert data["disciplined_execution"] == 3
    assert data["impulse_trades"] == 1
    assert data["size_violations"] == 0

    assert data["disciplined_rate"] == 0.75  # 3/4
    assert data["impulse_rate"] == 0.25      # 1/4
    assert data["size_violation_rate"] == 0.0
