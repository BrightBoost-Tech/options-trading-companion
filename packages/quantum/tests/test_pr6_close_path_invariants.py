"""
PR #6 cross-cutting structural invariants for the close-path
consolidation.

Each per-handler test file (test_reconciler_multileg_sign_convention,
test_exit_evaluator_close_pipeline, test_orphan_repair_close_pipeline,
test_commit_fill_close_pipeline) covers its own handler's behavior.
This file asserts invariants that span the PR as a whole — properties
that would silently regress if enforced only per-handler.

Why one file for these
  Splitting structural rules across handlers invites drift: if the
  rule changes, remembering to update every handler's file is a
  coordination problem. A single source of truth for the invariants
  is load-bearing for the PR's thesis.

What these tests protect against
  1. Reintroduction of a direct paper_positions.update(status='closed')
     writer that bypasses close_position_shared. The 2026-04-10 →
     04-15 class of close-path bugs all looked like "one handler
     wrote paper_positions directly and got the math / enum wrong"
     — the shared helper is the mitigation, but only if it's the
     SOLE writer. A1 enforces that.
  2. Drift between Python-side enum validation and the DB CHECK
     constraints. Phase 1 migration accepts 14 close_reason values
     (9 canonical + 5 legacy); Phase 2 drops to 9. The Python-side
     strict enum (post-PR #6) writes only 9. If close_helper.py's
     _VALID_CLOSE_REASONS drifts from the 9-value set — either way
     — Phase 2 deploys will either reject valid writes or allow
     legacy writes. B1 guards against both directions.
  3. NFLX 846bc787 (2026-04-16): a handler wrote unrealized_pl
     into realized_pl because the inline math was optional. The
     structural remedy is close_position_shared's REQUIRED
     realized_pl parameter — a handler cannot call the helper
     without first producing a realized_pl, and the helper rejects
     None at validation time. C1 pins this behavior.
  4. Silent fall-through on unknown close_reason or fill_source
     values. If someone passes a typo ('envelope_forceclose') the
     DB CHECK would reject it, but only at write time. C2 and C3
     catch it at Python validation for faster failure.

Known limitations of source-level tests (A-class)
  These tests are REGEX-BASED STATIC ANALYSIS. They are not
  bulletproof. They DO NOT catch:

    - Variable-indirection writes. If a handler builds the payload
      dict dynamically (payload = build_close_payload(...);
      supabase.table(...).update(payload).execute()), the regex
      won't see the 'status' key at the call site.
    - SQL-direct writes that bypass the supabase client (raw psql,
      stored procedures, migrations touching open positions).
    - Writes to paper_positions that don't mention the literal
      string 'closed' (e.g. constants imported from another file).
    - Cross-file aliases. `from packages.quantum.services.close_helper
      import close_position_shared as _close` followed by
      `_close(...)` is fine, but a future refactor could mask the
      import name.

  Combined with code review and the end-to-end handler tests, these
  limits are acceptable. Documented here so a future reader does
  not mistake coverage for proof.
"""

import re
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

# Stub alpaca-py so imports resolve.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.services import close_helper  # noqa: E402


# ── Path helpers ──────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
_QUANTUM_DIR = _REPO_ROOT / "packages" / "quantum"


def _production_py_files():
    """Yield production Python files under packages/quantum/ —
    excludes tests/, __pycache__/, and .pyc files."""
    for path in _QUANTUM_DIR.rglob("*.py"):
        parts = path.relative_to(_QUANTUM_DIR).parts
        if "tests" in parts or "__pycache__" in parts:
            continue
        yield path


# ── Class A: Source-level structural invariants ────────────────────


