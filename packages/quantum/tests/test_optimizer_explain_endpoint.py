
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from api import app
# Import the actual dependency function to use as key
from security import get_current_user

client = TestClient(app)

def mock_get_current_user():
    return "test-user-id"

# Use the function object, not the string path
app.dependency_overrides[get_current_user] = mock_get_current_user

@pytest.fixture
def mock_supabase():
    with patch("api.supabase") as mock:
        yield mock

def test_explain_optimizer_run_success(mock_supabase):
    mock_response = MagicMock()
    mock_response.data = [{
        "trace_id": "test-trace-123",
        "diagnostics": {
            "clamped_weights": True
        },
        "regime_context": {
            "current_regime": "high_vol"
        },
        "confidence_score": 0.85
    }]

    mock_query = MagicMock()
    mock_query.execute.return_value = mock_response

    mock_supabase.table.return_value.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.order.return_value = mock_query
    mock_query.limit.return_value = mock_query

    response = client.post("/optimizer/explain", json={"run_id": "latest"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPTIMAL"
    assert data["regime_detected"] == "high_vol"
    assert data["conviction_used"] == 0.85
    assert "Risk Guardrail: Weights clamped to safety limits" in data["active_constraints"]

def test_explain_optimizer_run_no_data(mock_supabase):
    mock_response = MagicMock()
    mock_response.data = []

    mock_query = MagicMock()
    mock_query.execute.return_value = mock_response

    mock_supabase.table.return_value.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.order.return_value = mock_query
    mock_query.limit.return_value = mock_query

    response = client.post("/optimizer/explain", json={"run_id": "latest"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPTIMAL"
    assert "No optimization run found" in data["active_constraints"][0]
