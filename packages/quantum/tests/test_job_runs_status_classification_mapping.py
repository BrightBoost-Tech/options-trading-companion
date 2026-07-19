"""Mirror parity — the job-runner status contract ↔ the job_runs_status_check
CHECK allowlist (20260718150000, the six + 'partial').

test_job_runs_partial_status_contract drives ONE handler shape end-to-end.
This file closes the named gap: the runner CLASSIFICATION → allowed-status
mapping. It drives the REAL ``_classify_handler_return`` over a fixture table of
handler-return shapes and asserts:

  1. each shape maps to the documented terminal status (behavioral, not a
     source-string assertion);
  2. the classifier's COMPLETE output range ({succeeded, partial}) is a subset
     of the CHECK allowlist — the classifier can never mint a status the
     constraint rejects;
  3. the JobStatus enum (every status the writers persist) is SET-EQUAL to the
     migration allowlist — no writer status is unlisted and the allowlist has
     no dead value;
  4. every client-side status literal in job_runs.py / db.py is in the
     allowlist (drift guard).
"""

import re
import unittest
from pathlib import Path

from packages.quantum.jobs.runner import _classify_handler_return
from packages.quantum.jobs.types import JobStatus

_REPO = Path(__file__).resolve().parents[3]
MIGRATION = (
    _REPO / "supabase" / "migrations"
    / "20260718150000_job_runs_status_check_partial.sql"
)


def _migration_allowed_statuses():
    body = "\n".join(
        ln for ln in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("--")
    )
    m = re.search(r"CHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)", body, re.S | re.I)
    assert m is not None, "CHECK (status IN (...)) not found"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


ALLOWED = _migration_allowed_statuses()


# ── (1)+(2) classifier return-shape → terminal status (behavioral) ──────────
# Each row: (desc, handler_return, expected_status). Drives the REAL classifier.
_CASES = [
    # --- succeeded: no failed-unit signal ---
    ("empty_dict", {}, "succeeded"),
    ("plain_ok", {"ok": True, "processed": 5}, "succeeded"),
    ("non_dict_none", None, "succeeded"),
    ("non_dict_str", "done", "succeeded"),
    ("non_dict_int", 7, "succeeded"),
    ("users_failed_zero", {"users_failed": 0}, "succeeded"),
    ("counts_errors_zero", {"counts": {"errors": 0}}, "succeeded"),
    ("error_key_falsy_none", {"error": None}, "succeeded"),
    ("error_key_falsy_empty", {"error": ""}, "succeeded"),
    # designed-false shapes the runner docstring calls out (NOT partial):
    ("ok_false_no_signal", {"ok": False}, "succeeded"),
    ("status_partial_string_only", {"status": "partial"}, "succeeded"),
    ("status_error_string_only", {"status": "error"}, "succeeded"),
    # non-int failure counters are ignored (no crash, no false partial):
    ("users_failed_non_int", {"users_failed": "two"}, "succeeded"),
    ("counts_errors_non_int", {"counts": {"errors": "lots"}}, "succeeded"),
    ("counts_not_a_dict", {"counts": 3}, "succeeded"),
    # --- partial: a real failed-unit signal ---
    ("users_failed_positive", {"users_failed": 2}, "partial"),
    ("counts_errors_positive", {"counts": {"errors": 1}}, "partial"),
    ("error_key_truthy", {"error": "boom"}, "partial"),
    ("error_dict_truthy", {"error": {"msg": "x"}}, "partial"),
    ("both_signals", {"users_failed": 1, "counts": {"errors": 3}}, "partial"),
]


class TestClassifierMapping(unittest.TestCase):
    def test_each_shape_maps_as_documented(self):
        for desc, ret, expected in _CASES:
            self.assertEqual(
                _classify_handler_return(ret), expected,
                f"{desc}: classifier mapped {ret!r} wrongly",
            )

    def test_every_classified_status_is_allowlisted(self):
        for desc, ret, _expected in _CASES:
            status = _classify_handler_return(ret)
            self.assertIn(
                status, ALLOWED,
                f"{desc}: classifier produced non-allowlisted status {status!r}",
            )

    def test_classifier_output_range_is_exactly_succeeded_and_partial(self):
        produced = {_classify_handler_return(ret) for _d, ret, _e in _CASES}
        self.assertEqual(produced, {"succeeded", "partial"})
        # And that range is inside the CHECK allowlist.
        self.assertTrue(produced <= ALLOWED)


# ── (3) full status contract ↔ the CHECK allowlist ──────────────────────────
class TestStatusEnumParity(unittest.TestCase):
    def test_migration_allowlist_is_the_six_plus_partial(self):
        self.assertEqual(ALLOWED, {
            "queued", "running", "succeeded", "failed_retryable",
            "dead_lettered", "cancelled", "partial",
        })

    def test_job_status_enum_is_set_equal_to_allowlist(self):
        enum_values = {s.value for s in JobStatus}
        self.assertEqual(
            enum_values, ALLOWED,
            "JobStatus enum and the job_runs_status_check allowlist have drifted",
        )

    def test_partial_is_present_both_sides(self):
        self.assertIn("partial", ALLOWED)
        self.assertIn("partial", {s.value for s in JobStatus})


# ── (4) writer status literals are all allowlisted (drift guard) ────────────
class TestWriterLiteralsAllowlisted(unittest.TestCase):
    def _status_literals(self, rel_path):
        src = (_REPO / rel_path).read_text(encoding="utf-8")
        return set(re.findall(r'"status":\s*"([a-z_]+)"', src))

    def test_job_runs_py_writes_only_allowlisted_statuses(self):
        lits = self._status_literals("packages/quantum/jobs/job_runs.py")
        self.assertTrue(lits, "no status literals found (parser drift?)")
        self.assertTrue(
            lits <= ALLOWED,
            f"job_runs.py writes non-allowlisted status(es): {lits - ALLOWED}",
        )

    def test_db_py_writes_only_allowlisted_statuses(self):
        lits = self._status_literals("packages/quantum/jobs/db.py")
        self.assertTrue(
            lits <= ALLOWED,
            f"db.py writes non-allowlisted status(es): {lits - ALLOWED}",
        )


if __name__ == "__main__":
    unittest.main()
