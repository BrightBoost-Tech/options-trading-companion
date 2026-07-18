"""A5-2 job-origin provenance (Lane 4D, 2026-07-17).

Covers, per the build contract:

1.  Unit per-taxonomy builder (``packages/quantum/jobs/origin.py``):
    every taxonomy value builds; invalid values raise; coercion at the
    seam never raises; header resolution classifies honestly.
2.  Enqueue-seam tests: the REAL ``JobRunStore.create_or_get`` /
    ``create_or_get_cancelled`` (fake supabase) stamp ``payload.origin``
    into the INSERTED row — i.e. provenance exists BEFORE any worker
    runs (the 03946f58 queued-orphan lesson).
3.  Caller-class threading through the real ``enqueue_job_run`` seam.
4.  The 14:09Z attribution case, driven END-TO-END through the real
    FastAPI route + REAL v4 HMAC verification (failure injected at the
    origin — the HTTP request — truth asserted at the top — the row):
    an off-schedule ``suggestions_open`` enqueued via the API/manual
    path carries a NON-scheduler origin; a scheduler-asserted request
    carries origin=scheduler + schedule_id.
5.  No-behavior-change: the enqueue result contract, RQ payload, and
    queue routing are byte-identical apart from the added provenance
    field inside the inserted row's payload.
6.  The run_signed_task.py CLI self-assertion headers.
"""

import json
import uuid as uuid_mod
from datetime import datetime

import pytest


def _ensure_rq_importable():
    """Windows-local shim ONLY: importing ``rq`` calls
    ``multiprocessing.get_context('fork')`` at import time, which raises on
    Windows (the known local '9 fork uncollectable files' class). On CI the
    real ``rq`` imports fine and this is a no-op — the production import
    path is untouched there. Locally we install a minimal stub so the
    enqueue-seam tests (which patch ``enqueue_idempotent`` anyway and never
    touch a real queue) can execute."""
    try:
        import rq  # noqa: F401
    except Exception:
        import sys
        import types

        stub = types.ModuleType("rq")

        class _StubQueue:  # pragma: no cover - local-only shim
            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    "rq stub Queue must never be instantiated in tests"
                )

        stub.Queue = _StubQueue
        sys.modules["rq"] = stub


_ensure_rq_importable()

from packages.quantum.jobs import origin as origin_mod
from packages.quantum.jobs.origin import (
    ACTOR_CLASS_HEADER,
    ORIGIN_HEADER,
    ORIGIN_INTERNAL_RETRY,
    ORIGIN_MANUAL_CLI,
    ORIGIN_OPERATOR_SIGNED_ENDPOINT,
    ORIGIN_REPLAY,
    ORIGIN_SCHEDULER,
    ORIGIN_UNKNOWN_LEGACY,
    PROVENANCE_VERSION,
    REQUEST_ID_HEADER,
    SCHEDULE_ID_HEADER,
    SCHEDULE_SLOT_HEADER,
    VALID_ORIGINS,
    append_retry_origin,
    build_origin,
    coerce_origin,
    resolve_request_origin,
)


# =====================================================================
# 1. Per-taxonomy builder units
# =====================================================================


