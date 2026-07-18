import os
import sys
import types

import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Environment BEFORE importing the app module. packages.quantum.api runs
# validate_security_config() at import time; without these vars the module
# raises SecurityConfigError at COLLECTION. In the full suite an earlier
# sibling (test_rebalance_endpoint_contract.py / test_api_info_disclosure.py)
# happens to seed them first, so this file only errored when collected SOLO
# or first — an ordering artifact, not a real failure. setdefault → the real
# CI env always wins; this only fills the local gap.
# ---------------------------------------------------------------------------
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault(
    "ENCRYPTION_KEY", "ke2AXS883XK_QFY9uLNGUiQlce1MifOaZNmmn06eoC8="
)
os.environ.setdefault("TASK_SIGNING_SECRET", "test-task-secret")
os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")

# Windows-local shim: rq's import raises ValueError (no 'fork' context) so
# packages.quantum.api — which transitively imports rq at module level — is
# unimportable locally (the known 9-file fork class). CI (Linux) imports the
# real rq; the shim only engages where rq itself cannot load.
# Pattern copied from test_ops_health_q30_dedup.py /
# test_rebalance_endpoint_contract.py.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from fastapi.testclient import TestClient  # noqa: E402

from packages.quantum.api import app  # noqa: E402
from packages.quantum.security import (  # noqa: E402
    get_current_user,
    get_supabase_user_client,
)

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
    # Re-assert the auth overrides per test. `app` is a process-global shared
    # with every other api-importing test; a sibling's teardown that deletes
    # get_current_user / get_supabase_user_client overrides by __qualname__
    # (e.g. test_rebalance_endpoint_contract.py) would otherwise strand these
    # tests at 401 whenever it runs first — an ordering artifact, not a real
    # failure. This keeps the file order-independent.
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_supabase_user_client] = mock_get_supabase_client_dep
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
