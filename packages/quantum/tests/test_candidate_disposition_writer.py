"""Lane 4B — candidate terminal-disposition WRITER contract tests.

Covers (STEP 3 of the build spec):
  - identity/fingerprint stability: the pre-persist candidate fingerprint
    REUSES the legs_fingerprint convention and equals the fingerprint of the
    order_json the midday writer would persist (size/price-excluded,
    leg-order-independent);
  - one-final-per-identity: a re-final of the SAME attempt refines the row;
    a final on a NEWER attempt demotes the old final to superseded_retry
    (supersede semantics, never a violation);
  - schema-absent (migration unapplied) -> TYPED no-op with a visible
    counter, zero crashes, and no further client traffic;
  - generic write failure / invalid disposition / missing client -> counted,
    loud, never raises.

Uses the hardened contract fake from test_prerejection_fork_e19 (the same
fake the full-route tests drive) so writer behavior here and route behavior
there share one database contract.
"""

import unittest

from packages.quantum.services.candidate_disposition import (
    DISPOSITIONS,
    TABLE,
    CandidateDispositionRecorder,
    candidate_fingerprint,
)
from packages.quantum.services.options_utils import compute_legs_fingerprint
from packages.quantum.services.workflow_orchestrator import (
    build_midday_order_json,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase

UID = "9d5f4c1e-0000-4000-8000-000000000001"
CYCLE_DATE = "2026-07-17"


def _cand(strike_sell=28.0, entry=0.30, qty=1, **over):
    c = {
        "symbol": "SOFI", "ticker": "SOFI",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "type": "LONG_CALL_DEBIT_SPREAD",
        "suggested_entry": entry, "ev": 30.0, "score": 65.0,
        "legs": [
            {"symbol": "SOFI260821C00026000", "side": "buy",
             "bid": 0.55, "ask": 0.65, "quantity": qty},
            {"symbol": f"SOFI260821C{int(strike_sell * 1000):08d}",
             "side": "sell", "bid": 0.25, "ask": 0.35, "quantity": qty},
        ],
    }
    c.update(over)
    return c


def _recorder(client, **kw):
    return CandidateDispositionRecorder(
        client, user_id=UID, cycle_date=CYCLE_DATE, **kw
    )


def _rows(client):
    return client.tables.get(TABLE, [])


def _final_rows(client):
    return [r for r in _rows(client) if r.get("is_final")]


# ─────────────────────────────────────────────────────────────────
# Schema-absent fake: the designed pre-migration state. Raises the
# PostgREST missing-table signature for OUR table only; everything
# else behaves like the shared contract fake.
# ─────────────────────────────────────────────────────────────────
class _MissingTable(Exception):
    pass


class SchemaAbsentFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.ctd_table_calls = 0

    def table(self, name):
        if name == TABLE:
            self.ctd_table_calls += 1

            class _Raise:
                def upsert(self, *a, **k):
                    return self

                def update(self, *a, **k):
                    return self

                def eq(self, *a, **k):
                    return self

                def neq(self, *a, **k):
                    return self

                def execute(self):
                    raise _MissingTable(
                        "{'code': 'PGRST205', 'message': \"Could not find "
                        "the table 'public.candidate_terminal_dispositions' "
                        "in the schema cache\"}"
                    )

            return _Raise()
        return super().table(name)


class TestFingerprintIdentity(unittest.TestCase):
    def test_reuses_legs_fingerprint_convention(self):
        c = _cand()
        self.assertEqual(
            candidate_fingerprint(c),
            compute_legs_fingerprint({"legs": c["legs"]}),
        )

    def test_equals_persisted_order_json_fingerprint(self):
        """The identity computed pre-persist (from candidate legs) must equal
        the legs_fingerprint the midday writer stamps on the persisted row
        (computed from build_midday_order_json output)."""
        c = _cand()
        order_json = build_midday_order_json(c, contracts=3)
        self.assertEqual(
            candidate_fingerprint(c), compute_legs_fingerprint(order_json)
        )

    def test_size_and_price_independent(self):
        self.assertEqual(
            candidate_fingerprint(_cand(entry=0.30, qty=1)),
            candidate_fingerprint(_cand(entry=0.95, qty=7)),
        )

    def test_leg_order_independent(self):
        a = _cand()
        b = _cand()
        b["legs"] = list(reversed(b["legs"]))
        self.assertEqual(candidate_fingerprint(a), candidate_fingerprint(b))

    def test_different_structure_different_fingerprint(self):
        self.assertNotEqual(
            candidate_fingerprint(_cand(strike_sell=28.0)),
            candidate_fingerprint(_cand(strike_sell=29.0)),
        )

    def test_legless_candidate_never_collides_with_real_hash(self):
        fp = candidate_fingerprint({"ticker": "XYZ", "strategy": "S"})
        self.assertTrue(fp.startswith("nolegs:"))


class TestAttemptAndPrimaryFlag(unittest.TestCase):
    def test_attempt_increments_per_identity(self):
        rec = _recorder(FakeSupabase())
        a, b = _cand(), _cand()  # distinct dicts, same structure
        rec.record_selected([a])
        rec.record_selected([b])
        attempts = sorted(r["attempt"] for r in _rows(rec._sb))
        self.assertEqual(attempts, [1, 2])

    def test_primary_default_true_fallback_flag_false(self):
        rec = _recorder(FakeSupabase())
        primary = _cand()
        fallback = _cand(strike_sell=29.0, is_fallback_strategy=True)
        rec.record_selected([primary, fallback])
        by_fp = {r["candidate_fingerprint"]: r for r in _rows(rec._sb)}
        self.assertTrue(by_fp[candidate_fingerprint(primary)]["is_primary"])
        self.assertFalse(by_fp[candidate_fingerprint(fallback)]["is_primary"])

    def test_selection_rows_are_selected_non_final(self):
        rec = _recorder(FakeSupabase())
        rec.record_selected([_cand()])
        (row,) = _rows(rec._sb)
        self.assertTrue(row["selected"])
        self.assertFalse(row["is_final"])
        self.assertIsNone(row["disposition"])
        self.assertEqual(row["cycle_id"], rec.cycle_id)
        self.assertIsNotNone(row.get("selected_at"))
        self.assertIsNotNone(row.get("code_sha"))
        self.assertEqual(rec.counters["attempts_recorded"], 1)


class TestOneFinalPerIdentity(unittest.TestCase):
    def test_refinal_same_attempt_refines_not_duplicates(self):
        rec = _recorder(FakeSupabase())
        c = _cand()
        rec.record_selected([c])
        rec.record_final(c, "rank_blocked",
                         detail={"reason": "edge_below_minimum",
                                 "risk_adjusted_ev": -999.0})
        rec.record_final(c, "rank_blocked",
                         detail={"status": "NOT_EXECUTABLE"},
                         suggestion_id="1e8a0f9c-0000-4000-8000-00000000aaaa")
        rows = _rows(rec._sb)
        self.assertEqual(len(rows), 1)  # one identity, one attempt, one row
        (row,) = rows
        self.assertTrue(row["is_final"])
        self.assertEqual(row["disposition"], "rank_blocked")
        # details MERGED across the refinement
        self.assertEqual(row["detail"]["reason"], "edge_below_minimum")
        self.assertEqual(row["detail"]["status"], "NOT_EXECUTABLE")
        self.assertEqual(row["suggestion_id"],
                         "1e8a0f9c-0000-4000-8000-00000000aaaa")

    def test_second_final_on_new_attempt_supersedes_old(self):
        rec = _recorder(FakeSupabase())
        first, retry = _cand(), _cand()  # same identity, two attempts
        rec.record_selected([first])
        rec.record_final(first, "h7_dropped", detail={"reason": "h7_prefilter"})
        rec.record_selected([retry])
        rec.record_final(retry, "persisted_executable")

        finals = _final_rows(rec._sb)
        self.assertEqual(len(finals), 1, "exactly ONE final per identity")
        self.assertEqual(finals[0]["attempt"], 2)
        self.assertEqual(finals[0]["disposition"], "persisted_executable")

        old = [r for r in _rows(rec._sb) if r["attempt"] == 1][0]
        self.assertFalse(old["is_final"])
        self.assertEqual(old["disposition"], "superseded_retry")

    def test_distinct_identities_each_get_a_final(self):
        rec = _recorder(FakeSupabase())
        a, b = _cand(strike_sell=28.0), _cand(strike_sell=29.0)
        rec.record_selected([a, b])
        rec.record_final(a, "allocator_dropped")
        rec.record_final(b, "persisted_executable")
        finals = _final_rows(rec._sb)
        self.assertEqual(len(finals), 2)
        self.assertEqual(
            {f["disposition"] for f in finals},
            {"allocator_dropped", "persisted_executable"},
        )

    def test_final_for_unregistered_candidate_registers_first(self):
        rec = _recorder(FakeSupabase())
        c = _cand()
        rec.record_final(c, "h7_dropped")
        (row,) = _rows(rec._sb)
        self.assertTrue(row["is_final"])
        self.assertEqual(row["attempt"], 1)

    def test_persisted_fingerprint_mismatch_recorded_not_switched(self):
        rec = _recorder(FakeSupabase())
        c = _cand()
        rec.record_selected([c])
        rec.record_final(c, "persisted_executable",
                         fingerprint="somehow-different")
        (row,) = _final_rows(rec._sb)
        self.assertEqual(row["candidate_fingerprint"],
                         candidate_fingerprint(c))
        self.assertEqual(row["detail"]["persisted_fingerprint_mismatch"],
                         "somehow-different")


class TestFailSoft(unittest.TestCase):
    def test_schema_absent_is_typed_noop_with_counter(self):
        client = SchemaAbsentFake()
        rec = _recorder(client)
        c = _cand()
        rec.record_selected([c])          # first touch trips detection
        calls_after_detection = client.ctd_table_calls
        rec.record_final(c, "h7_dropped")  # no-op, no client traffic
        rec.record_final(c, "rank_blocked")

        d = rec.counters_dict()
        self.assertTrue(d["table_missing"])
        self.assertEqual(d["table_missing_noops"], 3)
        self.assertEqual(d["write_failures"], 0)
        self.assertEqual(d["attempts_recorded"], 0)
        self.assertEqual(d["finals_recorded"], 0)
        self.assertEqual(client.ctd_table_calls, calls_after_detection,
                         "post-detection writes must not touch the client")
        self.assertNotIn(TABLE, client.tables)

    def test_generic_write_failure_counted_never_raises(self):
        client = FakeSupabase()
        client.raise_when(TABLE, "upsert")
        rec = _recorder(client)
        c = _cand()
        rec.record_selected([c])
        rec.record_final(c, "h7_dropped")
        self.assertGreaterEqual(rec.counters["write_failures"], 1)
        self.assertFalse(rec.counters_dict()["table_missing"])
        self.assertEqual(rec.counters["finals_recorded"], 0)

    def test_invalid_disposition_refused_loudly(self):
        client = FakeSupabase()
        rec = _recorder(client)
        rec.record_final(_cand(), "vaporized")  # not in the taxonomy
        self.assertEqual(_rows(client), [])
        self.assertEqual(rec.counters["write_failures"], 1)

    def test_none_client_disabled_never_raises(self):
        rec = _recorder(None)
        c = _cand()
        rec.record_selected([c])
        rec.record_final(c, "h7_dropped")
        d = rec.counters_dict()
        self.assertEqual(d["attempts_recorded"], 0)
        self.assertEqual(d["finals_recorded"], 0)
        self.assertEqual(d["write_failures"], 0)

    def test_taxonomy_matches_spec(self):
        self.assertEqual(DISPOSITIONS, {
            "scanner_rejected", "h7_dropped", "allocator_dropped",
            "rank_blocked", "persisted_blocked", "persisted_executable",
            "staged", "broker_submitted", "filled", "superseded_retry",
        })


if __name__ == "__main__":
    unittest.main()
