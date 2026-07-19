
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packages.quantum.optimizer import router

# Setup a test app just for the optimizer router
app = FastAPI()
app.include_router(router)
client = TestClient(app)

class TestOptimizerDiagnosticsSecurity:

    def test_endpoints_accessible_in_dev_localhost(self):
        """
        Test that endpoints are accessible in a valid dev/localhost environment.
        """
        # Default environment is dev, and TestClient is localhost/testclient.
        # So this checks the "Happy Path" for developers.

        response = client.get("/diagnostics/phase1")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "message": "Phase 1 test not modified in this update"}

        response = client.post("/diagnostics/phase2/qci_uplink")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "message": "Phase 2 test not modified"}

    @patch("packages.quantum.optimizer.is_debug_routes_enabled")
    def test_should_be_hidden_when_debug_disabled(self, mock_is_debug):
        """
        Test that endpoints return 404 when debug routes are disabled (e.g. Production).
        """
        mock_is_debug.return_value = False

        response = client.get("/diagnostics/phase1")
        assert response.status_code == 404

        response = client.post("/diagnostics/phase2/qci_uplink")
        assert response.status_code == 404

    @patch("packages.quantum.optimizer.is_debug_routes_enabled")
    @patch("packages.quantum.optimizer.is_localhost")
    def test_should_be_forbidden_when_not_localhost(self, mock_is_localhost, mock_is_debug):
        """
        Test that endpoints return 403 when not localhost, even if debug is enabled.
        """
        mock_is_debug.return_value = True
        mock_is_localhost.return_value = False

        response = client.get("/diagnostics/phase1")
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]

        response = client.post("/diagnostics/phase2/qci_uplink")
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]
