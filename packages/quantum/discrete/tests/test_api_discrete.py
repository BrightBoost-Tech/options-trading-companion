from fastapi.testclient import TestClient
from packages.quantum.api import app
from packages.quantum.discrete.models import DiscreteSolveRequest
import pytest
import os
import sys

# Ensure we can import from the root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

client = TestClient(app)

# Mock valid test user
TEST_USER_ID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"
HEADERS = {
    "X-Test-Mode-User": TEST_USER_ID,
    # "Authorization": "Bearer ... " # Test mode header should suffice if auth logic allows
}

# Add test environment variable bypass if needed
os.environ["ENABLE_DEV_AUTH_BYPASS"] = "1"


def test_optimize_discrete_endpoint():
    # Construct a valid request payload
    payload = {
        "candidates": [
            {
                "id": "trade-1",
                "symbol": "SPY",
                "side": "buy",
                "qty_max": 10,
                "ev_per_unit": 50.0,
                "premium_per_unit": 100.0,
                "delta": 0.5,
                "gamma": 0.01,
                "vega": 0.1,
                "tail_risk_contribution": 10.0,
                "metadata": {}
            },
            {
                "id": "trade-2",
                "symbol": "QQQ",
                "side": "sell",
                "qty_max": 5,
                "ev_per_unit": 20.0,
                "premium_per_unit": 40.0,
                "delta": -0.3,
                "gamma": -0.01,
                "vega": -0.05,
                "tail_risk_contribution": 5.0,
                "metadata": {}
            }
        ],
        "constraints": {
            "max_cash": 1000.0,
            "max_vega": 100.0,
            "max_delta_abs": 100.0,
            "max_gamma": 100.0
        },
        "parameters": {
            "lambda_tail": 1.0,
            "lambda_cash": 0.1,
            "lambda_vega": 0.1,
            "lambda_delta": 0.1,
            "lambda_gamma": 0.1,
            "num_samples": 20,
            "mode": "classical_only",
            "max_candidates_for_dirac": 40,
            "max_dirac_calls": 2,
            "dirac_timeout_s": 10
        }
    }

    # Make the request
    # Since auth logic might require real supabase validation, we rely on X-Test-Mode-User
    # and hope the dev bypass works or the test user is valid.
    # The `auth_debug` endpoint logic suggests we need to be localhost and dev env.

    # We might need to override the dependency get_current_user_id for pure unit testing
    # but here we are using the real app.
    # Let's try to override the dependency.

    from packages.quantum.security import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    response = client.post("/optimize/discrete", json=payload, headers=HEADERS)

    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()

    assert data["status"] == "ok"
    assert "selected_trades" in data
    assert "metrics" in data
    assert data["strategy_used"] == "classical" # as per our stub

    # Check logic (greedy selection)
    # trade-1 has EV/Cost = 0.5, trade-2 has EV/Cost = 0.5.
    # trade-1 cost 100, max_cash 1000. Should pick 10 units of trade-1 = 1000 cost.
    # trade-2 not picked because cash exhausted?
    # Our simple stub sorts by ratio. Stability of sort?
    # Actually both are 0.5.

    # Verify at least something is selected
    assert len(data["selected_trades"]) > 0

    metrics = data["metrics"]
    assert metrics["expected_profit"] > 0
    assert metrics["runtime_ms"] >= 0

def test_optimize_discrete_validation_error():
    # Invalid payload (missing constraints)
    payload = {
        "candidates": [],
        # "constraints": ... missing
        "parameters": {
            "lambda_tail": 1.0,
            "lambda_cash": 0.1,
            "lambda_vega": 0.1,
            "lambda_delta": 0.1,
            "lambda_gamma": 0.1,
            "num_samples": 20,
            "mode": "classical_only",
            "max_candidates_for_dirac": 40,
            "max_dirac_calls": 2,
            "dirac_timeout_s": 10
        }
    }

    response = client.post("/optimize/discrete", json=payload, headers=HEADERS)
    assert response.status_code == 422
