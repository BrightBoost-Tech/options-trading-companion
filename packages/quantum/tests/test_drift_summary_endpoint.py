import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import sys
import os

# Ensure we can import from the parent directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api import app
from security import get_current_user

client = TestClient(app)

@pytest.fixture
def mock_supabase():
    with patch("api.supabase") as mock:
        yield mock

def test_drift_summary_endpoint(mock_supabase):
    # Override authentication
    async def mock_get_user():
        return "test_user_123"

    app.dependency_overrides[get_current_user] = mock_get_user

    # Mock DB response
    # Scenario: 4 logs
    # 1. disciplined
    # 2. impulse
    # 3. size + impulse (mixed)
    # 4. disciplined
    mock_logs = [
        {"discipline_tags": ["disciplined_execution"]},
        {"discipline_tags": ["impulse_trade"]},
        {"discipline_tags": ["size_violation", "impulse_trade"]},
        {"discipline_tags": ["disciplined_execution"]},
    ]

    mock_response = MagicMock()
    mock_response.data = mock_logs

    # Mock the chain: supabase.table("execution_drift_logs").select("*").eq(...).gte(...).execute()
    mock_chain = mock_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .gte.return_value
    mock_chain.execute.return_value = mock_response

    response = client.get("/journal/drift-summary")

    assert response.status_code == 200
    data = response.json()

    # Verify basics
    assert data["window_days"] == 7
    assert data["total_suggestions"] == 4

    # Verify counts
    # Disciplined: 1st and 4th = 2
    assert data["disciplined_execution"] == 2
    # Impulse: 2nd and 3rd = 2
    assert data["impulse_trades"] == 2
    # Size: 3rd = 1
    assert data["size_violations"] == 1

    # Verify rates (rounded to 2 decimals in implementation)
    # 2/4 = 0.5
    assert data["disciplined_rate"] == 0.5
    assert data["impulse_rate"] == 0.5
    # 1/4 = 0.25
    assert data["size_violation_rate"] == 0.25

    # Clean up
    app.dependency_overrides = {}

def test_drift_summary_empty(mock_supabase):
    async def mock_get_user():
        return "test_user_empty"
    app.dependency_overrides[get_current_user] = mock_get_user

    mock_response = MagicMock()
    mock_response.data = []

    mock_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .gte.return_value \
        .execute.return_value = mock_response

    response = client.get("/journal/drift-summary")
    assert response.status_code == 200
    data = response.json()

    assert data["total_suggestions"] == 0
    assert data["disciplined_rate"] == 0.0

    app.dependency_overrides = {}
