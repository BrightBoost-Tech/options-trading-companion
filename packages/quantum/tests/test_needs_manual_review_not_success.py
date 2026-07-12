"""PR-①b F-A8/E6-edge: a needs_manual_review close (terminal submit failure) must
NOT read as a completed force-close in the monitor's accounting — no force_close
count, no cooldown, no same-cycle suppression. The bug: _close_position discarded
submit_and_track's needs_manual_review return and reported routed_to='alpaca', so
the monitor's success check (now _close_completed) counted a known-failed submit.
"""
import unittest

from packages.quantum.jobs.handlers.intraday_risk_monitor import _close_completed


class TestCloseCompleted(unittest.TestCase):
    def test_needs_manual_review_is_not_completed(self):
        # THE FIX: a terminal submit failure is not a routed success
        self.assertFalse(_close_completed({"routed_to": "needs_manual_review"}))

    def test_deferred_and_unknown_still_not_completed(self):
        self.assertFalse(_close_completed({"routed_to": "deferred_uncorroborated"}))
        self.assertFalse(_close_completed({"routed_to": "unknown_reconciling"}))

    def test_alpaca_and_others_stay_completed_byte_identical(self):
        # only needs_manual_review changed; every other route keeps its prior verdict
        for rt in ("alpaca", "already_closed", "internal_aborted", "alpaca_dry_run",
                   "skipped_duplicate", "skipped_resting_tp_owns_profit_side"):
            self.assertTrue(_close_completed({"routed_to": rt}), rt)

    def test_none_and_missing_stay_completed(self):
        self.assertTrue(_close_completed(None))
        self.assertTrue(_close_completed({}))


if __name__ == "__main__":
    unittest.main()
