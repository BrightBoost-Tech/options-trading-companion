"""Mirror parity — candidate_disposition writer H7 subreason ↔ the
ctd_h7_subreason_required CHECK (20260719010000).

test_h7_subreason_migration_contract.py pins the CHECK's TEXT; this file pins
its BEHAVIOR and — the closure that matters — that the WRITER never emits a row
the CHECK would reject.

The constraint is:

    disposition <> 'h7_dropped'
    OR COALESCE(detail->>'h7_subreason', '') IN
       ('roundtrip_bp','quality_gate','sizing_zero','risk_budget',
        'account_capacity','unspecified')

Three-valued logic worth pinning (the #1281 live-PG truth table): detail NULL,
a MISSING key, and a JSON-null value ALL make ``detail->>'h7_subreason'`` SQL
NULL, which COALESCE(...,'') maps to '' (not allow-listed) → REJECT. An empty
string is likewise rejected. The 5 canonical values + the 'unspecified'
sentinel pass; every non-h7 disposition is exempt.

Then the behavioral parity: drive the REAL CandidateDispositionRecorder and
assert EVERY persisted row satisfies the predicate — in strict mode (invalid
h7 rows RAISE, never persist) and in soft mode (invalid h7 rows get the
allow-listed sentinel). The writer can never strand a row the CHECK rejects.
"""

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.quantum.services.candidate_disposition import (
    CandidateDispositionRecorder,
    H7_SUBREASON_UNSPECIFIED,
    H7_SUBREASONS,
    TABLE,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260719010000_h7_subreason_check.sql"
)

# The predicate's allow-list — the writer's canonical set + the sentinel. The
# text-parity test below pins this equal to the migration's actual CHECK list.
ALLOWED = frozenset(H7_SUBREASONS) | {H7_SUBREASON_UNSPECIFIED}

UID = "9d5f4c1e-0000-4000-8000-00000000ab01"
CYCLE_DATE = "2026-07-18"


# ── Python mirror of the SQL CHECK (three-valued logic) ─────────────────────
def ctd_h7_subreason_check(disposition, detail):
    """Faithful mirror of ctd_h7_subreason_required.

    ``disposition <> 'h7_dropped' OR COALESCE(detail->>'h7_subreason','') IN
    (allowlist)``. detail NULL / missing key / JSON-null value → SQL NULL →
    COALESCE '' → reject (when h7_dropped)."""
    if disposition != "h7_dropped":
        return True  # constraint exempt for every non-h7 disposition
    val = detail.get("h7_subreason") if isinstance(detail, dict) else None
    coalesced = "" if val is None else val
    return coalesced in ALLOWED


def _migration_check_list():
    body = "\n".join(
        ln for ln in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("--")
    )
    m = re.search(r"IN\s*\(([^)]+)\)", body, re.S)
    assert m is not None, "CHECK IN(...) allowlist not found"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


# ── Truth table (the #1281 live-PG expectations) ────────────────────────────
_TRUTH = [
    # (desc, disposition, detail, expected_pass)
    ("h7_valid_roundtrip", "h7_dropped", {"h7_subreason": "roundtrip_bp"}, True),
    ("h7_valid_quality", "h7_dropped", {"h7_subreason": "quality_gate"}, True),
    ("h7_valid_sizing", "h7_dropped", {"h7_subreason": "sizing_zero"}, True),
    ("h7_valid_riskbudget", "h7_dropped", {"h7_subreason": "risk_budget"}, True),
    ("h7_valid_capacity", "h7_dropped", {"h7_subreason": "account_capacity"}, True),
    ("h7_sentinel_unspecified", "h7_dropped",
     {"h7_subreason": "unspecified"}, True),
    ("h7_missing_key_rejected", "h7_dropped", {"reason": "x"}, False),
    ("h7_detail_none_rejected", "h7_dropped", None, False),
    ("h7_null_value_rejected", "h7_dropped", {"h7_subreason": None}, False),
    ("h7_empty_string_rejected", "h7_dropped", {"h7_subreason": ""}, False),
    ("h7_invalid_value_rejected", "h7_dropped",
     {"h7_subreason": "not_a_real_value"}, False),
    ("h7_wrong_key_rejected", "h7_dropped", {"subreason": "sizing_zero"}, False),
    # Non-h7 dispositions are exempt regardless of detail.
    ("nonh7_no_detail_exempt", "persisted_executable", None, True),
    ("nonh7_empty_detail_exempt", "rank_blocked", {}, True),
    ("nonh7_garbage_subreason_exempt", "allocator_dropped",
     {"h7_subreason": "garbage"}, True),
    ("nonh7_valid_subreason_exempt", "staged",
     {"h7_subreason": "sizing_zero"}, True),
]


class TestPredicateTruthTable(unittest.TestCase):
    def test_truth_table(self):
        for desc, disp, detail, expected in _TRUTH:
            self.assertEqual(
                ctd_h7_subreason_check(disp, detail), expected,
                f"{desc}: predicate disagreed",
            )

    def test_all_five_canonical_pass(self):
        for sub in H7_SUBREASONS:
            self.assertTrue(
                ctd_h7_subreason_check("h7_dropped", {"h7_subreason": sub}), sub)

    def test_sentinel_passes(self):
        self.assertTrue(ctd_h7_subreason_check(
            "h7_dropped", {"h7_subreason": H7_SUBREASON_UNSPECIFIED}))


