"""Decision tape deployment-SHA provenance.

Railway builds currently expose a truthy Docker placeholder GIT_SHA=unknown.
These tests prove the writer boundary prefers the full authoritative Railway
SHA on every decision_runs path while preserving the short lineage helper.
"""

import os
from datetime import datetime, timezone
from unittest import mock

from packages.quantum.observability.lineage import get_code_sha, resolve_git_sha
from packages.quantum.services.replay.decision_context import DecisionContext


FULL_SHA = "1234567890abcdef1234567890abcdef12345678"


class _Result:
    def __init__(self, data=None):
        self.data = data


class _Chain:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.payload = None
        self.kind = None

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.kind = "insert"
        self.payload = payload
        return self

    def eq(self, *args):
        return self

    def execute(self):
        if self.kind == "update":
            self.db.update_calls += 1
            if self.db.fail_updates:
                raise RuntimeError("update unavailable")
            self.db.updates.append((self.table, self.payload))
            data = (
                self.db.update_results.pop(0)
                if self.db.update_results
                else []
            )
            return _Result(data)
        if self.kind == "insert":
            self.db.inserts.append((self.table, self.payload))
        return _Result([])


class _RPC:
    def __init__(self, db, name, payload):
        self.db = db
        self.name = name
        self.payload = payload

    def execute(self):
        self.db.rpc_calls.append((self.name, self.payload))
        was_update = self.db.rpc_was_update
        return _Result([{
            "commit_status": "updated" if was_update else "inserted",
            "decision_id": self.payload["p_decision_id"],
            "inputs_inserted": 0,
            "features_inserted": 0,
            "was_update": was_update,
        }])


class _DB:
    def __init__(
        self,
        *,
        fail_updates=False,
        rpc_was_update=False,
        update_results=None,
    ):
        self.fail_updates = fail_updates
        self.rpc_was_update = rpc_was_update
        self.update_results = list(update_results or [])
        self.update_calls = 0
        self.rpc_calls = []
        self.updates = []
        self.inserts = []

    def rpc(self, name, payload):
        return _RPC(self, name, payload)

    def table(self, name):
        return _Chain(self, name)


class _BlobStore:
    def commit(self, supabase):
        return 0

    def unpersisted_of(self, hashes):
        return []

    def was_dropped_oversize(self, blob_hash):
        return False


def _ctx(explicit=None):
    return DecisionContext(
        strategy_name="suggestions_open",
        as_of_ts=datetime(2026, 7, 15, tzinfo=timezone.utc),
        user_id="u",
        git_sha=explicit,
        _blob_store=_BlobStore(),
    )