class TestBuildOriginTaxonomy:
    @pytest.mark.parametrize(
        "taxonomy",
        sorted(VALID_ORIGINS),
    )
    def test_every_taxonomy_value_builds(self, taxonomy):
        obj = build_origin(taxonomy, trigger_actor_class="test_actor")
        assert obj["origin"] == taxonomy
        assert obj["trigger_actor_class"] == "test_actor"
        assert obj["v"] == PROVENANCE_VERSION
        # created_at is known-at: a parseable tz-aware UTC instant.
        parsed = datetime.fromisoformat(obj["created_at"])
        assert parsed.tzinfo is not None
        # All contract fields present even when unset (typed shape).
        for field in (
            "origin", "trigger_actor_class", "trigger_request_id",
            "parent_job_run_id", "schedule_id", "schedule_slot",
            "code_sha", "created_at", "v",
        ):
            assert field in obj

    def test_taxonomy_is_the_agreed_closed_set(self):
        assert VALID_ORIGINS == {
            "scheduler",
            "operator_signed_endpoint",
            "internal_retry",
            "manual_cli",
            "replay",
            "unknown_legacy",
        }

    def test_invalid_taxonomy_value_raises(self):
        with pytest.raises(ValueError, match="invalid origin taxonomy"):
            build_origin("cron")  # not a taxonomy value — must fail loudly

    def test_code_sha_uses_existing_lineage_resolver(self, monkeypatch):
        import packages.quantum.observability.lineage as lineage

        monkeypatch.setattr(lineage, "get_code_sha", lambda: "abc123def456")
        obj = build_origin(ORIGIN_SCHEDULER)
        assert obj["code_sha"] == "abc123def456"

    def test_explicit_code_sha_wins(self):
        obj = build_origin(ORIGIN_SCHEDULER, code_sha="deadbeef")
        assert obj["code_sha"] == "deadbeef"

    def test_fields_are_clipped_and_normalized(self):
        obj = build_origin(
            ORIGIN_MANUAL_CLI,
            trigger_actor_class="x" * 500,
            trigger_request_id="  spaced  ",
            schedule_id="",
        )
        assert len(obj["trigger_actor_class"]) == 128
        assert obj["trigger_request_id"] == "spaced"
        assert obj["schedule_id"] is None  # empty → None, never ""

    def test_schedule_fields_carried(self):
        obj = build_origin(
            ORIGIN_SCHEDULER,
            schedule_id="suggestions_open",
            schedule_slot="cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri",
        )
        assert obj["schedule_id"] == "suggestions_open"
        assert obj["schedule_slot"].startswith("cron:hour=11")


