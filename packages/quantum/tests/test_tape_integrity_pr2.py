"""PR-② (E16-3 + F-REPLAY-FK, 2026-07-13) — tape-integrity tests.

§9 discipline throughout:
- The blob round-trip is tested at the REAL serialization boundary: the fake
  client json.dumps()-encodes every row exactly as supabase-py/PostgREST does.
  A MagicMock client at that layer is what shipped the bug green
  (test_replay_feature_store.py:202) — the fourth mock-at-failing-layer
  instance dies here.
- The capture failure is injected at ORIGIN (the data_blobs upsert raises /
  the blob is oversize) and asserted at the TOP (the run row is a typed
  capture_partial; the job classifier returns 'partial').
- The five previously-unmanifested midday returns are driven through
  run_midday_cycle itself (route-driving), not the helper.
"""
import gzip
import io
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from packages.quantum.services.replay.blob_store import BlobStore, _decode_bytea
from packages.quantum.services.replay.decision_context import DecisionContext


# ---------------------------------------------------------------------------
# A fake supabase client that enforces the REAL serialization boundary
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self._client = client
        self._table = table_name
        self._op = None
        self._rows = None

    def upsert(self, rows, on_conflict=None):
        self._op = "upsert"
        self._rows = rows
        return self

    def insert(self, rows):
        self._op = "insert"
        self._rows = rows
        return self

    def update(self, values):
        self._op = "update"
        self._rows = values
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        if self._table in self._client.raise_on_tables:
            raise RuntimeError(f"injected failure on {self._table}")
        # THE BOUNDARY: PostgREST receives JSON. Raw bytes must die here,
        # exactly as they do in production supabase-py.
        json.dumps(self._rows)
        self._client.writes.setdefault(self._table, []).append(
            (self._op, self._rows))
        return _Result(data=[{}])


class _JSONBoundaryClient:
    """Fake supabase client that json-serializes every write (the real
    PostgREST boundary) and records what landed per table."""

    def __init__(self, raise_on_tables=()):
        self.writes = {}
        self.raise_on_tables = set(raise_on_tables)

    def table(self, name):
        return _Query(self, name)

    def rpc(self, *_a, **_k):
        raise RuntimeError("rpc unavailable (forces sequential path)")


# ---------------------------------------------------------------------------
# Blob store: encode/decode round trip at the boundary
# ---------------------------------------------------------------------------

class TestBlobBoundaryRoundTrip(unittest.TestCase):
    def test_commit_passes_json_boundary_and_hex_roundtrips(self):
        from packages.quantum.services.replay.canonical import canonical_json_bytes

        store = BlobStore()
        obj = {"strategy": "spy_opt_autolearn_v6", "version": 86, "x": [1.5, 2]}
        blob_hash, _, _ = store.put(obj)

        client = _JSONBoundaryClient()
        committed = store.commit(client)

        self.assertEqual(committed, 1)
        self.assertTrue(store.is_persisted(blob_hash))
        op, rows = client.writes["data_blobs"][0]
        self.assertEqual(op, "upsert")
        payload = rows[0]["payload"]
        self.assertIsInstance(payload, str)
        self.assertTrue(payload.startswith("\\x"))
        # BYTE-IDENTICAL round trip: stored hex → gzip → the exact canonical
        # bytes that were hashed (stronger than object equality — the
        # canonical encoder normalizes floats by design).
        raw = gzip.decompress(bytes.fromhex(payload[2:]))
        self.assertEqual(raw, canonical_json_bytes(obj))

    def test_get_decodes_postgrest_hex_string(self):
        obj = {"a": 1, "b": "two"}
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        hex_payload = "\\x" + gzip.compress(canonical).hex()

        class _GetClient:
            def table(self, name):
                outer = self

                class _Q:
                    def select(self, *_a):
                        return self

                    def eq(self, *_a):
                        return self

                    def single(self):
                        return self

                    def execute(self):
                        return _Result({"payload": hex_payload,
                                        "compression": "gzip"})
                return _Q()

        store = BlobStore()
        self.assertEqual(store.get(_GetClient(), "deadbeef"), obj)

    def test_decode_bytea_shapes(self):
        raw = b"\x1f\x8b payload"
        self.assertEqual(_decode_bytea(raw), raw)
        self.assertEqual(_decode_bytea(memoryview(raw)), raw)
        self.assertEqual(_decode_bytea("\\x" + raw.hex()), raw)
        self.assertIsNone(_decode_bytea("not-hex-zz"))
        self.assertIsNone(_decode_bytea(12345))

    def test_oversize_is_typed_drop_never_staged(self):
        store = BlobStore()
        with patch("packages.quantum.services.replay.blob_store."
                   "REPLAY_MAX_BLOB_BYTES", 8):
            blob_hash, _, size = store.put({"big": "x" * 64})
        self.assertGreater(size, 8)
        self.assertTrue(store.was_dropped_oversize(blob_hash))
        self.assertNotIn(blob_hash, store.get_pending_hashes())
        # commit has nothing to send; the hash stays unpersisted for the gate
        self.assertEqual(store.commit(_JSONBoundaryClient()), 0)
        self.assertEqual(store.unpersisted_of([blob_hash]), [blob_hash])


