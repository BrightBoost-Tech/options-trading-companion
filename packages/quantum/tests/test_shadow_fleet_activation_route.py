"""F-SHADOW-CAPITAL-PARITY (Lane 3A) — /tasks/shadow-fleet/activation ROUTE.

Drives the REAL production route (packages.quantum.api app → public_tasks
router → services/shadow_fleet_activation) end-to-end with failures
injected at their ORIGIN (missing payload, absent FLEET_ACTIVATION_
AUTHORIZED env, the six-stale-order DB rows) and the truth asserted at the
TOP (HTTP status + zero writes/RPCs on the fake supabase) — a green test on
the service helper alone is not a green closure on the route (E8-3 lesson).

Auth is exercised via the legacy X-Cron-Secret arm of verify_task_signature.
The arm is enabled by patching the globals of the ROUTE-RESOLVED dependency
closure (pattern from test_rebalance_endpoint_contract.py): CI proved a
module-level ``from packages.quantum.security import task_signing_v4`` can
bind a MagicMock CHILD of a poisoned parent package — an earlier-collected
module leaks ``sys.modules["packages.quantum.security"] = MagicMock()``
(test_inbox_ranker_comprehensive.py) — so patching that symbol never
reaches the real module the route closed over. The v4 HMAC arm is pinned by
test_task_signing_v4.py and is not under test here.
"""

