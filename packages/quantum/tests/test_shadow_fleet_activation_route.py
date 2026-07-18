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

import json
import os
import sys
import types
import uuid as uuid_mod
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
from packages.quantum.jobs.origin import (  # noqa: E402
    ACTOR_CLASS_HEADER,
    ORIGIN_HEADER,
    ORIGIN_OPERATOR_SIGNED_ENDPOINT,
    ORIGIN_SCHEDULER,
    REQUEST_ID_HEADER,
)
from packages.quantum.tests.test_job_origin_provenance import (  # noqa: E402
    _pin_real_module,
)

# The route is 5/minute rate-limited; determinism > exercising slowapi.
limiter.enabled = False

client = TestClient(app)

ROUTE = "/tasks/shadow-fleet/activation"
CRON_SECRET = "test-cron-secret-route"
AUTH_HEADERS = {"X-Cron-Secret": CRON_SECRET}
USER = "11111111-2222-3333-4444-555555555555"


def _iter_route_candidates():
    """Yield route objects from ``app.routes`` across FastAPI versions.

    fastapi<=0.135 FLATTENS ``include_router()``: every included endpoint
    appears in ``app.routes`` as a prefix-qualified APIRoute. fastapi
    0.139.x (starlette 1.x, what CI resolves the UNPINNED
    ``fastapi>=0.104.0`` to) instead appends an ``_IncludedRouter``
    CONTAINER — the real APIRoute objects live on
    ``container.original_router.routes`` (path still prefix-qualified,
    dependant intact) while a flat ``app.routes`` scan sees ZERO /tasks
    routes even though requests still dispatch through the container
    (CI run 29623820938: lookup ``got []`` with the unauthenticated-401
    test — served by the same app — passing 0.2s earlier). Walk both
    shapes; dedup by identity.
    """
    seen = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        yield route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(getattr(inner, "routes", None) or [])
        stack.extend(getattr(route, "routes", None) or [])


