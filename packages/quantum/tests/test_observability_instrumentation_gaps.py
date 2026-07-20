"""Regression tests for the 2026-05-18 diagnostic instrumentation gaps.

Tests three fixes shipped together:

FIX 1: run_midday_cycle's success-path return now includes structured
  funnel counts + cycle_metadata (universe_size, scanner_emitted,
  trade_suggestions_created, h7_passed, edge_above_minimum, executable,
  staged, plus regime/tier/open_position_count/available_envelope).
  Pre-fix only `candidates` and `created` were present.

FIX 2: RejectionStats now surfaces a `persist_failures` counter via
  to_dict() so cycle_metadata can show H9-style verification of
  observability writes. Pre-fix, suggestion_rejections insert failures
  were only logger.warning'd; no programmatic counter.

FIX 3: a fresh internal close gets `submitted_at` populated alongside
  `filled_at` so target_profit_hit close orders have non-NULL submitted_at
  for exit-side latency analysis. Since V17-1 A2 (2026-07-19) the internal
  economic commit is the atomic `rpc_commit_internal_close_v1`, so this write
  lives in that RPC's `UPDATE paper_orders SET submitted_at =
  COALESCE(submitted_at, v_now), filled_at = v_now`. The migration is the
  source of truth; the FIX-3 tests below assert that CONTRACT (the prior
  source-grep tests pinned the REMOVED Python block — the #1126 costume class,
  doctrine §9). Live-Postgres proof that the RPC actually populates the columns
  is in packages/quantum/tests/pg/test_rpc_commit_internal_close_pg.py.

Diagnostic reference: 2026-05-18 conversation history Part 5.
"""
from __future__ import annotations

import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from packages.quantum.options_scanner import RejectionStats


# ── FIX 2: RejectionStats persist_failures + to_dict surface ─────────


class _FakeFailingSupabase:
    """Stub Supabase client whose .insert().execute() raises.
    Mirrors the existing test_rejection_stats_persistence.py pattern
    but inverts the success path to drive the failure branch."""

    def table(self, name):
        return self

    def insert(self, payload):
        return self

    def execute(self):
        raise RuntimeError("simulated insert failure")


class _FakeSuccessSupabase:
    def __init__(self):
        self.inserts = []

    def table(self, name):
        self._name = name
        return self

    def insert(self, payload):
        self.inserts.append(payload)
        return self

    def execute(self):
        return MagicMock(data=None)


class TestFix2RejectionStatsPersistFailures(unittest.TestCase):

    def test_persist_failures_starts_at_zero(self):
        rs = RejectionStats()
        self.assertEqual(rs.to_dict()["persist_failures"], 0)

    def test_persist_failure_increments_counter(self):
        rs = RejectionStats(
            supabase=_FakeFailingSupabase(),
            cycle_date=date(2026, 5, 18),
        )
        rs.set_symbol("TEST")
        rs.record("test_reason")
        self.assertEqual(rs.to_dict()["persist_failures"], 1)
        rs.record("test_reason_2")
        self.assertEqual(rs.to_dict()["persist_failures"], 2)

    def test_persist_success_does_not_increment_counter(self):
        rs = RejectionStats(
            supabase=_FakeSuccessSupabase(),
            cycle_date=date(2026, 5, 18),
        )
        rs.set_symbol("TEST")
        rs.record("test_reason")
        self.assertEqual(rs.to_dict()["persist_failures"], 0)

    def test_to_dict_includes_counts_alias(self):
        """FIX 1 cycle_metadata reads from to_dict()['counts']; ensure
        the alias exists alongside the legacy rejection_counts key."""
        rs = RejectionStats()
        rs.record("test_reason")
        d = rs.to_dict()
        self.assertIn("counts", d)
        self.assertIn("rejection_counts", d)
        self.assertEqual(d["counts"], d["rejection_counts"])

    def test_persist_failures_isolated_per_instance(self):
        rs1 = RejectionStats(
            supabase=_FakeFailingSupabase(), cycle_date=date(2026, 5, 18),
        )
        rs2 = RejectionStats(
            supabase=_FakeFailingSupabase(), cycle_date=date(2026, 5, 18),
        )
        rs1.set_symbol("A")
        rs1.record("reason_a")
        # rs2 should still be 0 — instance-level counter
        self.assertEqual(rs2.to_dict()["persist_failures"], 0)
        self.assertEqual(rs1.to_dict()["persist_failures"], 1)


