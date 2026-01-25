import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# 1. Setup Environment Variables for Validation
os.environ["SUPABASE_JWT_SECRET"] = "test-secret"
os.environ["NEXT_PUBLIC_SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_ANON_KEY"] = "test-anon-key"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"
os.environ["ENCRYPTION_KEY"] = "ke2AXS883XK_QFY9uLNGUiQlce1MifOaZNmmn06eoC8="
os.environ["TASK_SIGNING_SECRET"] = "test-task-secret"
os.environ["POLYGON_API_KEY"] = "test-polygon-key"
os.environ["APP_ENV"] = "production" # Simulate production to ensure we mask errors

# 2. Import App
from packages.quantum.api import app
from packages.quantum.security import get_current_user, get_supabase_user_client
import packages.quantum.optimizer as optimizer_module

# Mock the missing function calculate_dynamic_target in optimizer module
# This fixes the ImportError in the broken api.py code, allowing us to test the leak.
optimizer_module.calculate_dynamic_target = MagicMock(return_value=0.1)

client = TestClient(app)

# 3. Mocks
@pytest.fixture
def mock_auth():
    async def mock_get_user():
        return "test_user_id"

    app.dependency_overrides[get_current_user] = mock_get_user
    yield
    app.dependency_overrides = {}

@pytest.fixture
def mock_supabase():
    mock = MagicMock()

    def mock_get_client():
        return mock

    app.dependency_overrides[get_supabase_user_client] = mock_get_client
    return mock

def test_preview_rebalance_leak(mock_auth, mock_supabase):
    sensitive_info = "SECRET_KEY_PREVIEW_123"

    with patch("packages.quantum.optimizer._compute_portfolio_weights") as mock_opt:
        mock_opt.side_effect = Exception(f"Optimizer failed: {sensitive_info}")

        # Mock supabase response for positions
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"symbol": "SPY", "quantity": 10, "current_value": 1000, "user_id": "test_user_id"}
        ]

        # Patch RiskBudgetEngine to avoid TypeError in current broken code (and ensure we hit the optimizer)
        with patch("packages.quantum.api.RiskBudgetEngine") as MockRiskEngine:
            MockRiskEngine.return_value.compute.return_value = MagicMock()

            # Ensure group_spread_positions returns something so we don't exit early
            with patch("packages.quantum.api.group_spread_positions") as mock_group:
                mock_spread = MagicMock()
                mock_spread.ticker = "SPY"
                mock_spread.current_value = 1000
                mock_spread.spread_type = "vertical"
                mock_spread.underlying = "SPY"
                mock_spread.legs = []
                mock_spread.quantity = 1
                mock_spread.net_cost = 100
                mock_spread.delta = 0.5
                mock_spread.gamma = 0.05
                mock_spread.vega = 0.1
                mock_spread.theta = -0.1
                # Mock dict method for model conversion if needed
                mock_spread.dict.return_value = {
                    "ticker": "SPY", "current_value": 1000, "spread_type": "vertical",
                    "underlying": "SPY", "legs": [], "quantity": 1, "net_cost": 100,
                    "delta": 0.5, "gamma": 0.05, "vega": 0.1, "theta": -0.1
                }

                # We need it to be convertible to Spread(**s)
                # But group_spread_positions returns a list of DICTS usually.
                mock_group.return_value = [{
                    "id": "test-spread-id",
                    "user_id": "test_user_id",
                    "ticker": "SPY",
                    "spread_type": "vertical",
                    "underlying": "SPY",
                    "legs": [],
                    "quantity": 1,
                    "net_cost": 100,
                    "current_value": 1000,
                    "delta": 0.5,
                    "gamma": 0.05,
                    "vega": 0.1,
                    "theta": -0.1
                }]

                response = client.post("/rebalance/preview")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"

            # ASSERT SECURE BEHAVIOR: Sensitive info should NOT be present in production
            assert sensitive_info not in data["message"], f"Leaked sensitive info in production! Got: {data['message']}"
            assert data["message"] == "Optimization failed" or data["message"] == "Internal Server Error"

def test_analytics_behavior_leak(mock_auth, mock_supabase):
    sensitive_info = "SECRET_KEY_ANALYTICS_456"

    with patch("packages.quantum.analytics_endpoints.BehaviorAnalysisService") as MockService:
        instance = MockService.return_value
        instance.get_behavior_summary.side_effect = Exception(sensitive_info)

        response = client.get("/analytics/behavior?window=7d")

        assert response.status_code == 500
        # ASSERT SECURE BEHAVIOR
        assert sensitive_info not in response.text, "Leaked sensitive info in analytics endpoint!"
        assert "Internal Server Error" in response.json()["detail"]

def test_validation_run_leak(mock_auth, mock_supabase):
    sensitive_info = "SECRET_KEY_VALIDATION_789"

    payload = {
        "mode": "paper"
    }

    with patch("packages.quantum.validation_endpoints.GoLiveValidationService") as MockService:
        instance = MockService.return_value
        instance.eval_paper_forward_checkpoint.side_effect = Exception(sensitive_info)

        response = client.post("/validation/run", json=payload)

        assert response.status_code == 500
        # ASSERT SECURE BEHAVIOR
        assert sensitive_info not in response.text, "Leaked sensitive info in validation endpoint!"
        assert "Internal Server Error" in response.json()["detail"]
