"""A5-2 job-origin provenance — scheduler-side wiring (Lane 4D, 2026-07-17).

Separate module from test_job_origin_provenance.py because importing
``packages.quantum.scheduler`` requires apscheduler (absent → this module
fails collection exactly like the existing scheduler test modules; CI has
the dependency).

Covers:
1. ``_fire_task`` sends the scheduler origin-assertion headers on the REAL
   outbound request (httpx.post captured; signing patched at its source).
2. ``_format_schedule_slot`` is deterministic.
3. ``start_scheduler`` wires the slot string into every registered job's
   ``_fire_task`` args — the production route, not a helper in isolation.

The internal_retry stamp on ``_retry_failed_jobs`` is covered in
``test_scheduler_retry_failed_jobs.py`` (existing suite, extended).
"""

import importlib
import unittest
import uuid as uuid_mod
from unittest.mock import MagicMock, patch

from packages.quantum.jobs.origin import (
    ACTOR_CLASS_HEADER,
    ORIGIN_HEADER,
    ORIGIN_SCHEDULER,
    REQUEST_ID_HEADER,
    SCHEDULE_ID_HEADER,
    SCHEDULE_SLOT_HEADER,
)


class _SchedulerTestBase(unittest.TestCase):
    def setUp(self):
        from packages.quantum import scheduler
        from packages.quantum.observability import alerts

        importlib.reload(scheduler)
        self.scheduler = scheduler
        # Pre-arm the alert singleton (same pattern as the existing
        # scheduler test modules) so error paths never hit a real client.
        alerts._ADMIN_SUPABASE = MagicMock()
        alerts._ADMIN_INIT_ATTEMPTED = True


class TestFireTaskOriginHeaders(_SchedulerTestBase):
    def test_fire_task_asserts_scheduler_origin(self):
        captured = {}

        def _fake_post(url, content=None, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            resp = MagicMock()
            resp.status_code = 202
            resp.text = "{}"
            return resp

        slot = "cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri"
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={},
        ), patch.object(self.scheduler.httpx, "post", _fake_post):
            self.scheduler._fire_task(
                endpoint="/tasks/suggestions/open",
                scope="tasks:suggestions_open",
                job_id="suggestions_open",
                user_id=None,
                schedule_slot=slot,
            )

        headers = captured["headers"]
        self.assertEqual(headers[ORIGIN_HEADER], ORIGIN_SCHEDULER)
        self.assertEqual(headers[ACTOR_CLASS_HEADER], "apscheduler_in_process")
        self.assertEqual(headers[SCHEDULE_ID_HEADER], "suggestions_open")
        self.assertEqual(headers[SCHEDULE_SLOT_HEADER], slot)
        # Per-fire request id is a valid UUID
        uuid_mod.UUID(headers[REQUEST_ID_HEADER])

    def test_fire_task_without_slot_omits_slot_header_only(self):
        captured = {}

        def _fake_post(url, content=None, headers=None, timeout=None):
            captured["headers"] = headers
            resp = MagicMock()
            resp.status_code = 202
            resp.text = "{}"
            return resp

        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={},
        ), patch.object(self.scheduler.httpx, "post", _fake_post):
            self.scheduler._fire_task(
                endpoint="/internal/tasks/heartbeat",
                scope="tasks:heartbeat",
                job_id="scheduler_heartbeat",
            )

        headers = captured["headers"]
        self.assertEqual(headers[ORIGIN_HEADER], ORIGIN_SCHEDULER)
        self.assertEqual(headers[SCHEDULE_ID_HEADER], "scheduler_heartbeat")
        self.assertNotIn(SCHEDULE_SLOT_HEADER, headers)


class TestFormatScheduleSlot(_SchedulerTestBase):
    def test_deterministic_sorted_fields(self):
        slot = self.scheduler._format_schedule_slot(
            dict(minute="*/5", hour="8-15")
        )
        self.assertEqual(
            slot, "cron:hour=8-15,minute=*/5;tz=America/Chicago;days=mon-fri"
        )

    def test_simple_daily_slot(self):
        slot = self.scheduler._format_schedule_slot(dict(hour=11, minute=0))
        self.assertEqual(
            slot, "cron:hour=11,minute=0;tz=America/Chicago;days=mon-fri"
        )


class TestStartSchedulerWiresSlot(_SchedulerTestBase):
    def test_every_registered_job_carries_its_slot(self):
        """Drive the PRODUCTION registration route: start_scheduler() must
        pass each SCHEDULES entry's slot string as _fire_task's 5th arg."""
        fake_sched = MagicMock()
        with patch.object(
            self.scheduler, "BackgroundScheduler", return_value=fake_sched
        ), patch.object(self.scheduler, "SCHEDULER_ENABLED", True):
            self.scheduler.start_scheduler()

        add_job_calls = fake_sched.add_job.call_args_list
        # All SCHEDULES entries + the auto-retry job registered.
        self.assertEqual(
            len(add_job_calls), len(self.scheduler.SCHEDULES) + 1
        )

        by_id = {}
        for call in add_job_calls:
            job_id = call.kwargs.get("id")
            if call.kwargs.get("args") is not None:
                by_id[job_id] = call.kwargs["args"]

        for job_id, cron_kwargs, endpoint, scope, _desc in self.scheduler.SCHEDULES:
            args = by_id[job_id]
            self.assertEqual(args[0], endpoint)
            self.assertEqual(args[1], scope)
            self.assertEqual(args[2], job_id)
            self.assertEqual(
                args[4],
                self.scheduler._format_schedule_slot(cron_kwargs),
                f"{job_id} must carry its own slot string",
            )

        fake_sched.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
