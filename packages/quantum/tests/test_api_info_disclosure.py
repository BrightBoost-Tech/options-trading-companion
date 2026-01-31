
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Mock required environment variables BEFORE importing api
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
# Valid 32-byte url-safe base64 key
os.environ.setdefault("ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")
os.environ.setdefault("TASK_SIGNING_SECRET", "test-task-secret")

# Mock Supabase client creation to avoid connection errors
# Note: patch() imports the module to resolve the target.
# We need nested patches because api.py imports security modules that also create clients.
with patch("packages.quantum.security.supabase_config.create_client") as mock_cc:
    mock_cc.return_value = MagicMock()

    with patch("packages.quantum.api.create_client") as mock_create_client:
        mock_create_client.return_value = MagicMock()

        # Import app after setting env vars and patches
        from packages.quantum.api import app

client = TestClient(app)

class TestApiInfoDisclosure:

    def test_whoami_exposes_info_by_default(self):
        """
        Verify that /__whoami exposes version and server info by default (in dev/test).
        """
        response = client.get("/__whoami")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "server" in data
        assert data["server"] == "packages.quantum.api"

    def test_health_exposes_app_env_by_default(self):
        """
        Verify that /health exposes app_env by default.
        """
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "app_env" in data

    def test_whoami_hidden_in_prod(self):
        """
        Verify fix: /__whoami is 404 in production.
        """
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = client.get("/__whoami")
            assert response.status_code == 404

    def test_health_sanitized_in_prod(self):
        """
        Verify fix: /health does not return app_env in production.
        """
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "app_env" not in data
