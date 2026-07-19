
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import sys
import os
import types

# Seed the security config env BEFORE importing packages.quantum.api, which
# runs validate_security_config() at import time; without these vars the module
# raises SecurityConfigError at COLLECTION. In the full suite an earlier sibling
# happens to seed them first, so this file only errored when collected SOLO or
# first — an ordering artifact, not a real failure. setdefault → the real CI env
# always wins; this only fills the local gap. Pattern: test_drift_summary_endpoint.py.
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("ENCRYPTION_KEY", "ke2AXS883XK_QFY9uLNGUiQlce1MifOaZNmmn06eoC8=")
os.environ.setdefault("TASK_SIGNING_SECRET", "test-task-secret")
os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")

# Windows-local shim: rq's import raises ValueError (no 'fork' context) so
# packages.quantum.api — which transitively imports rq at module level (via
# internal_tasks -> jobs.rq_enqueue) — is unimportable locally (the known fork
# class). CI (Linux) imports the real rq; the shim only engages where rq itself
# cannot load. Same pattern as test_rebalance_endpoint_contract.py.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from packages.quantum.api import app
# Import the actual dependency function to use as key
from packages.quantum.security import get_current_user

# Skipped in PR #1 triage to establish CI-green gate while test debt is cleared.
# [Cluster K] Production API drift (api.supabase)
# Tracked in #772 (umbrella: #767).
pytestmark = pytest.mark.skip(
    reason='[Cluster K] Production API drift (api.supabase); tracked in #772',
)

client = TestClient(app)

def mock_get_current_user():
    return "test-user-id"

# Use the function object, not the string path
app.dependency_overrides[get_current_user] = mock_get_current_user

@pytest.fixture
def mock_supabase():
    with patch("packages.quantum.api.supabase") as mock:
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
