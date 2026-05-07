"""Tests for #115 PR-A — iv_pipeline_no_data alert + iv_daily_refresh
schedule entry.

Source-level structural assertions only. Convention matches PR #876
(test_fork_clone_insert_alert.py) — the alert call site is wired,
behavior is verified by the next production fire.
"""

import re
import unittest
from pathlib import Path


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)
SCHEDULER_PATH = (
    Path(__file__).parent.parent / "scheduler.py"
)


def _read_scanner() -> str:
    return SCANNER_PATH.read_text(encoding="utf-8")


def _read_scheduler() -> str:
    return SCHEDULER_PATH.read_text(encoding="utf-8")


class TestIvPipelineAlertWired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read_scanner()

    def test_alert_type_present(self):
        self.assertIn("iv_pipeline_no_data", self.src)

    def test_helper_invoked_after_batch_fetch(self):
        """The alert helper must run after `get_iv_context_batch`.

        Anchors on the call site (passing iv_context_map + symbols),
        not the helper definition. Matches the surface at the scan
        cycle boundary.
        """
        batch_idx = self.src.find("get_iv_context_batch(symbols)")
        helper_call_idx = self.src.find(
            "_check_iv_pipeline_health(iv_context_map"
        )
        self.assertGreater(batch_idx, 0)
        self.assertGreater(helper_call_idx, batch_idx)

    def test_helper_definition_uses_alert_with_warning_severity(self):
        anchor = self.src.find('"iv_pipeline_no_data"')
        self.assertGreater(
            anchor, 0,
            "alert_type literal iv_pipeline_no_data not found",
        )
        window = self.src[anchor:anchor + 800]
        self.assertIn('severity="warning"', window)
        self.assertIn("alert(", window)

    def test_threshold_constant_present(self):
        """0.5 default threshold for None-rate trigger."""
        self.assertIn("IV_PIPELINE_NONE_RATE_THRESHOLD = 0.5", self.src)

    def test_dedup_window_constant_present(self):
        """24-hour dedup window so warmup-period alerts don't spam."""
        self.assertIn("IV_PIPELINE_ALERT_DEDUP_HOURS = 24", self.src)

    def test_dedup_query_against_risk_alerts(self):
        """Dedup must check risk_alerts for prior fire within window."""
        anchor = self.src.find("def _check_iv_pipeline_health(")
        self.assertGreater(anchor, 0)
        body = self.src[anchor:anchor + 3000]
        self.assertIn('.table("risk_alerts")', body)
        self.assertIn('.eq("alert_type", "iv_pipeline_no_data")', body)

    def test_operator_action_required_metadata(self):
        """Metadata must hand the operator a diagnosis path."""
        self.assertIn("operator_action_required", self.src)
        self.assertIn("underlying_iv_points", self.src)
        self.assertIn("iv-daily-refresh", self.src)


class TestIvDailyRefreshScheduled(unittest.TestCase):
    """#115 PR-A — confirm `iv_daily_refresh` is in SCHEDULES.

    Diagnostic verdict: NEVER WORKED. The handler had been wired since
    2026-04 but the SCHEDULES entry was missing — APScheduler had no
    knowledge of the job, so `underlying_iv_points` stayed empty for
    five-plus weeks. This test guards against the entry silently
    disappearing in a future refactor.

    Source-level structural assertions; avoids importing
    `apscheduler` so the test collects in lightweight environments.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _read_scheduler()

    def test_iv_daily_refresh_tuple_present(self):
        """The tuple shape (job_id, cron_kwargs, endpoint, scope, desc)
        must list `iv_daily_refresh` with the expected endpoint and
        scope. We anchor on the job_id literal, then look ahead for the
        endpoint + scope strings within the same line.
        """
        m = re.search(
            r'\("iv_daily_refresh",\s*'
            r'dict\(hour=4,\s*minute=30\),\s*'
            r'"/tasks/iv/daily-refresh",\s*'
            r'"tasks:iv_daily_refresh"',
            self.src,
        )
        self.assertIsNotNone(
            m,
            "iv_daily_refresh SCHEDULES entry missing or shape mismatched",
        )


if __name__ == "__main__":
    unittest.main()