# ── FIX 1: source-level assertions on cycle return shape ─────────────


WORKFLOW_ORCHESTRATOR_PATH = (
    Path(__file__).parent.parent / "services" / "workflow_orchestrator.py"
)


class TestFix1RunMiddayCycleReturnShape(unittest.TestCase):
    """Source-level assertions on the run_midday_cycle happy-path
    return dict. Source-level rather than runtime-mocked because the
    happy-path requires a fully-mocked scanner + budget engine that
    would re-implement most of the orchestrator. The mocked test for
    runtime behavior lives in suggestions_open / orchestrator
    integration tests; here we just defend the return-shape contract.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = WORKFLOW_ORCHESTRATOR_PATH.read_text(encoding="utf-8")

    def test_happy_path_counts_include_spec_keys(self):
        """Spec-required count keys must appear in the happy-path
        return dict. See diagnostic Part 5 for the original gap."""
        required_keys = [
            "universe_size",
            "scanner_emitted",
            "trade_suggestions_created",
            "h7_passed",
            "edge_above_minimum",
            "executable",
            "staged",
        ]
        for k in required_keys:
            # Look for "key": somewhere in the file — the happy-path
            # return at line ~3456 is the canonical write point.
            self.assertIn(
                f'"{k}":',
                self.src,
                f"Required FIX 1 cycle-result count key {k!r} not "
                "found in workflow_orchestrator.py. Diagnostic Part 5 "
                "(2026-05-18) listed this as the highest-blocking "
                "instrumentation gap.",
            )

    def test_happy_path_cycle_metadata_keys_present(self):
        required_meta_keys = [
            "regime",
            "tier",
            "open_position_count",
            "available_envelope_dollars",
        ]
        for k in required_meta_keys:
            self.assertIn(
                f'"{k}":',
                self.src,
                f"Required FIX 1 cycle_metadata key {k!r} not found.",
            )

    def test_rejection_persist_failures_surface_present(self):
        """FIX 2 surface: H9 verification metric for rejection
        persistence flowed through cycle_result."""
        self.assertIn(
            '"rejection_persist_failures":',
            self.src,
            "rejection_persist_failures should be surfaced in "
            "cycle counts (FIX 2 H9 verification).",
        )


# ── FIX 3: submitted_at populated alongside filled_at in the atomic close ────
# The 2026-05-18 write lived in a paper_orders.update() dict inside
# paper_exit_evaluator._close_position. V17-1 A2 (2026-07-19, Lane 1B) moved the
# internal economic commit into the atomic rpc_commit_internal_close_v1; the
# timing write is now `submitted_at = COALESCE(submitted_at, v_now)` /
# `filled_at = v_now` in that RPC's UPDATE paper_orders. The migration file IS
# the deployed RPC the route calls, so these assert the CONTRACT there — NOT a
# removed Python block (the prior source-grep tests were the #1126 costume:
# they pinned code the switch correctly deleted, and would have stayed green on
# any stray matching string while the live route walked past). Live-Postgres
# proof that the RPC actually populates the columns:
# packages/quantum/tests/pg/test_rpc_commit_internal_close_pg.py.

RPC_COMMIT_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260719180000_rpc_commit_internal_close_v1.sql"
)


def _coalesce_submitted_at(existing_submitted_at, v_now):
    """Faithful Python mirror of the RPC's
    `submitted_at = COALESCE(submitted_at, v_now)`. Used only AFTER the test
    anchors that this IS the expression the migration uses, so the mirror can
    never drift into a tautology."""
    return existing_submitted_at if existing_submitted_at is not None else v_now


class TestFix3CloseOrderSubmittedAtInAtomicCommit(unittest.TestCase):
    """FIX 3 invariant, relocated to the atomic RPC: a fresh internal-close
    order (submitted_at NULL at stage) must end up with BOTH submitted_at AND
    filled_at populated. Pre-fix, 11 of 11 target_profit_hit closes in 60d had
    NULL submitted_at — breaking exit-side latency analysis (diagnostic
    2026-05-18). Asserts the contract on the actual RPC migration; fails if the
    UPDATE ever stops writing submitted_at."""

    @classmethod
    def setUpClass(cls):
        raw = RPC_COMMIT_MIGRATION_PATH.read_text(encoding="utf-8")
        # comment-stripped SQL so a `--` prose line can never satisfy the
        # contract (the header comments mention submitted_at in passing).
        cls.code = "\n".join(
            (ln if ln.find("--") == -1 else ln[: ln.find("--")])
            for ln in raw.splitlines()
        )
        m = re.search(
            r"UPDATE\s+paper_orders\s+SET(.*?)WHERE\s+id\s*=\s*p_close_order_id",
            cls.code, re.S,
        )
        assert m is not None, (
            "rpc_commit_internal_close_v1 must have exactly one "
            "`UPDATE paper_orders SET ... WHERE id = p_close_order_id` block"
        )
        cls.update_block = m.group(1)

    def test_migration_file_present(self):
        self.assertTrue(
            RPC_COMMIT_MIGRATION_PATH.is_file(), RPC_COMMIT_MIGRATION_PATH
        )

    def test_atomic_rpc_update_sets_both_submitted_at_and_filled_at(self):
        """The order-fill UPDATE inside the RPC assigns BOTH timing columns.
        Fails if a future edit drops submitted_at (the exact 2026-05-18 gap)."""
        self.assertRegex(
            self.update_block,
            r"\bsubmitted_at\s*=\s*COALESCE\(\s*submitted_at\s*,\s*v_now\s*\)",
            "rpc_commit_internal_close_v1's UPDATE paper_orders must set "
            "submitted_at = COALESCE(submitted_at, v_now) — FIX 3 (2026-05-18): "
            "a close order with NULL submitted_at breaks exit-side latency "
            "analysis. See tests/pg/test_rpc_commit_internal_close_pg.py for the "
            "live-DB proof.",
        )
        self.assertRegex(
            self.update_block,
            r"\bfilled_at\s*=\s*v_now\b",
            "the RPC's UPDATE paper_orders must set filled_at = v_now.",
        )

    def test_submitted_at_equals_filled_at_honesty_for_fresh_close(self):
        """The submission and fill happen in the SAME atomic commit, so for a
        fresh internal close (submitted_at NULL at stage) submitted_at ==
        filled_at is the honest value — and a pre-existing submitted_at is
        PRESERVED. Anchored to the migration's actual COALESCE expression so
        the Python mirror can't drift from the SQL."""
        rhs = re.search(
            r"\bsubmitted_at\s*=\s*(COALESCE\([^)]*\))", self.update_block
        )
        self.assertIsNotNone(rhs, "submitted_at must be assigned a COALESCE(...)")
        self.assertEqual(
            re.sub(r"\s+", "", rhs.group(1)), "COALESCE(submitted_at,v_now)"
        )

        v_now = "2026-07-19T15:00:00+00:00"
        filled_at = v_now  # the RPC sets filled_at = v_now
        # Fresh close: submitted_at was NULL → becomes v_now → equals filled_at,
        # and BOTH are non-NULL (the FIX-3 invariant).
        submitted_fresh = _coalesce_submitted_at(None, v_now)
        self.assertIsNotNone(submitted_fresh)
        self.assertIsNotNone(filled_at)
        self.assertEqual(submitted_fresh, filled_at)
        # Pre-existing submitted_at is PRESERVED (COALESCE keeps the non-null
        # value); filled_at still advances to the commit time — both non-NULL,
        # and distinct.
        prior = "2026-07-19T10:00:00+00:00"
        submitted_kept = _coalesce_submitted_at(prior, v_now)
        self.assertEqual(submitted_kept, prior)
        self.assertNotEqual(submitted_kept, filled_at)


if __name__ == "__main__":
    unittest.main()
