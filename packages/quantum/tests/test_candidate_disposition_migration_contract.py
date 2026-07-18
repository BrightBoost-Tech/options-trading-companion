"""Lane 4B — contract tests for the candidate_terminal_dispositions
migration FILE (unapplied by design; the operator applies it).

Pins the migration text to the schema the writer relies on:
  - one row per (cycle_id, candidate_fingerprint, attempt);
  - EXACTLY ONE final per identity via the partial unique on is_final;
  - the disposition CHECK taxonomy is set-equal to the writer's
    DISPOSITIONS constant (a drifted enum would strand writes);
  - final rows must carry a disposition;
  - service-role RLS;
  - retention index on cycle_date;
  - purely ADDITIVE: no DDL against any existing table.
"""

import re
import unittest
from pathlib import Path

from packages.quantum.services.candidate_disposition import DISPOSITIONS

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260717090000_candidate_terminal_dispositions.sql"
)


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def _sql_no_comments():
    return "\n".join(
        line for line in _sql().splitlines()
        if not line.strip().startswith("--")
    )


class TestMigrationFileContract(unittest.TestCase):
    def test_file_exists_with_expected_name(self):
        self.assertTrue(MIGRATION.is_file(), MIGRATION)

    def test_creates_the_table(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS candidate_terminal_dispositions",
            _sql(),
        )

    def test_identity_uniqueness(self):
        self.assertIn("UNIQUE (cycle_id, candidate_fingerprint, attempt)",
                      _sql())

    def test_one_final_partial_unique(self):
        sql = _sql()
        m = re.search(
            r"CREATE UNIQUE INDEX IF NOT EXISTS idx_ctd_one_final_per_identity"
            r"\s+ON candidate_terminal_dispositions\s*"
            r"\(cycle_id, candidate_fingerprint\)\s+WHERE is_final",
            sql,
        )
        self.assertIsNotNone(
            m, "partial unique (one final per identity) missing")

    def test_disposition_taxonomy_matches_writer(self):
        sql = _sql()
        m = re.search(r"disposition IN \(([^)]+)\)", sql, re.S)
        self.assertIsNotNone(m, "disposition CHECK missing")
        migration_set = set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
        self.assertEqual(migration_set, set(DISPOSITIONS))

    def test_final_rows_must_carry_a_disposition(self):
        self.assertIn("CHECK (NOT is_final OR disposition IS NOT NULL)",
                      _sql())

    def test_attempt_floor(self):
        self.assertIn("CHECK (attempt >= 1)", _sql())

    def test_rls_enabled_with_service_role_policy(self):
        sql = _sql()
        self.assertIn(
            "ALTER TABLE candidate_terminal_dispositions "
            "ENABLE ROW LEVEL SECURITY",
            sql,
        )
        self.assertIn("auth.role() = 'service_role'", sql)
        self.assertIn("auth.uid() = user_id", sql)

    def test_retention_index_on_cycle_date(self):
        self.assertIn("idx_ctd_cycle_date", _sql())

    def test_purely_additive_no_ddl_on_existing_tables(self):
        body = _sql_no_comments()
        # Every CREATE/ALTER targets only the new table.
        for stmt_table in re.findall(
            r"(?:CREATE TABLE IF NOT EXISTS|ALTER TABLE)\s+(\w+)", body
        ):
            self.assertEqual(stmt_table, "candidate_terminal_dispositions")
        # COMMENT ON statements are documentation, not DDL against a table —
        # drop them before asserting no other table is referenced.
        ddl_only = re.sub(r"COMMENT ON[^;]+;", "", body, flags=re.S)
        for name in ("trade_suggestions", "suggestion_rejections",
                     "paper_positions", "decision_runs", "job_runs"):
            self.assertNotIn(name, ddl_only,
                             f"migration must not touch {name}")

    def test_no_foreign_keys_by_design(self):
        # Disposition history must survive suggestion pruning and never
        # fail a cycle on referential order.
        self.assertNotIn("REFERENCES", _sql_no_comments())


if __name__ == "__main__":
    unittest.main()
