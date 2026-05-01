"""Tests for #95 — fork.py threshold semantic mismatch fix.

Verifies score is read from sizing_metadata (option a) and that the
persistence path at workflow_orchestrator.py inserts it correctly.

Background: pre-#95, _filter_for_cohort read `risk_adjusted_ev`
(a 0-2 dollar-EV-per-dollar-risk ratio) and compared it against
`config.min_score_threshold` (designed for 0-100 score scale).
Result: every non-aggressive cohort filtered to zero clones across
all DB history. Verified by SELECT cohort_name, COUNT(*) FROM
trade_suggestions WHERE cohort_name IN ('conservative', 'neutral')
returning [].
"""

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


class TestSourceLevelFilterReadsSizingMetadataScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fork_src = (REPO_ROOT / "policy_lab" / "fork.py").read_text(
            encoding="utf-8",
        )
        cls.orch_src = (
            REPO_ROOT / "services" / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_filter_reads_sizing_metadata_score(self):
        """fork.py:_filter_for_cohort must read from sizing_metadata.score."""
        self.assertTrue(
            'sizing_metadata.get("score")' in self.fork_src
            or "sizing_metadata.get('score')" in self.fork_src,
            "fork.py must read score from sizing_metadata",
        )
        ast.parse(self.fork_src)

    def test_old_buggy_pattern_removed(self):
        """The old `s.get('risk_adjusted_ev')` comparison must not remain
        in non-comment code at the filter site."""
        non_comment_lines = [
            line for line in self.fork_src.split("\n")
            if 's.get("risk_adjusted_ev")' in line
            and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            non_comment_lines, [],
            f"Old buggy pattern remains in non-comment code: "
            f"{non_comment_lines}",
        )

    def test_filter_compares_against_min_score_threshold(self):
        """Threshold variable name preserved (compares score against
        min_score_threshold in 0-100 scale)."""
        self.assertIn("min_score_threshold", self.fork_src)

    def test_orchestrator_persists_score_in_sizing(self):
        """workflow_orchestrator.py midday cycle must augment sizing
        with score before inserting trade_suggestion."""
        self.assertIn(
            'sizing["score"]', self.orch_src,
            "workflow_orchestrator must persist score into sizing",
        )
        # Sanity: the augmentation block uses cand.get("score")
        self.assertIn(
            'cand.get("score")', self.orch_src,
        )
        ast.parse(self.orch_src)


class TestBehavioralFilter(unittest.TestCase):
    """Behavioral tests for _filter_for_cohort with the new contract."""

    def _make_config(self, min_score=70, max_pos=3, max_per_day=3):
        class MockConfig:
            min_score_threshold = min_score
            max_positions_open = max_pos
            max_suggestions_per_day = max_per_day

        return MockConfig()

    def test_score_above_threshold_passes(self):
        """Candidate with score=85 passes neutral threshold (50)."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [{
            "id": "test_1",
            "ticker": "BAC",
            "sizing_metadata": {"score": 85, "capital_required": 292},
            "risk_adjusted_ev": 0.13,  # would have failed old filter
        }]
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=50),
            open_positions=0,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "test_1")

    def test_score_at_exact_threshold_passes(self):
        """Candidate with score=70 passes conservative threshold (70)
        — not strictly less-than, so equal passes."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [{
            "id": "test_eq",
            "ticker": "PFE",
            "sizing_metadata": {"score": 70},
        }]
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=70),
            open_positions=0,
        )
        self.assertEqual(len(result), 1)

    def test_score_below_threshold_filtered_out(self):
        """Candidate with score=25 fails conservative threshold (70)."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [{
            "id": "test_2",
            "ticker": "F",
            "sizing_metadata": {"score": 25, "capital_required": 100},
            "risk_adjusted_ev": 0.5,
        }]
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=70),
            open_positions=0,
        )
        self.assertEqual(len(result), 0)

    def test_missing_score_filtered_out_for_safety(self):
        """No score field → filtered (safe default — no score means no
        cohort qualification, prevents accidental promotion via NULL)."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [{
            "id": "test_3",
            "ticker": "WBD",
            "sizing_metadata": {},  # no score key
        }]
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=70),
            open_positions=0,
        )
        self.assertEqual(len(result), 0)

    def test_missing_sizing_metadata_filtered_out(self):
        """No sizing_metadata at all → filtered (safe default)."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [{
            "id": "test_4",
            "ticker": "T",
            # No sizing_metadata key at all
        }]
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=70),
            open_positions=0,
        )
        self.assertEqual(len(result), 0)

    def test_max_positions_gate_still_applies(self):
        """max_positions_open caps results even if all scores pass."""
        from packages.quantum.policy_lab.fork import _filter_for_cohort

        suggestions = [
            {"id": f"sugg_{i}", "ticker": "X",
             "sizing_metadata": {"score": 95}}
            for i in range(5)
        ]
        # max_pos=3, open=2 → available_slots=1, max_per_day=3 → max_new=1
        result = _filter_for_cohort(
            suggestions,
            self._make_config(min_score=50, max_pos=3, max_per_day=3),
            open_positions=2,
        )
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