import os
import sys
import types
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Environment BEFORE importing the app module (pattern from
# test_rebalance_endpoint_contract.py).
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
# packages.quantum.api — which transitively imports rq_enqueue at module
# level — is unimportable locally (the known 9-file fork class). CI (Linux)
# imports the real rq; the shim only engages where rq itself cannot load.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from fastapi.testclient import TestClient  # noqa: E402

from packages.quantum.api import app  # noqa: E402
from packages.quantum.core.rate_limiter import limiter  # noqa: E402
from packages.quantum.services import shadow_fleet_activation as sfa  # noqa: E402
from packages.quantum.tests.test_shadow_fleet_activation import (  # noqa: E402
    FakeSupabase,
    _attestation,
    _clean_activatable_fake,
    _fleet_row,
    _micro_rows,
    _registrations,
    _stale_submitted_orders,
    _terminal_orders,
)

# The route is 5/minute rate-limited; determinism > exercising slowapi.
limiter.enabled = False

client = TestClient(app)

ROUTE = "/tasks/shadow-fleet/activation"
CRON_SECRET = "test-cron-secret-route"
AUTH_HEADERS = {"X-Cron-Secret": CRON_SECRET}
USER = "11111111-2222-3333-4444-555555555555"


def _route_auth_dependency():
    """Resolve the ACTUAL auth dependency callable bound into the activation
    route (route-resolved pattern from test_rebalance_endpoint_contract.py).

    Immune by construction to the poisoned-parent from-import (see module
    docstring): the callable resolved off ``app.routes`` IS the
    ``verify_task_signature(...)._dependency`` closure the route calls, and
    its ``__globals__`` is the REAL task_signing_v4 module dict —
    ``_verify_legacy_cron_secret`` reads ALLOW_LEGACY_CRON_SECRET /
    CRON_SECRET from that exact dict at call time.
    """
    calls = [
        d.call
        for r in app.routes
        if getattr(r, "path", "") == ROUTE
        for d in r.dependant.dependencies
        if (getattr(d.call, "__module__", "") or "").endswith("task_signing_v4")
    ]
    assert len(calls) == 1, (
        f"expected exactly one task_signing_v4 dependency on {ROUTE}, "
        f"got {calls!r}"
    )
    return calls[0]


def _legacy_auth():
    """Enable the legacy cron-secret arm for this call by patching the
    globals the route's own dependency closure reads at call time. The REAL
    _verify_legacy_cron_secret still runs (constant-time compare included) —
    the arm stays exercised, nothing is bypassed."""
    return mock.patch.dict(
        _route_auth_dependency().__globals__,
        {"ALLOW_LEGACY_CRON_SECRET": True, "CRON_SECRET": CRON_SECRET},
    )


def _patched_admin(fake):
    return mock.patch(
        "packages.quantum.jobs.handlers.utils.get_admin_client",
        return_value=fake,
    )


class TestRouteAuthAndPayload:
    def test_unauthenticated_request_is_401(self):
        response = client.post(ROUTE, json={"user_id": USER,
                                            "step": "provision"})
        assert response.status_code == 401

    def test_empty_payload_is_unavailable(self):
        """Default unavailable without an explicit payload: `step` is
        required, so an empty body is a validation error, not a dry-run."""
        with _legacy_auth():
            response = client.post(ROUTE, json={}, headers=AUTH_HEADERS)
        assert response.status_code == 422


class TestRouteDryRunDefault:
    def test_default_action_is_dry_run_with_zero_writes(self):
        fake = FakeSupabase(orders=_stale_submitted_orders())
        with _legacy_auth(), _patched_admin(fake):
            response = client.post(
                ROUTE,
                json={"user_id": USER, "step": "provision"},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "dry_run"
        assert body["writes_performed"] == 0
        assert fake.writes == [] and fake.rpc_calls == []

    def test_dry_run_activation_reports_stale_order_block(self):
        fake = FakeSupabase(
            fleets=[_fleet_row(user_id=USER)], micro_accounts=_micro_rows(),
            orders=_terminal_orders() + _stale_submitted_orders(6),
        )
        with _legacy_auth(), _patched_admin(fake):
            response = client.post(
                ROUTE,
                json={"user_id": USER, "step": "activate",
                      "policy_registrations": {
                          str(k): v for k, v in _registrations().items()}},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 200
        body = response.json()
        assert body["readiness"]["outcome"] == sfa.LEGACY_ORDERS_NOT_TERMINAL
        assert body["readiness"]["detail"]["legacy_nonterminal_orders"] == 6
        assert fake.writes == [] and fake.rpc_calls == []


class TestRouteExecutionGates:
    def test_execute_without_env_authorization_is_403(self, monkeypatch):
        """Failure injected at the ORIGIN (env unset — tonight's state):
        the top-level HTTP outcome is 403 and nothing was written."""
        monkeypatch.delenv(sfa.AUTHORIZATION_ENV, raising=False)
        fake = _clean_activatable_fake()
        with _legacy_auth(), _patched_admin(fake):
            response = client.post(
                ROUTE,
                json={
                    "user_id": USER, "step": "activate", "execute": True,
                    "confirm": sfa.CONFIRM_LITERAL,
                    "idempotency_key": "route-key",
                    "policy_registrations": {
                        str(k): v for k, v in _registrations().items()},
                    "attestation": _attestation(),
                },
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 403
        assert fake.writes == [] and fake.rpc_calls == []

    def test_execute_activate_without_operator_payload_is_422(
            self, monkeypatch):
        monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")
        fake = _clean_activatable_fake()
        with _legacy_auth(), _patched_admin(fake):
            response = client.post(
                ROUTE,
                json={"user_id": USER, "step": "activate", "execute": True,
                      "confirm": sfa.CONFIRM_LITERAL,
                      "idempotency_key": "route-key"},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 422
        assert fake.writes == [] and fake.rpc_calls == []

    def test_execute_provision_authorized_reaches_single_rpc(
            self, monkeypatch):
        monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")
        fake = FakeSupabase(orders=_terminal_orders())
        with _legacy_auth(), _patched_admin(fake):
            response = client.post(
                ROUTE,
                json={"user_id": USER, "step": "provision", "execute": True,
                      "confirm": sfa.CONFIRM_LITERAL,
                      "idempotency_key": "route-prov-key"},
                headers=AUTH_HEADERS,
            )
        assert response.status_code == 200
        assert response.json()["status"] == "rpc_complete"
        assert len(fake.rpc_calls) == 1
        assert fake.rpc_calls[0]["fn"] == sfa.PROVISION_RPC
        assert fake.writes == []
