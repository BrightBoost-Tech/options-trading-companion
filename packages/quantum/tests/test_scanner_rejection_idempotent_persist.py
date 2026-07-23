"""P1-1 (2026-07-23): append-only IDEMPOTENT rejection persistence.

Drives the REAL persist route (``RejectionStats.record`` ->
``_persist_rejection``, the exact function production calls) against a fake
that models a Postgres table WITH the unique partial index the migration
creates — so a re-insert of the same ``event_id`` raises 23505 exactly like
production. No source-string pinning: every assertion is on the OUTPUT
(counters, the durable row store, the event_id carried in each attempt).

Contract proven here:
  * single success                         -> persisted_new=1
  * transient then success on a FRESH client -> retry_recovery + fresh client used
  * uncertain-commit then retry            -> exactly ONE row + duplicate_ack (load-bearing)
  * two legit identical-looking rejections -> TWO rows, distinct event_ids
  * concurrent writes                      -> bounded/safe, all distinct
  * all retries exhausted                  -> lost_after_retries + partial (persist_failures>0)
  * permanent (auth/perm) error            -> NO transient retry + permanent_failure
  * schema-absent (event_id column missing) -> typed permanent_failure, non-crashing (pre-apply)
  * final-flush at exit                    -> a lost row recovered on flush reclassifies
  * aggregate counts byte-identical         -> persistence never perturbs _counts
  * new rows carry job_run_id
  * event_id reused verbatim across retries (never a second identity)
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from packages.quantum.options_scanner import RejectionStats


# ── transient class-name match for _is_transient_disconnect (MRO) ──────────
class _RemoteProtocolError(Exception):
    pass


_RemoteProtocolError.__name__ = "RemoteProtocolError"


def _dup_error() -> Exception:
    # Shape mirrors a PostgREST/Postgres unique violation on the partial index.
    return Exception(
        'duplicate key value violates unique constraint '
        '"suggestion_rejections_event_id_key" (SQLSTATE 23505)'
    )


def _perm_error() -> Exception:
    return Exception("permission denied for table suggestion_rejections (42501)")


def _schema_absent_error() -> Exception:
    return Exception(
        "Could not find the 'event_id' column of 'suggestion_rejections' "
        "in the schema cache (PGRST204)"
    )


# ── DB fake with a REAL unique-index on event_id ───────────────────────────
class _DbFakeTable:
    def __init__(self, parent: "_DbFake", name: str):
        self._p = parent
        self._name = name
        self._payload: Optional[Dict[str, Any]] = None

    def insert(self, payload: Dict[str, Any]) -> "_DbFakeTable":
        self._payload = payload
        return self

    def execute(self) -> Any:
        p = self._p
        with p.lock:
            p.attempts.append(dict(self._payload))
            fault = p.next_fault()
            eid = self._payload.get("event_id")
            if fault == "transient_before":
                raise _RemoteProtocolError("Server disconnected")
            if fault == "permanent":
                raise _perm_error()
            if fault == "schema_absent":
                raise _schema_absent_error()
            # commit path (clean OR transient_after): enforce the unique index
            if eid in p.committed:
                raise _dup_error()
            p.committed[eid] = dict(self._payload)
            if fault == "transient_after":
                # Row landed, but the client never sees the ack (response lost).
                raise _RemoteProtocolError("Server disconnected")
            m = MagicMock()
            m.data = []
            return m


class _DbFake:
    """Models one Postgres table with the event_id unique partial index.

    ``committed`` (event_id -> payload) can be SHARED across fakes so a
    "fresh client" still hits the same database. ``faults`` is consumed one
    entry per execute()."""

    def __init__(self, faults: Optional[List[Optional[str]]] = None,
                 committed: Optional[Dict[str, Any]] = None):
        self.faults = list(faults or [])
        self.committed: Dict[str, Any] = committed if committed is not None else {}
        self.attempts: List[Dict[str, Any]] = []
        self._i = 0
        self.lock = threading.Lock()

    def next_fault(self) -> Optional[str]:
        f = self.faults[self._i] if self._i < len(self.faults) else None
        self._i += 1
        return f

    def table(self, name: str) -> _DbFakeTable:
        return _DbFakeTable(self, name)


def _stats(db: _DbFake, *, job_run_id: Optional[str] = None,
           client_factory=None) -> RejectionStats:
    return RejectionStats(
        supabase=db, cycle_date=date(2026, 7, 23), job_run_id=job_run_id,
        retry_sleep=MagicMock(), client_factory=client_factory,
    )


# ───────────────────────────────────────────────────────────────────────────
class TestSingleSuccess(unittest.TestCase):
    def test_single_success_persisted_new(self):
        db = _DbFake()
        rs = _stats(db)
        rs.set_symbol("SPY")
        rs.record("edge_below_minimum")
        d = rs.to_dict()
        self.assertEqual(d["persisted_new"], 1)
        self.assertEqual(d["duplicate_ack"], 0)
        self.assertEqual(d["retry_recovery"], 0)
        self.assertEqual(d["lost_after_retries"], 0)
        self.assertEqual(d["permanent_failure"], 0)
        self.assertEqual(len(db.committed), 1)
        self.assertEqual(len(db.attempts), 1)
        # partial driver clean
        self.assertEqual(d["persist_failures"], 0)


class TestTransientThenFreshClient(unittest.TestCase):
    def test_retry_uses_a_fresh_client(self):
        primary = _DbFake(faults=["transient_before"])
        fresh = _DbFake()  # succeeds
        rs = _stats(primary, client_factory=lambda: fresh)
        rs.set_symbol("QQQ")
        rs.record("spread_too_wide")
        d = rs.to_dict()
        # Recovered on the FRESH client, not the poisoned primary.
        self.assertEqual(d["retry_recovery"], 1)
        self.assertEqual(d["persisted_new"], 0)
        self.assertEqual(len(fresh.committed), 1, "fresh client got the row")
        self.assertEqual(len(primary.committed), 0, "poisoned primary wrote nothing")
        # event_id is IDENTICAL across the two attempts (never a second identity).
        self.assertEqual(len(primary.attempts), 1)
        self.assertEqual(len(fresh.attempts), 1)
        self.assertEqual(
            primary.attempts[0]["event_id"], fresh.attempts[0]["event_id"],
            "event_id must be reused verbatim across retries",
        )
        self.assertEqual(d["persist_failures"], 0)


class TestUncertainCommitDeduplicates(unittest.TestCase):
    """LOAD-BEARING: a response-lost-after-commit retry re-sends the SAME
    event_id; the unique index collapses it to a duplicate_ack — exactly ONE
    physical row, and NEVER an UPDATE."""

    def test_commit_then_lost_response_then_retry_one_row(self):
        # Shared store so the "fresh" retry client hits the same DB.
        shared: Dict[str, Any] = {}
        primary = _DbFake(faults=["transient_after"], committed=shared)
        rs = _stats(
            primary,
            client_factory=lambda: _DbFake(committed=shared),  # fresh handle, same DB
        )
        rs.set_symbol("SOFI")
        rs.record("execution_cost_exceeds_ev")
        d = rs.to_dict()
        self.assertEqual(d["duplicate_ack"], 1)
        self.assertEqual(d["persisted_new"], 0)
        self.assertEqual(d["retry_recovery"], 0)
        self.assertEqual(d["lost_after_retries"], 0)
        # EXACTLY ONE row in the DB despite two physical insert attempts.
        self.assertEqual(len(shared), 1)
        self.assertEqual(len(primary.attempts), 1)  # primary saw attempt 1
        # A duplicate_ack does not partial the job.
        self.assertEqual(d["persist_failures"], 0)


class TestTwoLegitimateRejectionsTwoRows(unittest.TestCase):
    def test_identical_looking_rejections_get_distinct_event_ids(self):
        db = _DbFake()
        rs = _stats(db)
        rs.set_symbol("NVDA")
        rs.record("execution_cost_exceeds_ev", strategy="IRON_CONDOR")
        rs.record("execution_cost_exceeds_ev", strategy="IRON_CONDOR")
        d = rs.to_dict()
        self.assertEqual(d["persisted_new"], 2)
        self.assertEqual(d["duplicate_ack"], 0)
        self.assertEqual(len(db.committed), 2, "two legitimate repeats -> two rows")
        eids = [a["event_id"] for a in db.attempts]
        self.assertEqual(len(set(eids)), 2, "distinct event_ids for distinct emissions")


class TestConcurrentWritesSafe(unittest.TestCase):
    def test_thread_pool_all_distinct_and_bounded(self):
        db = _DbFake()
        rs = _stats(db)

        def _worker(sym: str) -> None:
            rs.set_symbol(sym)
            rs.record("dte_out_of_range")

        symbols = [f"S{i}" for i in range(24)]
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_worker, symbols))

        d = rs.to_dict()
        self.assertEqual(d["persisted_new"], 24)
        self.assertEqual(len(db.committed), 24)
        eids = [p["event_id"] for p in db.committed.values()]
        self.assertEqual(len(set(eids)), 24, "no event_id collisions under concurrency")
        self.assertEqual(d["persist_failures"], 0)


class TestAllRetriesExhaustedIsPartial(unittest.TestCase):
    def test_exhausted_transient_lost_and_partials(self):
        n = 1 + len(RejectionStats.PERSIST_RETRY_BACKOFFS)
        db = _DbFake(faults=["transient_before"] * n)
        rs = _stats(db)  # no factory -> reuse (fake has no live transport)
        rs.set_symbol("MSFT")
        with self.assertLogs("packages.quantum.options_scanner", level="WARNING") as cm:
            rs.record("processing_error")
        d = rs.to_dict()
        self.assertEqual(d["lost_after_retries"], 1)
        self.assertEqual(d["persisted_new"], 0)
        self.assertEqual(len(db.attempts), n)
        # ONLY the loss counters partial the job.
        self.assertEqual(d["persist_failures"], 1)
        # aggregate flow untouched
        self.assertEqual(rs._counts["processing_error"], 1)
        joined = "\n".join(cm.output)
        self.assertIn("rejection_row_lost_after_retries", joined)
        self.assertIn("suggestion_rejections insert failed", joined)


class TestPermanentErrorNoRetry(unittest.TestCase):
    def test_permanent_is_not_retried_as_transient(self):
        db = _DbFake(faults=["permanent"])
        rs = _stats(db)
        rs.set_symbol("AAPL")
        rs.record("agent_veto")
        d = rs.to_dict()
        self.assertEqual(d["permanent_failure"], 1)
        self.assertEqual(d["lost_after_retries"], 0)
        self.assertEqual(len(db.attempts), 1, "permanent error must NOT retry")
        self.assertEqual(d["persist_failures"], 1)  # partials the job


class TestSchemaAbsentTypedNoop(unittest.TestCase):
    """Pre-apply tolerance: the event_id column not existing yet is a typed,
    non-crashing permanent_failure with no transient retry."""

    def test_column_missing_is_typed_and_non_crashing(self):
        db = _DbFake(faults=["schema_absent"])
        rs = _stats(db)
        rs.set_symbol("IWM")
        rs.record("no_chain")  # must NOT raise
        d = rs.to_dict()
        self.assertEqual(d["permanent_failure"], 1)
        self.assertEqual(len(db.attempts), 1, "schema error is not retried")
        self.assertEqual(rs._counts["no_chain"], 1, "aggregate still recorded")


class TestFinalFlushAtExit(unittest.TestCase):
    def test_flush_recovers_a_row_lost_inline(self):
        n = 1 + len(RejectionStats.PERSIST_RETRY_BACKOFFS)
        db = _DbFake(faults=["transient_before"] * n)
        rs = _stats(db)  # factory None -> flush refreshes to the same fake
        rs.set_symbol("DIA")
        rs.record("edge_below_minimum")
        # Inline: all attempts failed transiently -> counted lost, buffered.
        self.assertEqual(rs.to_dict()["lost_after_retries"], 1)
        self.assertEqual(len(db.committed), 0)
        # The transient burst clears; the final flush lands the row.
        db.faults = []
        snap = rs.flush()
        self.assertEqual(snap["lost_after_retries"], 0, "recovered by flush")
        self.assertEqual(snap["retry_recovery"], 1)
        self.assertEqual(len(db.committed), 1)
        # Post-flush the job is no longer partial for this row.
        self.assertEqual(rs.to_dict()["persist_failures"], 0)

    def test_flush_is_idempotent_and_safe_with_nothing_pending(self):
        db = _DbFake()
        rs = _stats(db)
        rs.set_symbol("X")
        rs.record("no_chain")
        first = rs.flush()   # nothing lost -> no-op
        second = rs.flush()  # safe to call again
        self.assertEqual(first, second)
        self.assertEqual(len(db.committed), 1)

    def test_flush_acks_a_row_that_actually_committed_inline(self):
        # Last inline attempt commits then loses the response -> counted lost,
        # but the row is really in the DB. flush re-sends the same event_id and
        # gets a duplicate -> reclassifies lost -> duplicate_ack (never a 2nd row).
        db = _DbFake(faults=["transient_before", "transient_before", "transient_after"])
        rs = _stats(db)
        rs.set_symbol("GLD")
        rs.record("spread_too_wide")
        self.assertEqual(rs.to_dict()["lost_after_retries"], 1)
        self.assertEqual(len(db.committed), 1, "row actually committed on the last attempt")
        snap = rs.flush()
        self.assertEqual(snap["lost_after_retries"], 0)
        self.assertEqual(snap["duplicate_ack"], 1)
        self.assertEqual(len(db.committed), 1, "still exactly one row")


class TestAggregateByteIdentical(unittest.TestCase):
    """Persistence outcome must never perturb the authoritative _counts."""

    def _seq(self, rs: RejectionStats) -> None:
        rs.set_symbol("PFE")
        rs.record("entry_cost_too_low")
        rs.record("entry_cost_too_low")
        rs.record_with_sample("spread_too_wide", {"k": "v"}, strategy="LONG_CALL")

    def test_counts_match_across_persist_outcomes(self):
        off = RejectionStats()
        self._seq(off)
        ok = _stats(_DbFake())
        self._seq(ok)
        perm = _stats(_DbFake(faults=["permanent", "permanent", "permanent"]))
        self._seq(perm)
        self.assertEqual(dict(off._counts), dict(ok._counts))
        self.assertEqual(dict(off._counts), dict(perm._counts))
        self.assertEqual(off.to_dict()["rejection_counts"], ok.to_dict()["rejection_counts"])
        self.assertEqual(off.to_dict()["rejection_counts"], perm.to_dict()["rejection_counts"])


class TestJobRunIdStamped(unittest.TestCase):
    def test_new_rows_carry_job_run_id(self):
        jid = "11111111-2222-3333-4444-555555555555"
        db = _DbFake()
        rs = _stats(db, job_run_id=jid)
        rs.set_symbol("SPY")
        rs.record("edge_below_minimum")
        row = next(iter(db.committed.values()))
        self.assertEqual(row["job_run_id"], jid)
        self.assertIn("event_id", row)

    def test_job_run_id_absent_when_not_threaded(self):
        db = _DbFake()
        rs = _stats(db)  # job_run_id=None
        rs.set_symbol("SPY")
        rs.record("edge_below_minimum")
        row = next(iter(db.committed.values()))
        self.assertNotIn("job_run_id", row)


if __name__ == "__main__":
    unittest.main()
