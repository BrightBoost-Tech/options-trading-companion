"""P1-1 (2026-07-23) — SQL-mirror drift-lock for the suggestion_rejections
event_id migration FILE.

Pins the migration text to the exact schema the idempotent persistence code
relies on, and asserts it stays purely ADDITIVE + idempotent (so it can be
applied before the code merges, migration-before-merge, and re-run safely):
  - ADD COLUMN IF NOT EXISTS event_id uuid;
  - a UNIQUE index on (event_id) that is PARTIAL (WHERE event_id IS NOT NULL),
    so the 14,217 historical NULL rows coexist untouched (no backfill);
  - IF NOT EXISTS on the index (idempotent / re-runnable);
  - NO backfill / UPDATE / DELETE (append-only; historical rows byte-identical);
  - the only table touched is suggestion_rejections.
"""

import re
import unittest
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260723150000_suggestion_rejections_event_id.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _sql_no_comments() -> str:
    return "\n".join(
        line for line in _sql().splitlines()
        if not line.strip().startswith("--")
    )


class TestMigrationFileContract(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(MIGRATION.is_file(), MIGRATION)

    def test_filename_sorts_after_baseline(self):
        # Contract: strictly after 20260721010500 and after the latest existing
        # migration, so it applies last. 14-digit repo convention.
        self.assertGreater(MIGRATION.name, "20260721010500")
        self.assertTrue(MIGRATION.name.startswith("20260723"))

    def test_adds_event_id_column_idempotently(self):
        m = re.search(
            r"ALTER TABLE\s+public\.suggestion_rejections\s+"
            r"ADD COLUMN IF NOT EXISTS\s+event_id\s+uuid\s*;",
            _sql(), re.I | re.S,
        )
        self.assertIsNotNone(m, "ADD COLUMN IF NOT EXISTS event_id uuid missing")

    def test_unique_partial_index_where_not_null(self):
        sql = _sql()
        m = re.search(
            r"CREATE UNIQUE INDEX IF NOT EXISTS\s+"
            r"suggestion_rejections_event_id_key\s+"
            r"ON\s+public\.suggestion_rejections\s*\(\s*event_id\s*\)\s+"
            r"WHERE\s+event_id\s+IS\s+NOT\s+NULL",
            sql, re.I | re.S,
        )
        self.assertIsNotNone(
            m, "UNIQUE PARTIAL INDEX ON (event_id) WHERE event_id IS NOT NULL missing")

    def test_no_backfill_or_mutation_of_existing_rows(self):
        # COMMENT ON statements are documentation prose (they mention "INSERT",
        # "UPDATE" etc.); strip them before checking the DDL body for mutations.
        ddl_only = re.sub(
            r"COMMENT ON[^;]+;", "", _sql_no_comments(), flags=re.S
        ).upper()
        for forbidden in ("UPDATE ", "DELETE ", "INSERT ", "DROP TABLE", "TRUNCATE"):
            self.assertNotIn(
                forbidden, ddl_only,
                f"migration must be append-only; found {forbidden!r} "
                "(historical rows must stay byte-identical, no backfill)")

    def test_only_touches_suggestion_rejections(self):
        body = _sql_no_comments()
        for stmt_table in re.findall(
            r"(?:ALTER TABLE|CREATE (?:UNIQUE )?INDEX[^\n]*?ON)\s+(?:public\.)?(\w+)",
            body, re.I,
        ):
            self.assertEqual(stmt_table, "suggestion_rejections",
                             f"migration touched unexpected object: {stmt_table}")

    def test_no_non_partial_unique_index_variant(self):
        # A NON-partial unique index would also enforce single-NULL semantics on
        # some engines; the contract requires the partial form explicitly.
        sql = _sql()
        # Every "CREATE UNIQUE INDEX ... (event_id)" must carry a WHERE clause.
        for m in re.finditer(r"CREATE UNIQUE INDEX[^;]+;", sql, re.I | re.S):
            self.assertIn("WHERE", m.group(0).upper(),
                          "unique index on event_id must be PARTIAL (WHERE ...)")


if __name__ == "__main__":
    unittest.main()
