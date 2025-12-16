
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import sys
import os


from packages.quantum.api import app
from packages.quantum.security import get_current_user, get_supabase_user_client

client = TestClient(app)

def mock_get_current_user():
    return "test-user-id"

# Global mock for the client
mock_supabase_client = MagicMock()

def mock_get_supabase_client_dep():
    return mock_supabase_client

app.dependency_overrides[get_current_user] = mock_get_current_user
app.dependency_overrides[get_supabase_user_client] = mock_get_supabase_client_dep

@pytest.fixture
def mock_supabase():
    mock_supabase_client.reset_mock()
    return mock_supabase_client

def test_drift_summary_view_success(mock_supabase):
    mock_response = MagicMock()
    mock_response.data = {
        "disciplined_count": 10,
        "impulse_count": 2,
        "size_violation_count": 1,
        "discipline_score": 0.77
    }

    mock_query = MagicMock()
    mock_query.execute.return_value = mock_response

    mock_supabase.table.return_value.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.single.return_value = mock_query

    response = client.get("/journal/drift-summary")

    assert response.status_code == 200
    data = response.json()

    total = 10 + 2 + 1
    assert data["total_suggestions"] == total
    assert data["disciplined_execution"] == 10
    assert data["impulse_trades"] == 2
    assert data["size_violations"] == 1
    assert data["disciplined_rate"] == 0.77
    assert data["impulse_rate"] == pytest.approx(2/13)

def test_drift_summary_fallback_success(mock_supabase):
    mock_view_query = MagicMock()
    mock_view_query.execute.side_effect = Exception("View not found")

    mock_logs_response = MagicMock()
    mock_logs_response.data = [
        {"discipline_tag": "disciplined_execution"},
        {"discipline_tag": "disciplined_execution"},
        {"discipline_tag": "impulse_trade"}
    ]
    mock_logs_query = MagicMock()
    mock_logs_query.execute.return_value = mock_logs_response

    def table_side_effect(name):
        if name == "discipline_score_per_user":
            m = MagicMock()
            m.select.return_value = mock_view_query
            mock_view_query.eq.return_value = mock_view_query
            mock_view_query.single.return_value = mock_view_query
            return m
        elif name == "execution_drift_logs":
            m = MagicMock()
            m.select.return_value = mock_logs_query
            mock_logs_query.eq.return_value = mock_logs_query
            mock_logs_query.gte.return_value = mock_logs_query
            return m
        return MagicMock()

    mock_supabase.table.side_effect = table_side_effect

    response = client.get("/journal/drift-summary")

    assert response.status_code == 200
    data = response.json()

    assert data["total_suggestions"] == 3
    assert data["disciplined_execution"] == 2
    assert data["impulse_trades"] == 1
    assert data["disciplined_rate"] == pytest.approx(2/3)
