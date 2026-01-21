"""
Tests for v5 fold boundary fix - no overlap between train and test windows.

Tests:
1. test_start > train_end for all folds (embargo_days=0)
2. test_start == train_end + 1 + embargo_days when embargo_days > 0
"""

import unittest
import sys
import os
from datetime import datetime

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFoldNoOverlap(unittest.TestCase):
    """Tests that fold windows never overlap (data leakage prevention)."""

    def test_no_overlap_embargo_zero(self):
        """test_start > train_end when embargo_days=0."""
        from services.walkforward_runner import generate_folds

        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=30,
            test_days=15,
            step_days=15,
            warmup_days=0,
            embargo_days=0  # No explicit embargo
        )

        self.assertGreater(len(folds), 0, "Should generate at least one fold")

        for i, fold in enumerate(folds):
            train_end = datetime.strptime(fold["train_end"], "%Y-%m-%d")
            test_start = datetime.strptime(fold["test_start"], "%Y-%m-%d")

            # test_start must be strictly after train_end (no overlap)
            self.assertGreater(
                test_start,
                train_end,
                f"Fold {i}: test_start ({fold['test_start']}) must be > train_end ({fold['train_end']})"
            )

            # Exactly 1 day gap when embargo=0
            gap_days = (test_start - train_end).days
            self.assertEqual(
                gap_days,
                1,
                f"Fold {i}: Expected 1-day gap, got {gap_days} days"
            )

    def test_no_overlap_with_embargo(self):
        """test_start == train_end + 1 + embargo_days."""
        from services.walkforward_runner import generate_folds

        embargo_days = 2

        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=30,
            test_days=15,
            step_days=15,
            warmup_days=0,
            embargo_days=embargo_days
        )

        self.assertGreater(len(folds), 0, "Should generate at least one fold")

        for i, fold in enumerate(folds):
            train_end = datetime.strptime(fold["train_end"], "%Y-%m-%d")
            test_start = datetime.strptime(fold["test_start"], "%Y-%m-%d")

            # test_start must be train_end + 1 + embargo_days
            expected_gap = 1 + embargo_days
            actual_gap = (test_start - train_end).days

            self.assertEqual(
                actual_gap,
                expected_gap,
                f"Fold {i}: Expected {expected_gap}-day gap (1 + {embargo_days}), got {actual_gap} days"
            )

    def test_multiple_folds_all_non_overlapping(self):
        """All folds in a multi-fold run have non-overlapping train/test."""
        from services.walkforward_runner import generate_folds

        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-12-31",
            train_days=60,
            test_days=30,
            step_days=30,
            warmup_days=10,
            embargo_days=0
        )

        self.assertGreater(len(folds), 2, "Should generate multiple folds")

        for i, fold in enumerate(folds):
            train_end = datetime.strptime(fold["train_end"], "%Y-%m-%d")
            test_start = datetime.strptime(fold["test_start"], "%Y-%m-%d")
            test_end = datetime.strptime(fold["test_end"], "%Y-%m-%d")

            # No overlap
            self.assertGreater(test_start, train_end)

            # Test window is valid
            self.assertGreater(test_end, test_start)

    def test_warmup_does_not_affect_test_gap(self):
        """train_start_engine warmup expansion doesn't affect train_end/test_start gap."""
        from services.walkforward_runner import generate_folds

        folds_no_warmup = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=30,
            test_days=15,
            step_days=15,
            warmup_days=0,
            embargo_days=0
        )

        folds_with_warmup = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=30,
            test_days=15,
            step_days=15,
            warmup_days=10,  # With warmup
            embargo_days=0
        )

        # Both should have same number of folds
        self.assertEqual(len(folds_no_warmup), len(folds_with_warmup))

        for i in range(len(folds_no_warmup)):
            # train_end and test_start should be identical
            self.assertEqual(
                folds_no_warmup[i]["train_end"],
                folds_with_warmup[i]["train_end"]
            )
            self.assertEqual(
                folds_no_warmup[i]["test_start"],
                folds_with_warmup[i]["test_start"]
            )


if __name__ == "__main__":
    unittest.main()
