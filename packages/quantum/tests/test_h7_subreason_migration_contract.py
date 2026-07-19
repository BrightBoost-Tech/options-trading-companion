"""Lane B — contract tests for the h7_subreason CHECK migration FILE
(20260719010000_h7_subreason_check.sql, unapplied by design).

Pins the migration text to the writer contract (amended per #1281 review):
  - the CHECK's allowlist is set-equal to H7_SUBREASONS + the 'unspecified'
    sentinel (SIX values) — the sentinel is accepted ON PURPOSE so the writer's
    demote-then-retry fallback can never strand a candidate with zero finals;
  - presence is enforced via COALESCE(...,'') so a MISSING h7_subreason key on
    an h7_dropped row is rejected (NULL IN (...) would otherwise pass a CHECK);
  - the guard is disposition-scoped (disposition <> 'h7_dropped' OR ...), so
    non-h7 rows are unaffected;
  - added NOT VALID (writer-first backstop; enforces new writes at ADD time,
    VALIDATE only scans pre-existing rows);
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


def _check_in_list():
    """The value list inside the CHECK's COALESCE(...) IN (...). Parsed from
    the comment-stripped SQL so a prose 'IN (…)' in a -- line can't leak in."""
    body = _sql_no_line_comments()
    m = re.search(r"IN\s*\(([^)]+)\)", body, re.S)
    assert m is not None, "CHECK IN(...) allowlist missing"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


class TestH7SubreasonMigrationContract(unittest.TestCase):
    def test_file_exists_with_expected_name(self):
        self.assertTrue(MIGRATION.is_file(), MIGRATION)

    def test_adds_named_check_constraint(self):
        self.assertIn("ADD CONSTRAINT ctd_h7_subreason_required", _sql())
        self.assertIn("CHECK (", _sql())

    def test_allowlist_is_five_canonical_plus_sentinel(self):
        # Six values: the writer's canonical frozenset + the soft-fail sentinel.
        self.assertEqual(
            _check_in_list(),
            set(H7_SUBREASONS) | {H7_SUBREASON_UNSPECIFIED},
        )

    def test_sentinel_accepted_so_invariant_wins(self):
        # The sentinel MUST be allow-listed: a rejected soft-fail write would,
        # via the writer's demote-then-retry path, leave zero active finals.
        self.assertIn(H7_SUBREASON_UNSPECIFIED, _check_in_list())

    def test_canonical_five_all_present(self):
        self.assertTrue(set(H7_SUBREASONS).issubset(_check_in_list()))

    def test_missing_key_rejected_via_coalesce(self):
        # COALESCE(...,'') maps an absent key to '' (not allow-listed) so a bare
        # h7_dropped row is rejected — NULL IN (...) would otherwise pass.
        self.assertIn("COALESCE(detail->>'h7_subreason', '')", _sql())

    def test_guard_is_disposition_scoped(self):
        # Non-h7 rows are exempt; the constraint only binds h7_dropped.
        self.assertIn("disposition <> 'h7_dropped'", _sql())

    def test_added_not_valid(self):
        # NOT VALID: enforces on every NEW write at ADD time; only skips the
        # one-time scan of PRE-EXISTING rows (safe on a live table).
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
