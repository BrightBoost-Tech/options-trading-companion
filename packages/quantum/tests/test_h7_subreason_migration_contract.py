"""Lane B — contract tests for the h7_subreason CHECK migration FILE
(20260719010000_h7_subreason_check.sql, unapplied by design).

Pins the migration text to the writer contract:
  - the CHECK's h7_subreason IN-list is set-equal to the writer's
    H7_SUBREASONS frozenset (a drifted enum would strand writes / mislabel);
  - the guard is disposition-scoped (disposition <> 'h7_dropped' OR ...), so
    non-h7 rows are unaffected;
  - added NOT VALID (writer-first backstop; VALIDATE is a follow-up);
  - the sentinel 'unspecified' is NOT in the DB allowlist (crisp taxonomy —
    the writer's soft-fail reconciliation is documented in the file);
  - purely ADDITIVE: only ever touches the Lane-4B table; no new value in the
    parent disposition enum (that CHECK lives in the earlier migration and is
    untouched here).
"""

import re
import unittest
from pathlib import Path

from packages.quantum.services.candidate_disposition import (
    H7_SUBREASONS,
    H7_SUBREASON_UNSPECIFIED,
)

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260719010000_h7_subreason_check.sql"
)


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def _sql_no_line_comments():
    return "\n".join(
        line for line in _sql().splitlines()
        if not line.strip().startswith("--")
    )


class TestH7SubreasonMigrationContract(unittest.TestCase):
    def test_file_exists_with_expected_name(self):
        self.assertTrue(MIGRATION.is_file(), MIGRATION)

    def test_adds_named_check_constraint(self):
        self.assertIn("ADD CONSTRAINT ctd_h7_subreason_required", _sql())
        self.assertIn("CHECK (", _sql())

    def test_in_list_is_set_equal_to_writer_frozenset(self):
        sql = _sql()
        m = re.search(r"h7_subreason'\)\s*IN\s*\(([^)]+)\)", sql, re.S)
        self.assertIsNotNone(m, "h7_subreason IN(...) allowlist missing")
        migration_set = set(re.findall(r"'([a-z_]+)'", m.group(1)))
        self.assertEqual(migration_set, set(H7_SUBREASONS))

    def test_guard_is_disposition_scoped(self):
        # Non-h7 rows are exempt; the constraint only binds h7_dropped.
        self.assertIn("disposition <> 'h7_dropped'", _sql())

    def test_sentinel_not_in_db_allowlist(self):
        sql = _sql()
        m = re.search(r"h7_subreason'\)\s*IN\s*\(([^)]+)\)", sql, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn(H7_SUBREASON_UNSPECIFIED,
                         set(re.findall(r"'([a-z_]+)'", m.group(1))))

    def test_added_not_valid(self):
        # NOT VALID: never scans existing rows at add time (safe on a live
        # table); VALIDATE is the operator's documented follow-up.
        self.assertIn("NOT VALID", _sql())

    def test_purely_additive_only_the_lane4b_table(self):
        body = _sql_no_line_comments()
        for stmt_table in re.findall(r"ALTER TABLE\s+(\w+)", body):
            self.assertEqual(stmt_table, "candidate_terminal_dispositions")
        # No new disposition value nor DDL against any other table.
        for name in ("trade_suggestions", "suggestion_rejections",
                     "paper_positions", "decision_runs", "job_runs"):
            self.assertNotIn(name, body, f"migration must not touch {name}")

    def test_no_new_disposition_value(self):
        # The parent taxonomy is untouched — this migration adds a jsonb-detail
        # CHECK only, never a new top-level disposition string.
        self.assertNotIn("disposition IN (", _sql())


if __name__ == "__main__":
    unittest.main()
