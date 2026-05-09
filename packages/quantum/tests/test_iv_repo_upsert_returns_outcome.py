"""Tests for #115 PR-A Layer 3+4 fix.

Three layers covered:
1. ``IVRepository.upsert_iv_point`` returns bool reflecting actual
   write outcome (Layer 4).
2. ``IVRepository.count_rows_for_date`` provides the verification
   primitive used by the handler's accounting check.
3. Handler's accounting verifies actual writes vs reported success
   (Layer 4 protection).

Migration validation lives in the migration's own ``DO $$`` blocks
(raises on apply if invariant violated). Class-prevention via the
post-loop accounting alert is exercised in the integration shape
test below.
"""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# sys.modules pollution remediation (test_weekly_report poisons
# iv_repository at import time).
for _modname in (
    "packages.quantum.services.iv_repository",
):
    sys.modules.pop(_modname, None)
_iv_repo_mod = importlib.import_module(
    "packages.quantum.services.iv_repository"
)
IVRepository = _iv_repo_mod.IVRepository
assert callable(IVRepository), "iv_repository was already mocked at file load"


HANDLER_PATH = (
    Path(__file__).parent.parent / "jobs" / "handlers"
    / "iv_daily_refresh.py"
)
REPO_PATH = (
    Path(__file__).parent.parent / "services" / "iv_repository.py"
)
MIGRATION_PATH = (
    Path(__file__).parent.parent.parent.parent / "supabase" / "migrations"
    / "20260509000000_add_underlying_iv_points_unique_constraint.sql"
)


def _make_supabase(upsert_data, raises=False, count_value=None):
    """Build a Supabase mock for upsert_iv_point + count_rows_for_date.

    upsert_data: list returned as `result.data` from upsert (None or
        empty triggers the 'silent rejection' branch).
    raises: if True, .upsert().execute() raises RuntimeError.
    count_value: integer returned from .select(count='exact').execute().count
    """
    sb = MagicMock()
    table_chain = MagicMock()
    upsert_chain = MagicMock()
    select_chain = MagicMock()
    eq_chain = MagicMock()

    # Upsert path
    table_chain.upsert.return_value = upsert_chain
    if raises:
        upsert_chain.execute.side_effect = RuntimeError(
            'duplicate key value violates unique constraint "..."'
        )
    else:
        upsert_chain.execute.return_value = MagicMock(data=upsert_data)

    # Count path: table.select("...", count="exact").eq(...).execute()
    table_chain.select.return_value = select_chain
    select_chain.eq.return_value = eq_chain
    eq_chain.execute.return_value = MagicMock(count=count_value)

    sb.table.return_value = table_chain
    return sb


def _payload_data():
    """Minimal payload dict matching what compute_atm_iv_target_from_chain
    produces (so the upsert builds a complete row)."""
    return {
        "iv_30d": 0.25,
        "iv1": 0.24,
        "iv2": 0.26,
        "strike1": 100.0,
        "strike2": 102.0,
        "expiry1": "2026-05-30",
        "expiry2": "2026-06-06",
        "iv_method": "var_interp_spot_atm",
        "quality_score": 90,
        "inputs": {"spot": 101.0, "target_dte": 30},
    }


class TestUpsertReturnsOutcome(unittest.TestCase):
    """Layer 4: upsert_iv_point must return True/False reflecting
    actual write outcome rather than always returning None."""

    def test_returns_true_on_successful_upsert_with_data(self):
        from datetime import datetime as _dt
        sb = _make_supabase(upsert_data=[{"id": "row-1"}])
        repo = IVRepository(sb)
        ok = repo.upsert_iv_point("AAPL", _payload_data(), _dt(2026, 5, 9))
        self.assertTrue(ok)

    def test_returns_false_when_upsert_raises(self):
        """Layer 3 manifestation: PostgreSQL 42P10 on missing UNIQUE
        constraint becomes a Python exception in the SDK call."""
        from datetime import datetime as _dt
        sb = _make_supabase(upsert_data=None, raises=True)
        repo = IVRepository(sb)
        ok = repo.upsert_iv_point("AAPL", _payload_data(), _dt(2026, 5, 9))
        self.assertFalse(ok)

    def test_returns_false_when_upsert_returns_empty_data(self):
        """Server-side silent rejection: PostgREST returns 200 with
        empty data array (e.g., RLS blocked the write). Pre-fix
        the wrapper would have treated this as success."""
        from datetime import datetime as _dt
        sb = _make_supabase(upsert_data=[])
        repo = IVRepository(sb)
        ok = repo.upsert_iv_point("AAPL", _payload_data(), _dt(2026, 5, 9))
        self.assertFalse(ok)


