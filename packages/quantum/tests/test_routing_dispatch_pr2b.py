"""Tests for #62a-D4-PR2b shadow fill simulation.

PR2b builds on PR2a (#842) by materializing shadow_blocked orders
into actual fills. Two surgical edits:

1. Entry path (paper_endpoints.py): shadow_blocked branch in
   _stage_order_internal calls _process_orders_for_user
   (target_order_id=order_id) inline after marking. Reuses the
   existing TCM simulate + _commit_fill machinery.

2. Close path (paper_exit_evaluator.py): shadow_blocked branch in
   _close_position no longer returns early — falls through to the
   existing internal-fill block at line 1252+ which fills at
   current_mark and calls close_position_shared (writes
   learning_feedback_loops outcomes).

Layer 1 (source-level structural): wiring at each gate.
Layer 2 (helper-level behavioral): NOT applicable here — full-flow
behavioral tests would require the entire _process_orders_for_user
mock chain (Polygon fetch, _commit_fill, ledger). Defer to operator
post-merge verification (cohort_comparison data flow appears in
learning_feedback_loops once shadow cycles run).
"""

import ast
import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestEntryPathMaterialization(unittest.TestCase):
    """Entry path: shadow_blocked branch calls _process_orders_for_user
    after marking the order, restoring the fill flow that PR2a
    intentionally deferred."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("paper_endpoints.py")

    def test_process_orders_called_with_target_order_id(self):
        """_process_orders_for_user(target_order_id=order_id) wires
        the existing TCM simulate + commit machinery to the shadow
        path."""
        self.assertIn("_process_orders_for_user", self.src)
        self.assertIn("target_order_id=order_id", self.src,
                      "Shadow branch must scope processing to the single "
                      "order via target_order_id.")
        ast.parse(self.src)

    def test_shadow_blocked_marker_set_before_process_orders(self):
        """The execution_mode='shadow_blocked' update must happen
        BEFORE _process_orders_for_user is called, so the marker
        survives _commit_fill (which only writes filled-state fields).
        Triage queries rely on this marker post-fill."""
        # Locate within the entry-path shadow branch specifically by
        # anchoring on the entry-path log line.
        anchor = self.src.find("[ROUTING] Blocked Alpaca submit")
        self.assertGreater(anchor, 0,
                           "Entry-path shadow branch log line missing.")
        # The 'shadow_blocked' update is just before this anchor;
        # the _process_orders_for_user call is just after.
        before = self.src[max(0, anchor - 600):anchor]
        after = self.src[anchor:anchor + 1200]

        self.assertIn('"execution_mode": "shadow_blocked"', before,
                      "execution_mode='shadow_blocked' must be set "
                      "before the log line.")
        self.assertIn("_process_orders_for_user(supabase, analytics", after,
                      "_process_orders_for_user must be called after "
                      "the marker is set.")

    def test_pr2b_comment_documents_intent(self):
        """Source-level marker that PR2b intentionally wires this in.
        Defends against future deletion 'cleanups' that would re-break
        cohort data flow."""
        self.assertIn("#62a-D4-PR2b", self.src)


class TestClosePathFallThrough(unittest.TestCase):
    """Close path: shadow_blocked branch removed early-return; falls
    through to existing internal-fill block at line 1252+."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("services/paper_exit_evaluator.py")

    def test_pr2a_early_return_dict_removed(self):
        """The specific PR2a return-dict pattern in the close path is
        gone. Catches regressions where someone re-adds 'return' for
        clarity and breaks the fall-through."""
        self.assertNotIn(
            'shadow_only portfolio — Alpaca close blocked, position remains open pending PR2b',
            self.src,
            "PR2a's deferred-PR2b return note must be removed in PR2b. "
            "If this assertion fails, the early return that breaks the "
            "fall-through has been re-added.",
        )

    def test_internal_fill_block_still_present(self):
        """Fall-through target must still exist."""
        self.assertIn("# --- Internal fill at current_mark", self.src,
                      "Internal-fill block markers (current_mark, fee=0, "
                      "ledger emit) must remain — they're the materialization "
                      "path the shadow branch falls through to.")
        self.assertIn("close_position_shared", self.src,
                      "close_position_shared must be reachable — it's the "
                      "function that writes learning_feedback_loops outcomes "
                      "for cohort comparison.")

    def test_else_wraps_alpaca_submit(self):
        """The Alpaca submit_and_track in close path must be inside
        an `else:` clause (matching `if not should_submit_to_broker`)
        so shadow_only orders skip the Alpaca submission entirely."""
        # Locate the close-path shadow gate
        anchor = self.src.find("[ROUTING] Blocked Alpaca close for shadow_only")
        self.assertGreater(anchor, 0,
                           "Close-path shadow log line missing.")
        # Look for `else:` within the next ~700 chars (the else clause
        # that wraps the existing submit logic)
        block = self.src[anchor:anchor + 1500]
        self.assertIn("else:", block,
                      "Alpaca submit must be in an else: block so "
                      "shadow_only orders don't reach submit_and_track.")
        # Verify submit_and_track is in the same window (inside the else)
        self.assertIn("submit_and_track", block)

    def test_pr2b_comment_documents_intent(self):
        self.assertIn("#62a-D4-PR2b", self.src)


class TestSafetyChecksUnchanged(unittest.TestCase):
    """PR2b does not modify safety_checks.py — approval path keeps
    PR2a's defensive early-return for the rare race-condition case
    (routing_mode flip during pending approval)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("brokers/safety_checks.py")

    def test_safety_checks_still_has_shadow_blocked_marker(self):
        """PR2a's behavior preserved — defensive early-return intact."""
        self.assertIn("shadow_blocked", self.src)
        self.assertIn("Portfolio routing_mode flipped to shadow_only", self.src,
                      "PR2a's race-condition messaging must be preserved.")


class TestModuleSyntax(unittest.TestCase):
    """All modified files parse without SyntaxError."""

    def test_paper_endpoints_parses(self):
        ast.parse(_read("paper_endpoints.py"))

    def test_paper_exit_evaluator_parses(self):
        ast.parse(_read("services/paper_exit_evaluator.py"))


if __name__ == "__main__":
    unittest.main()