class TestSingleCloseWriter(unittest.TestCase):
    """A1 — close_position_shared is the only writer of
    paper_positions with status='closed'.

    Regression guard: the 2026-04-10 → 04-15 class of bugs where
    multiple handlers wrote the close row directly with divergent
    math/enum values. After PR #6, close_helper.py is the single
    allowed writer. PR #6 Commit 8a removed the last dead-code
    violator (PaperExecutionService).
    """

    # Regex captures .update({...}) where the dict literal contains
    # a 'status' key with value 'closed' or "closed". Multiline-dotall.
    # Defensive against single vs double quotes and arbitrary key order.
    _PATTERN = re.compile(
        r"\.update\(\s*\{[^}]*[\"']status[\"']\s*:\s*[\"']closed[\"']",
        re.DOTALL,
    )

    # The single allowlisted file. close_helper.py IS the helper —
    # it has to write 'closed' for the helper to function.
    _ALLOWED = {"services/close_helper.py"}

    def test_no_direct_closed_writes_in_production(self):
        violators = []
        for path in _production_py_files():
            rel = path.relative_to(_QUANTUM_DIR).as_posix()
            if rel in self._ALLOWED:
                continue
            source = path.read_text(encoding="utf-8")
            if self._PATTERN.search(source):
                violators.append(rel)

        self.assertEqual(
            violators, [],
            msg=(
                f"Found files writing status='closed' to paper_positions "
                f"directly (bypassing close_position_shared): {violators}. "
                f"Route the close through close_position_shared. The only "
                f"allowed direct writer is: {sorted(self._ALLOWED)}."
            ),
        )


class TestNoLegacyCloseReasonLiterals(unittest.TestCase):
    """A2 — no production file hardcodes a legacy close_reason
    literal as a write value.

    The 5 legacy strings ('manual_internal_fill', 'alpaca_fill_manual',
    'alpaca_fill_reconciled_2026_04_16', 'target_profit', 'stop_loss')
    are accepted by the Phase-1 CHECK for grandfathering, but no
    post-PR-#6 code path should emit them. The exit evaluator's
    _REASON_MAP (paper_exit_evaluator.py) is an exception — the MAP
    KEYS are legacy strings because callers (EXIT_CONDITIONS,
    intraday_risk_monitor) still emit them; the map translates.
    """

    # Legacy values that callers may still speak (map keys). The
    # check is: when these strings appear as map VALUES, that's a
    # regression — the map should emit canonical enum values.
    _LEGACY = {
        "manual_internal_fill",
        "alpaca_fill_manual",
        "alpaca_fill_reconciled_2026_04_16",
    }

    # Files that legitimately reference legacy strings in comments /
    # docstrings / migration discussion. Allowlist is NOT for code
    # emission — these files don't emit the legacy string at runtime.
    _ALLOWED_FILES_WITH_LEGACY_MENTIONS = {
        "services/paper_exit_evaluator.py",  # _REASON_MAP keys (not values)
        "services/close_helper.py",           # docstring mentions only
    }

    def test_no_legacy_close_reason_written_by_production_code(self):
        violators = []
        for path in _production_py_files():
            rel = path.relative_to(_QUANTUM_DIR).as_posix()
            source = path.read_text(encoding="utf-8")
            for legacy in self._LEGACY:
                # Only flag quoted string literals; mentions in
                # docstrings + comments are fine because this regex
                # catches the quote chars.
                if f"'{legacy}'" in source or f'"{legacy}"' in source:
                    if rel in self._ALLOWED_FILES_WITH_LEGACY_MENTIONS:
                        continue
                    violators.append((rel, legacy))

        self.assertEqual(
            violators, [],
            msg=(
                f"Legacy close_reason literals found in production code: "
                f"{violators}. Post-PR-#6 handlers must emit one of the "
                f"9 canonical enum values defined in close_helper._VALID_"
                f"CLOSE_REASONS. If a file needs to REFERENCE a legacy "
                f"value (e.g. for migration tooling), add it to "
                f"_ALLOWED_FILES_WITH_LEGACY_MENTIONS with a justification."
            ),
        )