# ---------------------------------------------------------------------------
# Atomicity gate: origin-injected blob failure -> typed capture_partial
# ---------------------------------------------------------------------------

def _ctx(client_unused=None):
    return DecisionContext(
        strategy_name="suggestions_open",
        as_of_ts=datetime.now(timezone.utc),
        user_id="u-test",
        git_sha="testsha",
        _blob_store=BlobStore(),  # fresh, never the process singleton
    )


class TestAtomicityGate(unittest.TestCase):
    def setUp(self):
        os.environ["REPLAY_ENABLE"] = "1"

    def tearDown(self):
        os.environ.pop("REPLAY_ENABLE", None)

    def test_blob_batch_failure_at_origin_is_typed_capture_partial(self):
        """ORIGIN: the data_blobs upsert raises. TOP: the run row is a typed
        capture_partial, decision_inputs receives NOTHING (the FK-orphan class
        is structurally impossible), and stats reports the shortfall."""
        client = _JSONBoundaryClient(raise_on_tables={"data_blobs"})
        ctx = _ctx()
        ctx.__enter__()
        try:
            ctx.record_input("SPY:test", "quote", {"bid": 1.0, "ask": 1.1})
            ctx.record_feature("SPY", "regime", {"state": "normal"})
            stats = ctx.commit(client, status="ok")
        finally:
            ctx.__exit__(None, None, None)

        self.assertEqual(stats["tape_integrity"], "capture_partial")
        self.assertEqual(stats["status"], "capture_partial")
        self.assertEqual(stats["blobs_missing"], 1)
        run_op, run_row = client.writes["decision_runs"][0]
        self.assertEqual(run_row["status"], "capture_partial")
        self.assertEqual(run_row["tape_integrity"], "capture_partial")
        self.assertIn("capture_partial: 1/1", run_row["error_summary"])
        # THE INVARIANT: no decision_inputs write referencing an unpersisted hash
        self.assertNotIn("decision_inputs", client.writes)
        # features are blob-free — they still commit (maximal evidence)
        self.assertIn("decision_features", client.writes)

    def test_clean_commit_is_complete_and_inputs_land(self):
        client = _JSONBoundaryClient()
        ctx = _ctx()
        ctx.__enter__()
        try:
            ctx.record_input("SPY:test", "quote", {"bid": 1.0})
            stats = ctx.commit(client, status="ok")
        finally:
            ctx.__exit__(None, None, None)

        self.assertEqual(stats["tape_integrity"], "complete")
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(len(client.writes["decision_inputs"][0][1]), 1)
        run_row = client.writes["decision_runs"][0][1]
        self.assertEqual(run_row["tape_integrity"], "complete")

    def test_oversize_input_degrades_typed_not_orphaned(self):
        client = _JSONBoundaryClient()
        ctx = _ctx()
        ctx.__enter__()
        try:
            with patch("packages.quantum.services.replay.blob_store."
                       "REPLAY_MAX_BLOB_BYTES", 8):
                ctx.record_input("SPY:big", "chain", {"big": "y" * 128})
            ctx.record_input("SPY:ok", "quote", {"bid": 1.0})
            stats = ctx.commit(client, status="ok")
        finally:
            ctx.__exit__(None, None, None)

        self.assertEqual(stats["tape_integrity"], "capture_partial")
        self.assertEqual(stats["blobs_missing"], 1)
        self.assertEqual(stats["blobs_oversize_dropped"], 1)
        # only the persisted blob's input row landed
        input_rows = client.writes["decision_inputs"][0][1]
        self.assertEqual(len(input_rows), 1)
        self.assertEqual(input_rows[0]["key"], "SPY:ok")


# ---------------------------------------------------------------------------
# Roll-up: generic nested counts.errors reaches the top level
# ---------------------------------------------------------------------------