class TestCountRowsForDate(unittest.TestCase):
    """Layer 4 verification primitive."""

    def test_returns_count_from_supabase(self):
        sb = _make_supabase(upsert_data=None, count_value=68)
        repo = IVRepository(sb)
        self.assertEqual(repo.count_rows_for_date("2026-05-09"), 68)

    def test_returns_zero_when_no_rows(self):
        sb = _make_supabase(upsert_data=None, count_value=0)
        repo = IVRepository(sb)
        self.assertEqual(repo.count_rows_for_date("2026-05-09"), 0)

    def test_returns_sentinel_minus_one_on_query_failure(self):
        """If we can't query the table, the handler should know not
        to fire a false-positive accounting mismatch."""
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
            RuntimeError("DB unreachable")
        )
        repo = IVRepository(sb)
        self.assertEqual(repo.count_rows_for_date("2026-05-09"), -1)


class TestHandlerAccountingShape(unittest.TestCase):
    """Source-level guards on the handler's accounting + alert wiring."""

    @classmethod
    def setUpClass(cls):
        cls.src = HANDLER_PATH.read_text(encoding="utf-8")

    def test_handler_checks_upsert_return_value(self):
        """Pre-fix: stats['ok'] += 1 ran unconditionally after the
        upsert call. Post-fix: bound to write_succeeded."""
        self.assertIn("write_succeeded = iv_repo.upsert_iv_point(", self.src)
        self.assertIn("if write_succeeded:", self.src)

    def test_handler_uses_split_buckets(self):
        """missing_data and failed are distinct counts so the load-
        bearing 'ok' reflects only confirmed DB writes."""
        self.assertIn('"missing_data": 0', self.src)
        self.assertIn('stats["missing_data"] += 1', self.src)

    def test_handler_post_loop_accounting_check(self):
        """The verify-after-loop assertion is what makes Layer 4
        impossible to silently regress."""
        self.assertIn("count_rows_for_date(", self.src)
        self.assertIn("iv_handler_accounting_mismatch", self.src)
        # The alert fires only when actual_rows is a real count
        # (>= 0), not the -1 sentinel that means "couldn't verify"
        self.assertIn("actual_rows >= 0", self.src)

    def test_handler_returns_actual_row_count(self):
        """The job_runs.result envelope exposes both the handler's
        ok count AND the actual DB row count so post-mortem audits
        can detect Layer 4 regressions even if the alert path
        itself fails."""
        self.assertIn('"actual_rows_written"', self.src)
        self.assertIn('"accounting_match"', self.src)


class TestRepoSourceShape(unittest.TestCase):
    """Source-level guard on the repository's return-type contract."""

    @classmethod
    def setUpClass(cls):
        cls.src = REPO_PATH.read_text(encoding="utf-8")

    def test_upsert_signature_returns_bool(self):
        # Locate the def and verify the return annotation
        anchor = self.src.find("def upsert_iv_point(")
        self.assertGreater(anchor, 0)
        window = self.src[anchor:anchor + 400]
        self.assertIn("-> bool:", window)

    def test_upsert_no_silent_print_swallow(self):
        """The pre-fix `print(f"[IVRepo] Upsert failed for ...")`
        pattern must be gone — replaced by structured logger.error."""
        anchor = self.src.find("def upsert_iv_point(")
        self.assertGreater(anchor, 0)
        # Body extent: until next `def ` at same indentation
        end_match = self.src.find("\n    def ", anchor + 50)
        body = self.src[anchor:end_match] if end_match > 0 else self.src[anchor:]
        self.assertNotIn(
            "print(f\"[IVRepo] Upsert failed",
            body,
            "Pre-fix silent print swallow must be removed",
        )
        self.assertIn("logger.error", body)
        self.assertIn("iv_repo_upsert_failed", body)

    def test_count_rows_helper_present(self):
        self.assertIn("def count_rows_for_date(", self.src)


class TestMigrationShape(unittest.TestCase):
    """Source-level guard on the constraint-adding migration."""

    @classmethod
    def setUpClass(cls):
        cls.src = MIGRATION_PATH.read_text(encoding="utf-8")

    def test_migration_adds_unique_constraint(self):
        # Constraint must match the upsert's on_conflict spec exactly
        self.assertIn(
            "UNIQUE (underlying, as_of_date)",
            self.src,
        )
        self.assertIn(
            "underlying_iv_points_underlying_as_of_date_key",
            self.src,
        )

    def test_migration_idempotent(self):
        """Re-apply must not error."""
        self.assertIn("IF NOT EXISTS", self.src)

    def test_migration_self_verifies(self):
        """Inline DO $$ block raises if the constraint isn't present
        post-apply — fail-loud at apply time rather than silently
        partial."""
        self.assertIn("RAISE EXCEPTION", self.src)


if __name__ == "__main__":
    unittest.main()