class TestPredicateMatchesMigrationText(unittest.TestCase):
    def test_allowlist_is_five_canonical_plus_sentinel(self):
        self.assertEqual(ALLOWED, set(H7_SUBREASONS) | {H7_SUBREASON_UNSPECIFIED})
        self.assertEqual(len(ALLOWED), 6)

    def test_predicate_allowlist_equals_migration_allowlist(self):
        self.assertEqual(ALLOWED, _migration_check_list())

    def test_migration_is_disposition_scoped_and_coalesced(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("disposition <> 'h7_dropped'", sql)
        self.assertIn("COALESCE(detail->>'h7_subreason', '')", sql)


# ── Writer-output parity: no persisted row ever violates the CHECK ──────────
def _cand(strike_sell=28.0, **over):
    c = {
        "symbol": "SOFI", "ticker": "SOFI",
        "strategy": "LONG_CALL_DEBIT_SPREAD", "type": "LONG_CALL_DEBIT_SPREAD",
        "suggested_entry": 0.30, "ev": 30.0, "score": 65.0,
        "legs": [
            {"symbol": "SOFI260821C00026000", "side": "buy",
             "bid": 0.55, "ask": 0.65, "quantity": 1},
            {"symbol": f"SOFI260821C{int(strike_sell * 1000):08d}",
             "side": "sell", "bid": 0.25, "ask": 0.35, "quantity": 1},
        ],
    }
    c.update(over)
    return c


def _recorder(client):
    return CandidateDispositionRecorder(
        client, user_id=UID, cycle_date=CYCLE_DATE)


def _persisted_rows(client):
    return client.tables.get(TABLE, [])


def _assert_all_rows_satisfy_check(testcase, client):
    rows = _persisted_rows(client)
    testcase.assertGreater(len(rows), 0, "expected at least one persisted row")
    for row in rows:
        ok = ctd_h7_subreason_check(row.get("disposition"), row.get("detail"))
        testcase.assertTrue(
            ok,
            f"writer persisted a CHECK-violating row: "
            f"disposition={row.get('disposition')!r} detail={row.get('detail')!r}",
        )


class TestWriterOutputSatisfiesCheck(unittest.TestCase):
    def test_valid_h7_row_satisfies_check(self):
        client = FakeSupabase()
        rec = _recorder(client)
        c = _cand()
        rec.record_selected([c])
        rec.record_final(c, "h7_dropped",
                         detail={"reason": "sized_to_zero",
                                 "h7_subreason": "sizing_zero"})
        _assert_all_rows_satisfy_check(self, client)

    def test_soft_mode_sentinel_row_satisfies_check(self):
        # The KEY parity: a soft-fail (missing subreason) row carries the
        # allow-listed 'unspecified' sentinel, so the CHECK ACCEPTS it — the
        # writer's one-final invariant genuinely always wins.
        client = FakeSupabase()
        rec = _recorder(client)
        c = _cand()
        rec.record_selected([c])
        with patch.dict(os.environ,
                        {"CANDIDATE_DISPOSITION_STRICT_TAXONOMY": "0"}):
            rec.record_final(c, "h7_dropped", detail={"reason": "sized_to_zero"})
        rows = _persisted_rows(client)
        (row,) = [r for r in rows if r.get("is_final")]
        self.assertEqual(row["detail"]["h7_subreason"], H7_SUBREASON_UNSPECIFIED)
        _assert_all_rows_satisfy_check(self, client)

    def test_mixed_dispositions_all_satisfy_check(self):
        # A cycle with valid h7, non-h7, and a soft-fail h7 — every persisted
        # row (finals and the selected non-final) satisfies the CHECK.
        client = FakeSupabase()
        rec = _recorder(client)
        a, b, d = _cand(28.0), _cand(29.0), _cand(30.0)
        rec.record_selected([a, b, d])
        rec.record_final(a, "h7_dropped",
                         detail={"h7_subreason": "roundtrip_bp"})
        rec.record_final(b, "persisted_executable")
        with patch.dict(os.environ,
                        {"CANDIDATE_DISPOSITION_STRICT_TAXONOMY": "0"}):
            rec.record_final(d, "h7_dropped", detail={"reason": "no bp"})
        _assert_all_rows_satisfy_check(self, client)

    def test_strict_mode_invalid_h7_never_persists_a_row(self):
        # In strict mode the invalid h7 RAISES before writing → the CHECK is
        # never even reachable (no row exists to violate it).
        client = FakeSupabase()
        rec = _recorder(client)
        c = _cand()
        rec.record_selected([c])
        from packages.quantum.services.candidate_disposition import (
            H7SubreasonViolation,
        )
        with patch.dict(os.environ,
                        {"CANDIDATE_DISPOSITION_STRICT_TAXONOMY": "1"}):
            with self.assertRaises(H7SubreasonViolation):
                rec.record_final(c, "h7_dropped", detail={"reason": "x"})
        # No final row was persisted; the only row is the non-final selection.
        finals = [r for r in _persisted_rows(client) if r.get("is_final")]
        self.assertEqual(finals, [])
        # And every row that DID persist still satisfies the CHECK.
        for row in _persisted_rows(client):
            self.assertTrue(
                ctd_h7_subreason_check(row.get("disposition"), row.get("detail")))

    def test_superseded_retry_row_satisfies_check(self):
        # When a newer attempt supersedes an old h7 final, the demoted row's
        # disposition becomes 'superseded_retry' (non-h7) → CHECK-exempt.
        client = FakeSupabase()
        rec = _recorder(client)
        first, retry = _cand(), _cand()  # same identity, two attempts
        rec.record_selected([first])
        rec.record_final(first, "h7_dropped",
                         detail={"h7_subreason": "roundtrip_bp"})
        rec.record_selected([retry])
        rec.record_final(retry, "persisted_executable")
        _assert_all_rows_satisfy_check(self, client)
        dispositions = {r.get("disposition") for r in _persisted_rows(client)}
        self.assertIn("superseded_retry", dispositions)


if __name__ == "__main__":
    unittest.main()
