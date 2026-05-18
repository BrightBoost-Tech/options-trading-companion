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

FIX 3: paper_exit_evaluator's internal-fill path now writes
  `submitted_at` alongside `filled_at` so target_profit_hit close
  orders have non-NULL submitted_at for exit-side latency analysis.

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
PAPER_EXIT_EVALUATOR_PATH = (
    Path(__file__).parent.parent / "services" / "paper_exit_evaluator.py"
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


# ── FIX 3: source-level assertion on close-order timing write ───────


class TestFix3CloseOrderSubmittedAtWrite(unittest.TestCase):
    """Source-level assertion on paper_exit_evaluator's internal-fill
    path. Pre-fix the paper_orders.update() block at ~line 1270 set
    filled_at but not submitted_at — causing 11 of 11 target_profit_hit
    closes in 60d to have NULL submitted_at (diagnostic 2026-05-18)."""

    @classmethod
    def setUpClass(cls):
        cls.src = PAPER_EXIT_EVALUATOR_PATH.read_text(encoding="utf-8")

    def test_internal_fill_update_writes_submitted_at_alongside_filled_at(self):
        """Defend against accidental revert. The internal-fill update
        dict must include BOTH submitted_at and filled_at keys for
        target_profit_hit close-path timing observability."""
        # Look for an update block that contains both keys.
        # The update is invoked on paper_orders.update({...}) — the
        # dict literal contains both timing fields.
        update_block_pattern = re.compile(
            r'paper_orders.*?update\(\s*\{[^}]*?"submitted_at"[^}]*?"filled_at"',
            re.DOTALL,
        )
        match = update_block_pattern.search(self.src)
        if match is None:
            # Try reverse order too — the spec doesn't mandate which
            # comes first in the literal.
            update_block_pattern_rev = re.compile(
                r'paper_orders.*?update\(\s*\{[^}]*?"filled_at"[^}]*?"submitted_at"',
                re.DOTALL,
            )
            match = update_block_pattern_rev.search(self.src)

        self.assertIsNotNone(
            match,
            "paper_exit_evaluator's paper_orders.update() block must "
            "include BOTH 'submitted_at' and 'filled_at' keys. FIX 3 "
            "(2026-05-18 diagnostic): pre-fix, target_profit_hit "
            "close orders had filled_at populated but submitted_at "
            "NULL — broke exit-side latency analysis. See diagnostic "
            "Part 5 + paper_exit_evaluator.py:~1270.",
        )

    def test_fix_3_inline_comment_present(self):
        """The fix has non-obvious 'why' (submitted_at == filled_at
        for internal fills is intentional). Inline comment should
        reference FIX 3 + the 2026-05-18 diagnostic so a future
        reader doesn't 'fix' the apparent duplication by removing
        submitted_at."""
        markers = [
            "FIX 3" in self.src,
            "2026-05-18" in self.src,
            "submitted_at" in self.src and "filled_at" in self.src,
        ]
        self.assertTrue(
            all(markers),
            "Inline comment near the submitted_at write should "
            "reference FIX 3 + 2026-05-18 + explain the "
            "submitted_at==filled_at honesty for internal fills.",
        )


if __name__ == "__main__":
    unittest.main()