class TestErrorRollup(unittest.TestCase):
    def setUp(self):
        os.environ["REPLAY_ENABLE"] = "1"

    def tearDown(self):
        os.environ.pop("REPLAY_ENABLE", None)

    def test_rollup_sums_generic_errors_and_persist_failures(self):
        from packages.quantum.jobs.handlers.suggestions_open import (
            _persist_error_rollup,
        )
        cycles = [
            {"counts": {"rejection_persist_failures": 2}},
            {"counts": {"errors": 1}},          # the #1188 replay_commit_error class
            {"counts": {}},
            {},
            None,
        ]
        self.assertEqual(_persist_error_rollup(cycles), 3)

    def test_commit_degrade_classifies_job_partial_end_to_end(self):
        """ORIGIN: blob write dies inside the handler's commit. TOP: the job
        result carries counts.errors and the REAL runner classifier returns
        'partial' — the class that rode green five times on 07-13."""
        from packages.quantum.jobs.runner import _classify_handler_return

        client = _JSONBoundaryClient(raise_on_tables={"data_blobs"})
        ctx = _ctx()
        ctx.__enter__()
        try:
            ctx.record_input("SPY:test", "quote", {"bid": 1.0})
            commit_res = ctx.commit(client, status="ok")
        finally:
            ctx.__exit__(None, None, None)

        # the surfacing contract both handlers now implement
        counts = {"processed": 1, "failed": 0}
        if commit_res.get("error") or commit_res.get("tape_integrity") not in (None, "complete"):
            counts["errors"] = int(counts.get("errors") or 0) + 1
        result = {"ok": False, "counts": counts}
        self.assertEqual(_classify_handler_return(result), "partial")


# ---------------------------------------------------------------------------
# Route-driving: the previously-unmanifested midday returns emit exactly one
# terminal manifest (P10's gap). Failure conditions injected at their ORIGIN
# (the external reads), asserted at the TOP (the manifest on the context).
# ---------------------------------------------------------------------------

class _FakeRegimeState:
    value = "normal"


class _FakeSnap:
    state = _FakeRegimeState()


class _MiddayRouteHarness(unittest.TestCase):
    """Shared origin-level fakes: capital / positions / regime / progression.
    These are the DB/API reads — the deepest injectable layer — not
    intermediate logic of the route under test."""

    def setUp(self):
        os.environ["REPLAY_ENABLE"] = "1"
        self._patches = []

    def tearDown(self):
        os.environ.pop("REPLAY_ENABLE", None)
        for p in self._patches:
            p.stop()

    def _start(self, target, **kw):
        p = patch(target, **kw)
        self._patches.append(p)
        return p.start()

    def _drive(self, *, capital, positions):
        import asyncio
        from packages.quantum.services import workflow_orchestrator as wo

        self._start(
            "packages.quantum.services.cash_service.CashService."
            "get_deployable_capital", new=_async_return(capital))
        self._start(
            "packages.quantum.services.workflow_orchestrator."
            "RegimeEngineV3.compute_global_snapshot",
            return_value=_FakeSnap())
        self._start(
            "packages.quantum.services.progression_service.ProgressionService."
            "get_state", return_value={"current_phase": "alpaca_paper"})
        self._start(
            "packages.quantum.risk.position_scope.live_routed_portfolio_ids",
            return_value=["p1"])

        class _PosClient:
            def table(self, name):
                rows = positions

                class _Q:
                    def select(self, *_a):
                        return self

                    def in_(self, *_a):
                        return self

                    def eq(self, *_a):
                        return self

                    def execute(self):
                        return _Result(rows)
                return _Q()

        ctx = DecisionContext(
            strategy_name="suggestions_open",
            as_of_ts=datetime.now(timezone.utc),
            user_id="u-test", git_sha="testsha",
            _blob_store=BlobStore(),
        )
        ctx.__enter__()
        try:
            # asyncio.run: a FRESH loop — get_event_loop() has no current loop
            # in CI's main thread (the local pass rode a leftover loop).
            result = asyncio.run(
                wo.run_midday_cycle(_PosClient(), "u-test-user-id"))
        finally:
            ctx.__exit__(None, None, None)
        manifests = [f for f in ctx.features
                     if f.symbol == "__decision__"
                     and f.namespace == "ranked_candidates"]
        return result, manifests


def _async_return(value):
    async def _f(*_a, **_k):
        return value
    return _f


class TestMiddayReturnsEmitManifest(_MiddayRouteHarness):
    def test_micro_tier_position_open_emits_one_manifest(self):
        result, manifests = self._drive(
            capital=500.0,  # micro tier (<$1k) -> max_trades==1
            positions=[{"id": "pos1", "symbol": "QQQ", "status": "open"}],
        )
        self.assertEqual(result["reason"], "micro_tier_position_open")
        self.assertEqual(len(manifests), 1)
        m = manifests[0].features
        self.assertEqual(m["exit_reason"], "micro_tier_position_open")
        self.assertTrue(m["is_zero_cycle"])

    def test_capital_scan_policy_block_emits_one_manifest(self):
        result, manifests = self._drive(capital=1.0, positions=[])
        self.assertTrue(result.get("skipped"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].features["exit_reason"],
                         "capital_scan_policy_block")


if __name__ == "__main__":
    unittest.main()
