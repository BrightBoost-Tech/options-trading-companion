import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from fastapi import FastAPI
from packages.quantum.optimizer import router, get_current_user_id

# Create a minimal app to test the router
app = FastAPI()
app.include_router(router)

client = TestClient(app)

def test_optimize_discrete_exception_leak():
    """
    Verifies that the /optimize/discrete endpoint does NOT leak exception details
    when an unhandled exception occurs.
    """

    # Mock payload
    payload = {
        "candidates": [],
        "constraints": {
            "max_cash": 10000.0,
            "max_vega": 500.0,
            "max_delta_abs": 100.0,
            "max_gamma": 50.0
        },
        "parameters": {
            "lambda_tail": 1.0,
            "lambda_cash": 1.0,
            "lambda_vega": 1.0,
            "lambda_delta": 1.0,
            "lambda_gamma": 1.0,
            "mode": "classical_only"
        }
    }

    # Mock the solver to raise an exception with a sensitive message
    sensitive_message = "SECRET_DB_PASSWORD_123"

    # We patch the HybridDiscreteSolver.solve method where it is called in optimizer.py
    # Since optimizer.py imports HybridDiscreteSolver, we patch it there?
    # Or patch the class method directly.

    with patch("packages.quantum.discrete.solvers.hybrid.HybridDiscreteSolver.solve") as mock_solve:
        mock_solve.side_effect = ValueError(sensitive_message)

        async def mock_get_current_user():
            return "test_user"

        app.dependency_overrides[get_current_user_id] = mock_get_current_user

        response = client.post("/optimize/discrete", json=payload)

        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")

        assert response.status_code == 500

        # THE CHECK: Ensure sensitive info is NOT in the response
        # This will FAIL currently, which confirms the vulnerability
        if sensitive_message in response.text:
            pytest.fail(f"SECURITY VULNERABILITY: Response contained sensitive message '{sensitive_message}'")

        # Also ensure it says something generic
        assert "Discrete optimization failed" in response.json()["detail"]