def _route_auth_dependency():
    """Resolve the ACTUAL auth dependency callable bound into the activation
    route (route-resolved pattern from test_rebalance_endpoint_contract.py,
    made include_router-shape-robust via _iter_route_candidates).

    Immune by construction to the poisoned-parent from-import (see module
    docstring): the callable resolved off the route table IS the
    ``verify_task_signature(...)._dependency`` closure the route calls, and
    its ``__globals__`` is the REAL task_signing_v4 module dict —
    ``_verify_legacy_cron_secret`` reads ALLOW_LEGACY_CRON_SECRET /
    CRON_SECRET from that exact dict at call time.
    """
    calls = [
        d.call
        for r in _iter_route_candidates()
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


# ---------------------------------------------------------------------------
# A5-2 origin provenance on the /tasks/shadow-fleet/activation route.
#
# This surface acts SYNCHRONOUSLY — it does NOT enqueue_job_run, so there is
# NO job_runs row to carry payload.origin, and its writes land inside the
# frozen atomic RPC (no origin argument). The origin contract is therefore
# asserted at the ENDPOINT SEAM: the endpoint resolves
# resolve_request_origin(request) and stamps it into the RETURNED receipt
# (dry-run AND execute). These tests drive the REAL public_tasks router with
# REAL v4 HMAC verification (pattern: test_job_origin_provenance.signed_app),
# failure injected at the ORIGIN (the request) and truth asserted at the TOP
# (the receipt body's origin object / the HTTP status).
# ---------------------------------------------------------------------------

_ORIGIN_TEST_SECRET = "shadow-fleet-origin-test-secret"


@pytest.fixture
def signed_fleet_app(monkeypatch):
    """Fresh FastAPI app mounting the REAL public_tasks router with REAL v4
    HMAC verification. The signing module is pinned real (defeating the
    poisoned-parent sys.modules leak) so the route's own
    verify_task_signature closure reads our test secret at call time."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    signing = _pin_real_module(
        monkeypatch, "packages.quantum.security.task_signing_v4"
    )
    public_tasks = _pin_real_module(
        monkeypatch, "packages.quantum.public_tasks"
    )
    monkeypatch.setattr(signing, "SIGNING_KEYS", {})
    monkeypatch.setattr(signing, "TASK_SIGNING_SECRET", _ORIGIN_TEST_SECRET)
    monkeypatch.setattr(signing, "TASK_NONCE_PROTECTION", False)
    monkeypatch.setattr(limiter, "enabled", False)

    signed_app = FastAPI()
    signed_app.state.limiter = limiter
    signed_app.include_router(public_tasks.router)
    return TestClient(signed_app)


def _signed_fleet_headers(body_bytes, extra=None):
    """Real v4 HMAC headers for the activation route (per
    test_job_origin_provenance._signed_headers). The X-Task-Origin assertion
    headers ride OUTSIDE the canonical string, so they never affect the
    signature."""
    from packages.quantum.security.task_signing_v4 import sign_task_request

    headers = sign_task_request(
        method="POST", path=ROUTE, body=body_bytes,
        scope="tasks:shadow_fleet_activation", secret=_ORIGIN_TEST_SECRET,
    )
    headers["Content-Type"] = "application/json"
    if extra:
        headers.update(extra)
    return headers


class TestRouteOriginProvenance:
    def test_signed_dry_run_receipt_stamps_operator_origin(
            self, signed_fleet_app):
        """A signed operator call WITHOUT an origin assertion header (the
        historical client shape) → the dry-run receipt carries
        origin=operator_signed_endpoint, actor class signed_client_unmarked
        (the 14:09Z lesson: an unmarked signed request never reads as
        scheduler). Provenance is attribution, not a write: zero writes."""
        fake = FakeSupabase(orders=_stale_submitted_orders())
        body = json.dumps({"user_id": USER, "step": "provision"}).encode()
        with _patched_admin(fake):
            resp = signed_fleet_app.post(
                ROUTE, content=body, headers=_signed_fleet_headers(body),
            )
        assert resp.status_code == 200
        receipt = resp.json()
        assert receipt["mode"] == "dry_run"
        assert receipt["writes_performed"] == 0
        origin = receipt["origin"]
        assert origin["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert origin["origin"] != ORIGIN_SCHEDULER
        assert origin["trigger_actor_class"] == "signed_client_unmarked"
        assert fake.writes == [] and fake.rpc_calls == []

    def test_cli_asserted_origin_carries_run_signed_task_cli_actor(
            self, signed_fleet_app):
        """The run_signed_task.py CLI self-asserts actor class
        run_signed_task_cli; resolve_request_origin honours it and the
        endpoint stamps it onto the receipt (honest passthrough)."""
        rid = str(uuid_mod.uuid4())
        fake = FakeSupabase(orders=_stale_submitted_orders())
        body = json.dumps({"user_id": USER, "step": "provision"}).encode()
        with _patched_admin(fake):
            resp = signed_fleet_app.post(
                ROUTE, content=body,
                headers=_signed_fleet_headers(body, extra={
                    ORIGIN_HEADER: ORIGIN_OPERATOR_SIGNED_ENDPOINT,
                    ACTOR_CLASS_HEADER: "run_signed_task_cli",
                    REQUEST_ID_HEADER: rid,
                }),
            )
        assert resp.status_code == 200
        origin = resp.json()["origin"]
        assert origin["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert origin["trigger_actor_class"] == "run_signed_task_cli"
        assert origin["trigger_request_id"] == rid

    def test_execute_provision_receipt_also_stamps_origin(
            self, signed_fleet_app, monkeypatch):
        """The origin is stamped on the EXECUTE path too (not just dry-run):
        an authorized single-RPC provision receipt carries the operator
        origin alongside status=rpc_complete."""
        monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")
        fake = FakeSupabase(orders=_terminal_orders())
        body = json.dumps({
            "user_id": USER, "step": "provision", "execute": True,
            "confirm": sfa.CONFIRM_LITERAL,
            "idempotency_key": "origin-exec-key",
        }).encode()
        with _patched_admin(fake):
            resp = signed_fleet_app.post(
                ROUTE, content=body,
                headers=_signed_fleet_headers(body, extra={
                    ORIGIN_HEADER: ORIGIN_OPERATOR_SIGNED_ENDPOINT,
                    ACTOR_CLASS_HEADER: "run_signed_task_cli",
                }),
            )
        assert resp.status_code == 200
        receipt = resp.json()
        assert receipt["status"] == "rpc_complete"
        assert receipt["origin"]["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert receipt["origin"]["trigger_actor_class"] == "run_signed_task_cli"
        assert len(fake.rpc_calls) == 1

    def test_origin_header_cannot_bypass_signature(self, signed_fleet_app):
        """Provenance is attribution, NEVER authorization: an UNSIGNED request
        that asserts a scheduler origin is still rejected 401, nothing runs."""
        fake = FakeSupabase(orders=_stale_submitted_orders())
        body = json.dumps({"user_id": USER, "step": "provision"}).encode()
        with _patched_admin(fake):
            resp = signed_fleet_app.post(
                ROUTE, content=body,
                headers={"Content-Type": "application/json",
                         ORIGIN_HEADER: ORIGIN_SCHEDULER},
            )
        assert resp.status_code == 401
        assert fake.writes == [] and fake.rpc_calls == []


class TestRunSignedTaskCliMapping:
    """scripts/run_signed_task.py: the shadow_fleet_activation task is
    registered and the CLI origin self-assertion carries actor class
    run_signed_task_cli (mirrors test_job_origin_provenance's CLI check,
    scoped to this route)."""

    @pytest.fixture
    def cli(self):
        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "scripts"
        )
        sys.path.insert(0, scripts_dir)
        try:
            import run_signed_task
        finally:
            sys.path.remove(scripts_dir)
        return run_signed_task

    def test_cli_registers_shadow_fleet_activation_task(self, cli):
        entry = cli.TASKS["shadow_fleet_activation"]
        assert entry["path"] == ROUTE
        assert entry["scope"] == "tasks:shadow_fleet_activation"
        assert entry.get("skip_time_gate") is True

    def test_cli_origin_headers_carry_operator_actor_class(
            self, cli, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        headers = cli._origin_headers()
        assert headers[ORIGIN_HEADER] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert headers[ACTOR_CLASS_HEADER] == "run_signed_task_cli"
        uuid_mod.UUID(headers[REQUEST_ID_HEADER])  # valid uuid