class TestCoerceOrigin:
    def test_none_coerces_to_unknown_legacy(self):
        obj = coerce_origin(None)
        assert obj["origin"] == ORIGIN_UNKNOWN_LEGACY
        assert obj["trigger_actor_class"] == "unthreaded_enqueue_caller"

    def test_malformed_object_coerces_to_unknown_legacy(self):
        obj = coerce_origin({"origin": "not-a-taxonomy-value"})
        assert obj["origin"] == ORIGIN_UNKNOWN_LEGACY
        assert obj["trigger_actor_class"] == "malformed_origin_object"

    def test_wrong_type_coerces_to_unknown_legacy(self):
        obj = coerce_origin("scheduler")  # a bare string is not an origin object
        assert obj["origin"] == ORIGIN_UNKNOWN_LEGACY

    def test_valid_object_passes_through_unchanged(self):
        built = build_origin(ORIGIN_REPLAY, trigger_actor_class="replay_harness")
        assert coerce_origin(built) is built


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class TestResolveRequestOrigin:
    def test_scheduler_assertion_resolves_scheduler(self):
        rid = str(uuid_mod.uuid4())
        req = _FakeRequest({
            ORIGIN_HEADER: "scheduler",
            ACTOR_CLASS_HEADER: "apscheduler_in_process",
            REQUEST_ID_HEADER: rid,
            SCHEDULE_ID_HEADER: "suggestions_open",
            SCHEDULE_SLOT_HEADER: "cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri",
        })
        obj = resolve_request_origin(req)
        assert obj["origin"] == ORIGIN_SCHEDULER
        assert obj["trigger_actor_class"] == "apscheduler_in_process"
        assert obj["trigger_request_id"] == rid
        assert obj["schedule_id"] == "suggestions_open"

    def test_unmarked_signed_request_is_operator_never_scheduler(self):
        """The 14:09Z lesson: an unmarked signed request must NEVER read
        as scheduler."""
        obj = resolve_request_origin(_FakeRequest({}))
        assert obj["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert obj["trigger_actor_class"] == "signed_client_unmarked"
        assert obj["schedule_id"] is None

    def test_invalid_assertion_recorded_not_fabricated(self):
        obj = resolve_request_origin(
            _FakeRequest({ORIGIN_HEADER: "totally-bogus"})
        )
        assert obj["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert obj["trigger_actor_class"] == (
            "invalid_origin_assertion:totally-bogus"
        )

    def test_other_valid_assertions_pass_through(self):
        obj = resolve_request_origin(
            _FakeRequest({ORIGIN_HEADER: "manual_cli",
                          ACTOR_CLASS_HEADER: "some_script"})
        )
        assert obj["origin"] == ORIGIN_MANUAL_CLI
        assert obj["trigger_actor_class"] == "some_script"

    def test_unreadable_request_is_unknown_legacy(self):
        class _Broken:
            @property
            def headers(self):
                raise RuntimeError("no headers")

        obj = resolve_request_origin(_Broken())
        assert obj["origin"] == ORIGIN_UNKNOWN_LEGACY
        assert obj["trigger_actor_class"] == "unresolvable_request"


class TestAppendRetryOrigin:
    def test_appends_without_mutating_and_preserves_creator(self):
        payload = {"date": "2026-07-17", "origin": {"origin": "scheduler"}}
        out = append_retry_origin(
            payload,
            origin=ORIGIN_INTERNAL_RETRY,
            trigger_actor_class="scheduler_auto_retry",
            parent_job_run_id="jr-abc",
        )
        # input not mutated
        assert "origin_retries" not in payload
        # creator provenance untouched
        assert out["origin"] == {"origin": "scheduler"}
        assert out["date"] == "2026-07-17"
        (entry,) = out["origin_retries"]
        assert entry["origin"] == ORIGIN_INTERNAL_RETRY
        assert entry["parent_job_run_id"] == "jr-abc"

    def test_second_retry_appends(self):
        first = append_retry_origin(
            {}, origin=ORIGIN_INTERNAL_RETRY,
            trigger_actor_class="scheduler_auto_retry",
            parent_job_run_id="jr-1",
        )
        second = append_retry_origin(
            first, origin=ORIGIN_OPERATOR_SIGNED_ENDPOINT,
            trigger_actor_class="admin_jobs_api_retry",
            parent_job_run_id="jr-1",
        )
        assert len(second["origin_retries"]) == 2
        assert second["origin_retries"][1]["origin"] == (
            ORIGIN_OPERATOR_SIGNED_ENDPOINT
        )

    def test_non_dict_payload_tolerated(self):
        out = append_retry_origin(
            None, origin=ORIGIN_INTERNAL_RETRY,
            trigger_actor_class="scheduler_auto_retry",
            parent_job_run_id="jr-2",
        )
        assert len(out["origin_retries"]) == 1


# =====================================================================
# 2. Enqueue-seam: the REAL JobRunStore stamps the INSERTED row
# =====================================================================


class _Resp:
    def __init__(self, data):
        self.data = data


class _UpsertHandle:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Resp([{**self._data, "id": "jr-new"}])


class _FakeJobRunsTable:
    """Chainable fake for the job_runs table used by JobRunStore."""

    def __init__(self, existing_rows=None):
        self.existing = list(existing_rows or [])
        self.upserted = []

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(list(self.existing))

    def upsert(self, data, **kw):
        self.upserted.append(data)
        return _UpsertHandle(data)


class _FakeClient:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "job_runs"
        return self._table


def _make_store(existing_rows=None):
    from unittest.mock import MagicMock, patch

    from packages.quantum.jobs.job_runs import JobRunStore

    with patch(
        "packages.quantum.jobs.job_runs.create_supabase_admin_client",
        return_value=MagicMock(),
    ):
        store = JobRunStore()
    table = _FakeJobRunsTable(existing_rows)
    store.client = _FakeClient(table)
    return store, table


class TestCreateOrGetStampsOriginAtInsertTime:
    def test_threaded_origin_lands_in_inserted_payload(self):
        store, table = _make_store()
        threaded = build_origin(
            ORIGIN_SCHEDULER,
            trigger_actor_class="apscheduler_in_process",
            schedule_id="suggestions_open",
        )
        caller_payload = {"date": "2026-07-17", "type": "open"}
        row = store.create_or_get(
            "suggestions_open", "2026-07-17-open-all-ss0-default",
            caller_payload, origin=threaded,
        )
        # Provenance exists in the INSERT — before any worker runs.
        (inserted,) = table.upserted
        assert inserted["payload"]["origin"] is threaded
        assert inserted["status"] == "queued"
        # The returned row carries it too.
        assert row["payload"]["origin"]["origin"] == ORIGIN_SCHEDULER
        # Original payload keys intact; caller's dict NOT mutated.
        assert inserted["payload"]["date"] == "2026-07-17"
        assert "origin" not in caller_payload

    def test_unthreaded_caller_defaults_to_unknown_legacy(self):
        store, table = _make_store()
        store.create_or_get("some_job", "key-1", {"a": 1})
        (inserted,) = table.upserted
        assert inserted["payload"]["origin"]["origin"] == ORIGIN_UNKNOWN_LEGACY
        assert inserted["payload"]["origin"]["trigger_actor_class"] == (
            "unthreaded_enqueue_caller"
        )

    def test_existing_row_wins_no_overwrite(self):
        existing = {
            "id": "jr-old", "status": "queued",
            "payload": {"origin": {"origin": "scheduler"}},
        }
        store, table = _make_store(existing_rows=[existing])
        row = store.create_or_get(
            "suggestions_open", "dup-key", {},
            origin=build_origin(ORIGIN_OPERATOR_SIGNED_ENDPOINT),
        )
        assert row is existing  # first-writer provenance wins
        assert table.upserted == []  # no second insert

    def test_cancelled_gate_rows_carry_origin_too(self):
        store, table = _make_store()
        threaded = build_origin(
            ORIGIN_OPERATOR_SIGNED_ENDPOINT,
            trigger_actor_class="run_signed_task_cli",
        )
        store.create_or_get_cancelled(
            "suggestions_open", "key-c", {"date": "2026-07-17"},
            cancelled_reason="global_ops_pause",
            cancelled_detail="paused for audit",
            origin=threaded,
        )
        (inserted,) = table.upserted
        assert inserted["status"] == "cancelled"
        assert inserted["payload"]["origin"] is threaded
        assert inserted["payload"]["cancelled_reason"] == "global_ops_pause"

    def test_payload_stays_json_serializable(self):
        store, table = _make_store()
        store.create_or_get("j", "k", {"n": 1}, origin=None)
        (inserted,) = table.upserted
        json.dumps(inserted["payload"])  # must not raise


# =====================================================================
# 3 + 5. enqueue_job_run threading + no-behavior-change contract
# =====================================================================


class _FakeStore:
    def __init__(self):
        self.create_calls = []
        self.cancel_calls = []

    def create_or_get(self, job_name, idempotency_key, payload, origin=None):
        self.create_calls.append({
            "job_name": job_name,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "origin": origin,
        })
        return {"id": "jr-1", "status": "queued"}

    def create_or_get_cancelled(self, job_name, idempotency_key, payload,
                                cancelled_reason, cancelled_detail=None,
                                origin=None):
        self.cancel_calls.append({
            "job_name": job_name,
            "cancelled_reason": cancelled_reason,
            "origin": origin,
        })
        return {"id": "jr-c", "status": "cancelled"}


@pytest.fixture
def enqueue_env(monkeypatch):
    """Patch the seam collaborators around the REAL enqueue_job_run."""
    import packages.quantum.ops_endpoints as ops_endpoints
    import packages.quantum.public_tasks as public_tasks

    fake_store = _FakeStore()
    rq_calls = []

    def _fake_rq(**kwargs):
        rq_calls.append(kwargs)
        return {"status": "queued", "job_id": "rq-1", "enqueued_at": None}

    monkeypatch.setattr(public_tasks, "JobRunStore", lambda: fake_store)
    monkeypatch.setattr(public_tasks, "enqueue_idempotent", _fake_rq)
    monkeypatch.setattr(
        ops_endpoints, "is_trading_paused", lambda: (False, None)
    )
    return public_tasks, fake_store, rq_calls


class TestEnqueueJobRunThreading:
    def test_origin_threads_to_store(self, enqueue_env):
        public_tasks, fake_store, _ = enqueue_env
        threaded = build_origin(ORIGIN_MANUAL_CLI, trigger_actor_class="t")
        public_tasks.enqueue_job_run(
            "suggestions_open", "k1", {"date": "d"}, origin=threaded
        )
        (call,) = fake_store.create_calls
        assert call["origin"] is threaded

    def test_result_contract_unchanged_no_origin_leak(self, enqueue_env):
        public_tasks, _, rq_calls = enqueue_env
        result = public_tasks.enqueue_job_run(
            "suggestions_open", "k2", {"date": "d"},
            origin=build_origin(ORIGIN_SCHEDULER),
        )
        # Byte-identical result contract (pre-change key set + values).
        assert result == {
            "job_run_id": "jr-1",
            "job_name": "suggestions_open",
            "idempotency_key": "k2",
            "rq_job_id": "rq-1",
            "status": "queued",
        }
        # RQ payload + routing unchanged.
        (rq,) = rq_calls
        assert rq["payload"] == {"job_run_id": "jr-1"}
        assert rq["queue_name"] == "otc"
        assert rq["handler_path"] == "packages.quantum.jobs.runner.run_job_run"

    def test_queue_routing_passthrough_unchanged(self, enqueue_env):
        public_tasks, _, rq_calls = enqueue_env
        public_tasks.enqueue_job_run(
            "paper_learning_ingest", "k3", {}, queue_name="background",
            origin=build_origin(ORIGIN_SCHEDULER),
        )
        assert rq_calls[0]["queue_name"] == "background"

    def test_paused_gate_cancelled_row_gets_origin(self, enqueue_env, monkeypatch):
        import packages.quantum.ops_endpoints as ops_endpoints

        public_tasks, fake_store, rq_calls = enqueue_env
        monkeypatch.setattr(
            ops_endpoints, "is_trading_paused",
            lambda: (True, "operator pause"),
        )
        threaded = build_origin(
            ORIGIN_OPERATOR_SIGNED_ENDPOINT,
            trigger_actor_class="run_signed_task_cli",
        )
        result = public_tasks.enqueue_job_run(
            "suggestions_open", "k4", {}, origin=threaded
        )
        assert result["status"] == "cancelled"
        (call,) = fake_store.cancel_calls
        assert call["origin"] is threaded
        assert rq_calls == []  # still no RQ enqueue while paused


# =====================================================================
# 4. The 14:09Z attribution case — END-TO-END through the real route
#    and REAL v4 HMAC verification.
# =====================================================================


_TEST_SECRET = "origin-prov-test-secret"


@pytest.fixture
def signed_app(monkeypatch, enqueue_env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import packages.quantum.security.task_signing_v4 as signing
    from packages.quantum.core.rate_limiter import limiter

    public_tasks, fake_store, rq_calls = enqueue_env

    monkeypatch.setattr(signing, "SIGNING_KEYS", {})
    monkeypatch.setattr(signing, "TASK_SIGNING_SECRET", _TEST_SECRET)
    monkeypatch.setattr(signing, "TASK_NONCE_PROTECTION", False)
    monkeypatch.setattr(limiter, "enabled", False)

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(public_tasks.router)
    client = TestClient(app)
    return client, fake_store, rq_calls


def _signed_headers(path, scope, body=b"{}", extra=None):
    from packages.quantum.security.task_signing_v4 import sign_task_request

    headers = sign_task_request(
        method="POST", path=path, body=body, scope=scope, secret=_TEST_SECRET
    )
    headers["Content-Type"] = "application/json"
    if extra:
        headers.update(extra)
    return headers


class TestOffScheduleAttribution:
    def test_1409_case_api_manual_fire_is_non_scheduler(self, signed_app):
        """A suggestions_open enqueued outside any schedule slot via the
        signed API path (no origin assertion — the historical client
        shape) must carry a NON-scheduler origin on the row."""
        client, fake_store, _ = signed_app
        resp = client.post(
            "/tasks/suggestions/open",
            content=b"{}",
            headers=_signed_headers(
                "/tasks/suggestions/open", "tasks:suggestions_open"
            ),
        )
        assert resp.status_code == 202
        (call,) = fake_store.create_calls
        assert call["job_name"] == "suggestions_open"
        origin = call["origin"]
        assert origin["origin"] != ORIGIN_SCHEDULER
        assert origin["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert origin["trigger_actor_class"] == "signed_client_unmarked"
        # Response contract unchanged — no provenance leak.
        assert set(resp.json().keys()) == {
            "job_run_id", "job_name", "idempotency_key", "rq_job_id", "status",
        }

    def test_cli_asserted_fire_is_operator_with_actor_class(self, signed_app):
        client, fake_store, _ = signed_app
        rid = str(uuid_mod.uuid4())
        resp = client.post(
            "/tasks/suggestions/open",
            content=b"{}",
            headers=_signed_headers(
                "/tasks/suggestions/open", "tasks:suggestions_open",
                extra={
                    ORIGIN_HEADER: ORIGIN_OPERATOR_SIGNED_ENDPOINT,
                    ACTOR_CLASS_HEADER: "run_signed_task_cli",
                    REQUEST_ID_HEADER: rid,
                },
            ),
        )
        assert resp.status_code == 202
        (call,) = fake_store.create_calls
        assert call["origin"]["origin"] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert call["origin"]["trigger_actor_class"] == "run_signed_task_cli"
        assert call["origin"]["trigger_request_id"] == rid

    def test_scheduler_asserted_fire_carries_schedule_identity(self, signed_app):
        """The same route, fired with exactly the headers _fire_task sends,
        resolves to origin=scheduler + schedule_id/slot."""
        client, fake_store, _ = signed_app
        slot = "cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri"
        resp = client.post(
            "/tasks/suggestions/open",
            content=b"{}",
            headers=_signed_headers(
                "/tasks/suggestions/open", "tasks:suggestions_open",
                extra={
                    ORIGIN_HEADER: ORIGIN_SCHEDULER,
                    ACTOR_CLASS_HEADER: "apscheduler_in_process",
                    REQUEST_ID_HEADER: str(uuid_mod.uuid4()),
                    SCHEDULE_ID_HEADER: "suggestions_open",
                    SCHEDULE_SLOT_HEADER: slot,
                },
            ),
        )
        assert resp.status_code == 202
        (call,) = fake_store.create_calls
        assert call["origin"]["origin"] == ORIGIN_SCHEDULER
        assert call["origin"]["schedule_id"] == "suggestions_open"
        assert call["origin"]["schedule_slot"] == slot

    def test_internal_router_threads_origin_too(self, monkeypatch, enqueue_env):
        """The scripted internal_tasks threading, proven at runtime through
        a REAL /internal/tasks route (heartbeat — a scheduler-fired slot)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import packages.quantum.internal_tasks as internal_tasks
        import packages.quantum.security.task_signing_v4 as signing

        _, fake_store, _ = enqueue_env
        monkeypatch.setattr(signing, "SIGNING_KEYS", {})
        monkeypatch.setattr(signing, "TASK_SIGNING_SECRET", _TEST_SECRET)
        monkeypatch.setattr(signing, "TASK_NONCE_PROTECTION", False)

        app = FastAPI()
        app.include_router(internal_tasks.router)
        client = TestClient(app)

        resp = client.post(
            "/internal/tasks/heartbeat",
            content=b"{}",
            headers=_signed_headers(
                "/internal/tasks/heartbeat", "tasks:heartbeat",
                extra={
                    ORIGIN_HEADER: ORIGIN_SCHEDULER,
                    ACTOR_CLASS_HEADER: "apscheduler_in_process",
                    SCHEDULE_ID_HEADER: "scheduler_heartbeat",
                },
            ),
        )
        assert resp.status_code == 202
        (call,) = fake_store.create_calls
        assert call["job_name"] == "scheduler_heartbeat"
        assert call["origin"]["origin"] == ORIGIN_SCHEDULER
        assert call["origin"]["schedule_id"] == "scheduler_heartbeat"

    def test_origin_header_cannot_bypass_signature(self, signed_app):
        """Provenance is attribution, never authorization: an unsigned
        request with a scheduler assertion is still rejected."""
        client, fake_store, _ = signed_app
        resp = client.post(
            "/tasks/suggestions/open",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                ORIGIN_HEADER: ORIGIN_SCHEDULER,
            },
        )
        assert resp.status_code == 401
        assert fake_store.create_calls == []


# =====================================================================
# 6. run_signed_task.py CLI self-assertion
# =====================================================================


class TestRunSignedTaskOriginHeaders:
    @pytest.fixture
    def cli(self):
        import os
        import sys

        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "scripts"
        )
        sys.path.insert(0, scripts_dir)
        try:
            import run_signed_task
        finally:
            sys.path.remove(scripts_dir)
        return run_signed_task

    def test_cli_asserts_operator_origin(self, cli, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        headers = cli._origin_headers()
        assert headers[ORIGIN_HEADER] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
        assert headers[ACTOR_CLASS_HEADER] == "run_signed_task_cli"
        uuid_mod.UUID(headers[REQUEST_ID_HEADER])  # valid uuid

    def test_github_actions_actor_class(self, cli, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        headers = cli._origin_headers()
        assert headers[ACTOR_CLASS_HEADER] == "github_actions_workflow"
        assert headers[ORIGIN_HEADER] == ORIGIN_OPERATOR_SIGNED_ENDPOINT
