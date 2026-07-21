"""Route-level wiring proof for GET /tasks/status/{job_run_id}.

Drives the REAL public_tasks router through a TestClient: real
``verify_task_signature`` (v4 HMAC) auth + real ``project_job_status``
redaction. Failures are injected at the boundary (missing / wrong-scope
signature, unknown / malformed id) and asserted at the TOP (HTTP status +
redacted body) — a green projection unit test alone is not a green closure on
the route (E8-3 lesson: drive the entrypoint, assert the output).

Only the DB read boundary (``JobRunStore.get_job``) is faked; no production
DB/broker is touched. Auth is exercised for real via the v4 HMAC arm, with the
signing secret and nonce store patched at the module the route closed over.
"""

import os
import sys
import types
from unittest import mock

import pytest

# --- Env + rq shim BEFORE importing the router (Windows-local rq fork class) ---
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("TASK_SIGNING_SECRET", "route-test-secret")
os.environ.setdefault("TASK_NONCE_PROTECTION", "0")

try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from packages.quantum.core.rate_limiter import limiter  # noqa: E402
from packages.quantum.security import task_signing_v4  # noqa: E402
from packages.quantum.security.task_signing_v4 import sign_task_request  # noqa: E402
from packages.quantum import public_tasks  # noqa: E402

SECRET = "route-test-secret"
JID = "11111111-1111-1111-1111-111111111111"
OTHER_JID = "22222222-2222-2222-2222-222222222222"

TERMINAL_ROW = {
    "id": JID,
    "job_name": "paper_learning_ingest",
    "status": "succeeded",
    "created_at": "2026-07-20T00:00:00Z",
    "started_at": "2026-07-20T00:00:01Z",
    "finished_at": "2026-07-20T00:00:03Z",
    "duration_ms": 1500,
    "attempt": 1,
    "idempotency_key": "2026-07-20-paper-learning-all",
    "locked_by": "worker-7",
    "payload": {"user_id": "SECRET-USER-UUID", "api_key": "sk-should-never-leak"},
    "error": {"trace": "sensitive traceback"},
    "result": {"counts": {"processed": 2}, "reason": "done", "secret": "sk-inner-leak"},
}


def _build_app():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(public_tasks.router)
    return app


def _fake_store_returning(row):
    class _Store:
        def __init__(self):
            pass

        def get_job(self, job_run_id):
            if row is not None and str(row.get("id")) == str(job_run_id):
                return row
            return None

    return _Store


def _signed_get(path, scope="tasks:job_status"):
    return sign_task_request(method="GET", path=path, body=b"", scope=scope, secret=SECRET)


def _auth_patches(row=TERMINAL_ROW):
    """Patch the signing secret, nonce store, and JobRunStore on the modules
    the route closed over. Returns a list of active context managers."""
    return [
        mock.patch.object(task_signing_v4, "get_signing_secret", return_value=SECRET),
        mock.patch.object(task_signing_v4, "check_and_store_nonce", return_value=True),
        mock.patch.object(public_tasks, "JobRunStore", _fake_store_returning(row)),
    ]


class _Ctx:
    """Enter/exit a list of context managers together."""

    def __init__(self, mgrs):
        self._mgrs = mgrs

    def __enter__(self):
        for m in self._mgrs:
            m.__enter__()
        return self

    def __exit__(self, *exc):
        for m in reversed(self._mgrs):
            m.__exit__(*exc)
        return False


def test_valid_signed_get_returns_redacted_projection():
    app = _build_app()
    path = f"/tasks/status/{JID}"
    with _Ctx(_auth_patches()):
        client = TestClient(app)
        resp = client.get(path, headers=_signed_get(path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["terminal"] is True
    assert body["duration_ms"] == 1500
    assert body["result"]["counts"] == {"processed": 2}
    assert body["reason"] == "done"
    # Redaction: no withheld field / secret leaks into the response.
    text = resp.text
    for leaked in (
        "SECRET-USER-UUID",
        "sk-should-never-leak",
        "sensitive traceback",
        "sk-inner-leak",
        "worker-7",
        "2026-07-20-paper-learning-all",
    ):
        assert leaked not in text
    for key in ("payload", "error", "idempotency_key", "locked_by"):
        assert key not in body


def test_unknown_id_returns_404():
    app = _build_app()
    path = f"/tasks/status/{OTHER_JID}"  # store only has JID
    with _Ctx(_auth_patches()):
        client = TestClient(app)
        resp = client.get(path, headers=_signed_get(path))
    assert resp.status_code == 404


def test_malformed_id_returns_404():
    app = _build_app()
    path = "/tasks/status/not-a-uuid"
    with _Ctx(_auth_patches()):
        client = TestClient(app)
        resp = client.get(path, headers=_signed_get(path))
    assert resp.status_code == 404


def test_missing_signature_headers_returns_401():
    app = _build_app()
    path = f"/tasks/status/{JID}"
    with _Ctx(_auth_patches()):
        client = TestClient(app)
        resp = client.get(path)  # no X-Task-* headers
    assert resp.status_code == 401


def test_wrong_scope_signature_returns_403():
    app = _build_app()
    path = f"/tasks/status/{JID}"
    with _Ctx(_auth_patches()):
        client = TestClient(app)
        # Signed for a different scope than the route requires.
        resp = client.get(path, headers=_signed_get(path, scope="tasks:suggestions_open"))
    assert resp.status_code == 403


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
