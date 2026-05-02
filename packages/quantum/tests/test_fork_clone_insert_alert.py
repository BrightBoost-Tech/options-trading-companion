"""Tests for #97 Phase 1 — alert at cohort clone INSERT swallow site.

Source-level structural assertions only. Per Loud-Error Doctrine v1.0
anti-pattern 4 (per-iteration swallow in tight loops). Convention
matches PR #838 (H5a paper_exit_evaluator) and PR #839 (H5b
paper_autopilot_service) structural-test pattern.

Behavioral wiring is verified at runtime by the next production
fire — the next `suggestions_open` cycle that produces a candidate
passing all 3 cohort filters should emit one
`cohort_clone_insert_failed` alert per non-aggressive cohort.
"""

import re
import unittest
from pathlib import Path


FORK_PATH = (
    Path(__file__).parent.parent / "policy_lab" / "fork.py"
)


def _read_fork() -> str:
    return FORK_PATH.read_text(encoding="utf-8")


class TestCohortCloneInsertAlertWired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read_fork()

    def test_cohort_clone_insert_failure_writes_alert(self):
        """Required strings present at the swallow site."""
        self.assertIn("cohort_clone_insert_failed", self.src)
        self.assertIn("operator_action_required", self.src)
        self.assertIn("alert(", self.src)

    def test_cohort_clone_alert_severity_is_critical(self):
        """Severity is critical at the new alert call site.

        The alert(...) call spans multiple lines with nested parens
        (the metadata dict contains its own parens), so a balanced
        regex isn't viable. Use a window around the alert_type
        literal: severity declaration must appear within ~500 chars.
        """
        anchor = self.src.find('"cohort_clone_insert_failed"')
        self.assertGreater(
            anchor, 0,
            "alert_type literal cohort_clone_insert_failed not found",
        )
        # Severity sits 1-2 lines below alert_type per call-site convention.
        window = self.src[anchor:anchor + 500]
        self.assertIn('severity="critical"', window)


if __name__ == "__main__":
    unittest.main()