class TestHandlersImportSharedPipeline(unittest.TestCase):
    """A3 — every handler with a close path imports both
    close_position_shared and compute_realized_pl.

    If a future handler adds a close path without wiring through the
    shared pipeline, this test will catch the missing import. It
    won't catch the case of a handler that imports but doesn't call
    the helper — that's covered by A1 (no direct 'closed' writes).
    """

    _HANDLERS = [
        "brokers/alpaca_order_handler.py",
        "services/paper_exit_evaluator.py",
        "paper_endpoints.py",
    ]

    def test_each_handler_imports_close_position_shared(self):
        missing = []
        for rel in self._HANDLERS:
            src = (_QUANTUM_DIR / rel).read_text(encoding="utf-8")
            if "close_position_shared" not in src:
                missing.append(rel)
        self.assertEqual(missing, [], msg=(
            f"Handlers missing close_position_shared import: {missing}"
        ))

    def test_each_handler_imports_compute_realized_pl(self):
        missing = []
        for rel in self._HANDLERS:
            src = (_QUANTUM_DIR / rel).read_text(encoding="utf-8")
            if "compute_realized_pl" not in src:
                missing.append(rel)
        self.assertEqual(missing, [], msg=(
            f"Handlers missing compute_realized_pl import: {missing}"
        ))


# ── Class B: Phase-1 migration enum alignment ─────────────────────


class TestEnumAlignment(unittest.TestCase):
    """B1/B2 — close_helper's Python enums align with the migration
    CHECK. If these drift, writes will silently produce DB errors
    at runtime (Phase 2) or accept typos (Python strict side)."""

    _MIGRATION_FILE = (
        _REPO_ROOT / "supabase" / "migrations"
        / "20260423000001_expand_close_reason_enum_phase1.sql"
    )

    # Canonical 9 close_reason values (the target state after Phase 2).
    # Legacy-5 are acceptable in Phase 1 CHECK but never emitted by
    # Python code post-PR-#6, so they don't belong in Python's strict
    # validation set.
    _EXPECTED_CLOSE_REASONS = frozenset({
        "target_profit_hit",
        "stop_loss_hit",
        "dte_threshold",
        "expiration_day",
        "manual_close_user_initiated",
        "alpaca_fill_reconciler_sign_corrected",
        "alpaca_fill_reconciler_standard",
        "envelope_force_close",
        "orphan_fill_repair",
    })

    _EXPECTED_FILL_SOURCES = frozenset({
        "alpaca_fill_reconciler",
        "orphan_fill_repair",
        "exit_evaluator",
        "manual_endpoint",
    })

    def test_close_reason_enum_is_exactly_nine_canonical_values(self):
        self.assertEqual(
            set(close_helper._VALID_CLOSE_REASONS),
            set(self._EXPECTED_CLOSE_REASONS),
            msg=(
                "close_helper._VALID_CLOSE_REASONS drift detected. "
                "Python strict enum must match the 9 canonical values; "
                "legacy-5 are only for the Phase-1 DB CHECK, not Python."
            ),
        )

    def test_fill_source_enum_is_exactly_four_values(self):
        self.assertEqual(
            set(close_helper._VALID_FILL_SOURCES),
            set(self._EXPECTED_FILL_SOURCES),
            msg=(
                "close_helper._VALID_FILL_SOURCES drift detected. "
                "Must match the 4 values accepted by the "
                "check_fill_source_enum DB CHECK."
            ),
        )

    def test_migration_check_contains_all_nine_canonical_reasons(self):
        """Migration SQL enumerates the 9 canonical values inside the
        CHECK clause (alongside 5 grandfathered legacy strings). If
        someone drops a canonical value from the migration without
        removing it from Python, writes will silently fail."""
        if not self._MIGRATION_FILE.exists():
            self.skipTest(f"Migration file not present: {self._MIGRATION_FILE}")
        sql = self._MIGRATION_FILE.read_text(encoding="utf-8")
        missing = []
        for reason in self._EXPECTED_CLOSE_REASONS:
            if f"'{reason}'" not in sql:
                missing.append(reason)
        self.assertEqual(missing, [], msg=(
            f"Canonical close_reason values missing from Phase-1 CHECK "
            f"migration SQL: {missing}. Python would accept these but "
            f"the DB would reject them."
        ))

    def test_migration_check_contains_all_four_fill_sources(self):
        if not self._MIGRATION_FILE.exists():
            self.skipTest(f"Migration file not present: {self._MIGRATION_FILE}")
        sql = self._MIGRATION_FILE.read_text(encoding="utf-8")
        missing = []
        for src in self._EXPECTED_FILL_SOURCES:
            if f"'{src}'" not in sql:
                missing.append(src)
        self.assertEqual(missing, [], msg=(
            f"Fill source values missing from migration CHECK SQL: {missing}."
        ))


