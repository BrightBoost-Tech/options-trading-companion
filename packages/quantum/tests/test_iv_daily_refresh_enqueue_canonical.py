"""Regression guard for #115 PR-A enqueue-path wrapper-drift.

Caught 2026-05-08: ``iv_daily_refresh_task`` in ``internal_tasks.py``
used the legacy DB-only ``enqueue_idempotent`` (from
``packages.quantum.jobs.enqueue``) — wrote a ``status='queued'``
row to ``job_runs`` but never pushed to RQ, so the worker never
picked it up. d4bba93 (2026-03-28) migrated 4 sibling endpoints
to the canonical ``enqueue_job_run`` (DB + RQ push) but carved
out iv_daily_refresh as "NOT in target list" — undocumented
oversight per d4bba93 commit message. PR-A activating the
SCHEDULES entry surfaced the gap as a 30+ minute queue stuck.

This test asserts ``iv_daily_refresh_task`` specifically uses
``enqueue_job_run``. Targeted regression guard; the broader class
(other dormant endpoints in ``internal_tasks.py`` still on the
legacy path) is documented in the PR description as known
follow-up scope rather than enforced here — those endpoints are
not currently in SCHEDULES, so they're latent rather than active.
"""

import re
import unittest
from pathlib import Path


INTERNAL_TASKS_PATH = (
    Path(__file__).parent.parent / "internal_tasks.py"
)


class TestIvDailyRefreshUsesCanonicalEnqueue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = INTERNAL_TASKS_PATH.read_text(encoding="utf-8")

    def test_iv_daily_refresh_task_uses_enqueue_job_run(self):
        """The function body of ``iv_daily_refresh_task`` must call
        ``enqueue_job_run`` (canonical RQ-pushing path) — NOT the
        legacy ``enqueue_idempotent`` from ``jobs/enqueue.py``.
        """
        anchor = self.src.find("async def iv_daily_refresh_task(")
        self.assertGreater(
            anchor, 0,
            "iv_daily_refresh_task missing from internal_tasks.py",
        )

        # Walk forward to next def or @router.post (function body
        # extent). Scan that window for the right enqueue call.
        end_match = re.search(
            r"\n(@router\.post|async def |def )",
            self.src[anchor + 50:],
        )
        body_end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        body = self.src[anchor:body_end]

        self.assertIn(
            "enqueue_job_run(", body,
            "iv_daily_refresh_task must use the canonical "
            "enqueue_job_run path (DB + RQ push). Legacy "
            "enqueue_idempotent only writes job_runs without RQ — "
            "jobs sit queued forever. See d4bba93 for the migration "
            "pattern; PR-A's first fire produced 30+ min queue stuck "
            "on 2026-05-08 because of this exact regression.",
        )
        self.assertNotIn(
            "enqueue_idempotent(", body,
            "iv_daily_refresh_task uses the legacy DB-only enqueue "
            "path. Migrate to enqueue_job_run.",
        )

    def test_iv_daily_refresh_uses_underscored_job_name(self):
        """d4bba93's standardisation: job_name must match the
        handler's ``JOB_NAME`` constant. Both sides use underscores
        (``iv_daily_refresh``) post-fix; pre-fix used hyphens
        (``iv-daily-refresh``).
        """
        anchor = self.src.find("async def iv_daily_refresh_task(")
        self.assertGreater(anchor, 0)
        end_match = re.search(
            r"\n(@router\.post|async def |def )",
            self.src[anchor + 50:],
        )
        body_end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        body = self.src[anchor:body_end]

        self.assertIn(
            'job_name="iv_daily_refresh"', body,
            "iv_daily_refresh_task must pass the underscored job_name "
            "to enqueue_job_run, matching the handler's JOB_NAME "
            "constant. d4bba93 fix #2: hyphenated job_names don't "
            "resolve via discover_handlers().",
        )

    def test_handler_job_name_underscored(self):
        """The handler's ``JOB_NAME`` constant must match what the
        endpoint passes — both underscored.
        """
        handler_path = (
            INTERNAL_TASKS_PATH.parent / "jobs" / "handlers"
            / "iv_daily_refresh.py"
        )
        handler_src = handler_path.read_text(encoding="utf-8")
        self.assertIn('JOB_NAME = "iv_daily_refresh"', handler_src)
        self.assertNotIn('JOB_NAME = "iv-daily-refresh"', handler_src)


if __name__ == "__main__":
    unittest.main()
