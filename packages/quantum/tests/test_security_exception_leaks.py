"""Security contract: endpoint exceptions must NOT leak internal detail
(secrets, connection strings, stack context) in production error payloads.

REBUILT 2026-07-17 (Lane 4A test-honesty; was module-skipped in the #774
cluster since the PR #1 triage). The original file mocked AROUND the
pre-#1242 rebalance breakage ("Patch RiskBudgetEngine to avoid TypeError in
current broken code") and injected a fake ``calculate_dynamic_target`` into
the optimizer module to paper over a then-broken import — both stale, both
gone. #1242 repaired the routes; this rebuild drives the REAL routes:

  - failure injected at its ORIGIN (the optimizer callee / the service the
    endpoint delegates to), truth asserted at the TOP (the HTTP payload);
  - every leak assertion asserts against the WHOLE response body, plus a
    call-count proof the injected failure actually reached the route (the
    masked 500 cannot be produced by anything upstream of the injection);
  - dependency overrides are resolved from the LIVE route objects
    (test_rebalance_endpoint_contract.py pattern — CI proved module-level
    imported symbols can be stale after collection-time patch leakage);
  - the rebalance harness is IMPORTED from
    test_rebalance_endpoint_contract.py rather than re-implemented, so one
    wiring owns that route's boundary fakes;
  - APP_ENV=production is scoped per-request via mock.patch.dict — the old
    module-level ``os.environ["APP_ENV"] = "production"`` bled into every
    later test module in the session.

Original security assertions preserved (none diluted):
  1. /rebalance/preview — optimizer exception text absent; typed
     "Optimization failed" message.
  2. /analytics/behavior — service exception text absent; 500 with
     "Internal Server Error".
  3. /validation/run (mode=paper) — service exception text absent; 500
     with "Internal Server Error".
"""

import contextlib
import os
import sys
import types
from unittest import mock

# ---------------------------------------------------------------------------
# Environment BEFORE importing the app module (setdefault — never bleed).
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

# Windows-local shim: rq's import raises where no 'fork' context exists, so
# packages.quantum.api is unimportable locally (the known 9-file fork
# class). CI (Linux) imports the real rq; the shim only engages where rq
# itself cannot load. Same pattern as test_rebalance_endpoint_contract.py.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from fastapi.testclient import TestClient  # noqa: E402

from packages.quantum.api import app  # noqa: E402
from packages.quantum.core.rate_limiter import limiter  # noqa: E402

# The rebalance route is 5/minute rate-limited and this module plus the
# contract module drive it repeatedly in one session. Not under test here.
limiter.enabled = False

client = TestClient(app)

USER_ID = "test-user-security"
_PROD = {"APP_ENV": "production"}


# ---------------------------------------------------------------------------
# Route-resolved dependency overrides (immune to import/patch timing).
# ---------------------------------------------------------------------------
_AUTH_QUALNAMES = ("get_current_user", "get_supabase_user_client")


def _route_dep_targets(paths):
    targets = set()
    for r in app.routes:
        if getattr(r, "path", "") in paths:
            for d in r.dependant.dependencies:
                if getattr(d.call, "__qualname__", "") in _AUTH_QUALNAMES:
                    targets.add(d.call)
    return targets


@contextlib.contextmanager
def _authed(*paths):
    """Override auth + user-scoped supabase for the given route paths."""
    fake_sb = mock.MagicMock()

    async def _fake_user():
        return USER_ID

    targets = _route_dep_targets(paths)
    assert targets, f"no auth dependencies resolved for {paths!r}"
    added = []
    for call in targets:
        if call.__qualname__ == "get_current_user":
            app.dependency_overrides[call] = _fake_user
        else:
            app.dependency_overrides[call] = lambda: fake_sb
        added.append(call)
    # Belt-and-braces: also key the module-imported symbols (harmless
    # duplicates when identical to the route-resolved callables).
    from packages.quantum.security import (
        get_current_user,
        get_supabase_user_client,
    )

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_supabase_user_client] = lambda: fake_sb
    added += [get_current_user, get_supabase_user_client]
    try:
        yield fake_sb
    finally:
        for k in added:
            app.dependency_overrides.pop(k, None)


# ===========================================================================
# 1. /rebalance/preview — optimizer failure (deepest callee the route
#    reaches) must surface as the typed message, never the exception text.
#    Boundary wiring imported from the authoritative rebalance harness.
# ===========================================================================
def test_rebalance_preview_masks_optimizer_detail_in_production():
    from packages.quantum.tests.test_rebalance_endpoint_contract import (
        FakeSupabase,
        _book_rows,
        _wired,
    )

    sensitive = "SECRET_KEY_PREVIEW_123"
    fake_sb = FakeSupabase(_book_rows())
    with _wired(fake_sb, opt_exc=RuntimeError(f"Optimizer failed: {sensitive}")) as handles:
        with mock.patch.dict(os.environ, _PROD):
            resp = client.post("/rebalance/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    # Whole-payload leak check, stronger than the original message-only one.
    assert sensitive not in resp.text
    assert body["message"] == "Optimization failed"
    # Non-vacuous: the exploding optimizer was actually reached.
    assert handles["opt"].call_count == 1


# ===========================================================================
# 2. /analytics/behavior — service failure at its origin must yield a
#    masked 500 in production.
# ===========================================================================
def test_analytics_behavior_masks_service_detail_in_production():
    sensitive = "SECRET_KEY_ANALYTICS_456"
    with _authed("/analytics/behavior"):
        with mock.patch(
            "packages.quantum.analytics_endpoints.BehaviorAnalysisService"
        ) as MockService:
            MockService.return_value.get_behavior_summary.side_effect = (
                Exception(f"db=postgres://svc:hunter2@10.0.0.9 {sensitive}")
            )
            with mock.patch.dict(os.environ, _PROD):
                resp = client.get("/analytics/behavior?window=7d")

    assert resp.status_code == 500
    assert sensitive not in resp.text
    assert "hunter2" not in resp.text
    assert resp.json()["detail"] == "Internal Server Error"
    # Non-vacuous: the injected failure is what produced the 500.
    MockService.return_value.get_behavior_summary.assert_called_once()


# ===========================================================================
# 3. /validation/run — checkpoint-evaluation failure at its origin must
#    yield a masked 500 in production.
# ===========================================================================
def test_validation_run_masks_service_detail_in_production():
    sensitive = "SECRET_KEY_VALIDATION_789"
    with _authed("/validation/run"):
        with mock.patch(
            "packages.quantum.validation_endpoints.GoLiveValidationService"
        ) as MockService:
            MockService.return_value.eval_paper_forward_checkpoint.side_effect = (
                Exception(sensitive)
            )
            with mock.patch.dict(os.environ, _PROD):
                resp = client.post("/validation/run", json={"mode": "paper"})

    assert resp.status_code == 500
    assert sensitive not in resp.text
    assert resp.json()["detail"] == "Internal Server Error"
    # Non-vacuous: the injected failure is what produced the 500.
    MockService.return_value.eval_paper_forward_checkpoint.assert_called_once()