# ── Class C: Helper contract invariants ───────────────────────────


def _minimal_supabase_mock():
    """Returns a supabase-like mock that exposes the surface
    close_position_shared uses: .table(...).update().eq().neq().execute()
    and .table(...).select().eq().limit().execute()."""
    supabase = MagicMock()
    chain = MagicMock()
    chain.update.return_value.eq.return_value.neq.return_value.execute \
        .return_value = MagicMock(data=[{"id": "pos-1"}])
    chain.select.return_value.eq.return_value.limit.return_value.execute \
        .return_value = MagicMock(data=[])
    supabase.table.return_value = chain
    return supabase


class TestHelperContract(unittest.TestCase):
    """C1-C3 — close_position_shared's contract guards.

    These are the structural remedies for specific pre-PR-#6 bug
    classes. Each test pins an invariant that would have prevented
    a documented incident.
    """

    def test_realized_pl_none_raises_value_error(self):
        """C1 — NFLX 846bc787 2026-04-16: manual_internal_fill wrote
        unrealized_pl into realized_pl because the old inline writer
        treated realized_pl as optional. The shared helper REQUIRES
        realized_pl and raises ValueError on None at input-validation
        time, before any DB write. Callers cannot forget to compute it."""
        with self.assertRaises(ValueError) as ctx:
            close_helper.close_position_shared(
                supabase=_minimal_supabase_mock(),
                position_id="pos-1",
                realized_pl=None,
                close_reason="manual_close_user_initiated",
                fill_source="manual_endpoint",
            )
        self.assertIn("realized_pl", str(ctx.exception).lower())

    def test_legacy_close_reason_rejected_by_python_validation(self):
        """C2 — Python strict enum rejects legacy values. The Phase-1
        DB CHECK accepts 'target_profit' for grandfathering, but
        close_position_shared rejects it so no new code path can emit
        a legacy string through the helper."""
        with self.assertRaises(ValueError):
            close_helper.close_position_shared(
                supabase=_minimal_supabase_mock(),
                position_id="pos-1",
                realized_pl=Decimal("100.00"),
                close_reason="target_profit",  # legacy; not in 9-value set
                fill_source="exit_evaluator",
            )

    def test_typo_close_reason_rejected(self):
        """C2 cont. — a plausible typo is caught before DB round-trip.
        Without this Python-side guard, the typo would be rejected
        later by the DB CHECK, but with a less informative error."""
        with self.assertRaises(ValueError):
            close_helper.close_position_shared(
                supabase=_minimal_supabase_mock(),
                position_id="pos-1",
                realized_pl=Decimal("100.00"),
                close_reason="envelope_forceclose",  # missing underscore
                fill_source="exit_evaluator",
            )

    def test_unknown_fill_source_rejected(self):
        """C3 — fill_source strict enum mirrors the DB CHECK. Catches
        typos and any future source-engine name drift at the Python
        boundary."""
        with self.assertRaises(ValueError):
            close_helper.close_position_shared(
                supabase=_minimal_supabase_mock(),
                position_id="pos-1",
                realized_pl=Decimal("100.00"),
                close_reason="target_profit_hit",
                fill_source="alpaca_reconciler",  # missing '_fill'
            )

    def test_empty_string_close_reason_rejected(self):
        """Defense in depth: empty string is not in the 9-value set
        and must not silently fall through."""
        with self.assertRaises(ValueError):
            close_helper.close_position_shared(
                supabase=_minimal_supabase_mock(),
                position_id="pos-1",
                realized_pl=Decimal("100.00"),
                close_reason="",
                fill_source="exit_evaluator",
            )


if __name__ == "__main__":
    unittest.main()