class TestResolver:
    def test_explicit_real_sha_wins(self):
        with mock.patch.dict(
            os.environ,
            {"GIT_SHA": "other", "RAILWAY_GIT_COMMIT_SHA": "railway"},
            clear=True,
        ):
            assert resolve_git_sha(FULL_SHA) == FULL_SHA

    def test_short_or_malformed_explicit_sha_cannot_shadow_railway(self):
        for invalid in ("abc123", "main", "g" * 40, "1" * 39, "1" * 41):
            with mock.patch.dict(
                os.environ,
                {
                    "GIT_SHA": "also-short",
                    "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
                },
                clear=True,
            ):
                assert resolve_git_sha(invalid) == FULL_SHA

    def test_short_or_malformed_git_sha_falls_back_to_railway(self):
        for invalid in ("abc123", "main", "z" * 40):
            with mock.patch.dict(
                os.environ,
                {
                    "GIT_SHA": invalid,
                    "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
                },
                clear=True,
            ):
                assert resolve_git_sha() == FULL_SHA

    def test_docker_unknown_falls_back_to_railway_sha(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_SHA": "unknown",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            assert resolve_git_sha() == FULL_SHA

    def test_blank_none_and_null_sentinels_fall_back(self):
        for sentinel in ("", "none", "NULL", " unknown "):
            with mock.patch.dict(
                os.environ,
                {
                    "GIT_SHA": sentinel,
                    "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
                },
                clear=True,
            ):
                assert resolve_git_sha() == FULL_SHA

    def test_no_real_source_returns_unknown(self):
        with mock.patch.dict(
            os.environ,
            {"GIT_SHA": "unknown", "RAILWAY_GIT_COMMIT_SHA": ""},
            clear=True,
        ):
            assert resolve_git_sha() == "unknown"

    def test_get_code_sha_keeps_short_contract(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_SHA": "unknown",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            assert get_code_sha() == FULL_SHA[:12]


class TestDecisionWriterBoundary:
    def test_context_repairs_explicit_unknown_from_railway(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_SHA": "unknown",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            assert _ctx("unknown").git_sha == FULL_SHA

    def test_context_preserves_explicit_real_sha(self):
        with mock.patch.dict(
            os.environ,
            {"RAILWAY_GIT_COMMIT_SHA": "railway"},
            clear=True,
        ):
            assert _ctx(FULL_SHA).git_sha == FULL_SHA

    def test_rpc_payload_carries_full_railway_sha(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_SHA": "unknown",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            ctx = _ctx("unknown")
        db = _DB()
        assert ctx._commit_via_rpc(
            db,
            input_hash=None,
            features_hash=None,
            duration_ms=1,
            status="ok",
            error_summary=None,
            inputs_jsonb=[],
            features_jsonb=[],
        )
        assert db.rpc_calls[0][1]["p_git_sha"] == FULL_SHA

    def test_rpc_post_stamp_repairs_production_shaped_existing_row(self):
        with mock.patch.dict(
            os.environ,
            {
                "REPLAY_ENABLE": "1",
                "GIT_SHA": "unknown",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            ctx = _ctx("unknown")
            db = _DB(
                rpc_was_update=True,
                update_results=[[{"decision_id": str(ctx.decision_id)}]],
            )
            result = ctx.commit(db)

        assert result["commit_method"] == "rpc"
        assert result["rpc_was_update"] is True
        assert result["status"] == "ok"
        assert "error" not in result
        assert db.rpc_calls[0][1]["p_decision_id"] == str(ctx.decision_id)
        stamps = [
            payload
            for table, payload in db.updates
            if table == "decision_runs"
        ]
        assert stamps == [{
            "tape_integrity": "complete",
            "git_sha": FULL_SHA,
        }]

    def test_rpc_existing_row_zero_stamp_is_typed_non_green(self):
        with mock.patch.dict(
            os.environ,
            {
                "REPLAY_ENABLE": "1",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            ctx = _ctx()
            db = _DB(rpc_was_update=True, update_results=[[], []])
            result = ctx.commit(db)

        assert result["commit_method"] == "rpc"
        assert result["rpc_was_update"] is True
        assert result["status"] == "failed"
        assert result["tape_integrity"] == "commit_failed"
        assert result["error_type"] == "decision_run_stamp_failed"
        assert "expected_one_row_got_0" in result["error"]
        failed = [
            payload
            for table, payload in db.inserts
            if table == "decision_runs"
        ]
        assert len(failed) == 1
        assert failed[0]["git_sha"] == FULL_SHA

    def test_rpc_existing_row_stamp_exception_is_typed_non_green(self):
        with mock.patch.dict(
            os.environ,
            {
                "REPLAY_ENABLE": "1",
                "RAILWAY_GIT_COMMIT_SHA": FULL_SHA,
            },
            clear=True,
        ):
            ctx = _ctx()
            result = ctx.commit(_DB(rpc_was_update=True, fail_updates=True))

        assert result["status"] == "failed"
        assert result["tape_integrity"] == "commit_failed"
        assert result["error_type"] == "decision_run_stamp_failed"
        assert "update_error" in result["error"]

    def test_sequential_insert_carries_full_sha(self):
        with mock.patch.dict(
            os.environ,
            {"RAILWAY_GIT_COMMIT_SHA": FULL_SHA},
            clear=True,
        ):
            ctx = _ctx()
        db = _DB()
        ctx._commit_sequential(
            db,
            input_hash=None,
            features_hash=None,
            duration_ms=1,
            status="ok",
            error_summary=None,
            inputs_jsonb=[],
            features_jsonb=[],
        )
        row = [
            payload for table, payload in db.inserts
            if table == "decision_runs"
        ][0]
        assert row["git_sha"] == FULL_SHA

    def test_failed_existing_row_update_carries_git_sha(self):
        with mock.patch.dict(
            os.environ,
            {"RAILWAY_GIT_COMMIT_SHA": FULL_SHA},
            clear=True,
        ):
            ctx = _ctx()
        db = _DB(update_results=[[{"decision_id": str(ctx.decision_id)}]])
        ctx._try_mark_failed(db, "boom")
        assert db.updates[0][1]["git_sha"] == FULL_SHA
        assert db.inserts == []

    def test_failed_zero_row_update_falls_back_to_insert(self):
        with mock.patch.dict(
            os.environ,
            {"RAILWAY_GIT_COMMIT_SHA": FULL_SHA},
            clear=True,
        ):
            ctx = _ctx()
        db = _DB(update_results=[[]])
        ctx._try_mark_failed(db, "boom")
        rows = [
            payload
            for table, payload in db.inserts
            if table == "decision_runs"
        ]
        assert len(rows) == 1
        assert rows[0]["git_sha"] == FULL_SHA
        assert rows[0]["status"] == "failed"

    def test_failed_insert_fallback_carries_git_sha(self):
        with mock.patch.dict(
            os.environ,
            {"RAILWAY_GIT_COMMIT_SHA": FULL_SHA},
            clear=True,
        ):
            ctx = _ctx()
        db = _DB(fail_updates=True)
        ctx._try_mark_failed(db, "boom")
        row = [
            payload for table, payload in db.inserts
            if table == "decision_runs"
        ][0]
        assert row["git_sha"] == FULL_SHA
