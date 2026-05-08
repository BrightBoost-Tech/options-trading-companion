"""Class-prevention test for #115 PR-A wrapper-drift bug.

PR-A (2026-05-07) shipped a SCHEDULES entry with URL
``/tasks/iv/daily-refresh`` but the actual route is
``/internal/tasks/iv/daily-refresh`` (prefix on
``internal_tasks.router``). The first natural fire produced an HTTP
404. The H2 doctrine alert (``scheduler_task_http_status_error``)
caught it at first occurrence — pathway is healthy — but the
underlying defect type (string identifier in module A doesn't match
real registration in module B) is exactly the wrapper-drift class
called out by ``docs/loud_error_doctrine.md``.

This test asserts every URL in ``scheduler.SCHEDULES`` resolves to a
real handler path produced by joining the router's ``prefix`` with a
declared handler route. Catches the class going forward.

Imports only the two task routers (internal_tasks + public_tasks)
rather than the full FastAPI app — keeps test fast and avoids the
heavy app-construction dependency chain.
"""

import unittest

from packages.quantum.scheduler import SCHEDULES


def _enumerate_router_paths(router) -> set:
    """Collect every externally-visible route path on a router.

    FastAPI's ``APIRouter`` stamps the prefix into each ``APIRoute.path``
    at construction time, so iterating ``router.routes`` already yields
    full ``"/internal/tasks/iv/daily-refresh"``-style URLs without
    needing to re-concatenate with ``router.prefix``.
    """
    paths = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
    return paths


def _all_task_route_paths() -> set:
    """Collect every URL path served by the task routers.

    PR-A's SCHEDULES URLs point exclusively at task routers
    (``/tasks/...`` from public_tasks, ``/internal/tasks/...`` from
    internal_tasks). The few SCHEDULES entries that point at other
    paths (e.g., ``/internal/tasks/heartbeat``) are also covered
    because both routers carry their own ``/heartbeat``-style routes.
    """
    from packages.quantum import internal_tasks, public_tasks
    paths = set()
    paths |= _enumerate_router_paths(internal_tasks.router)
    paths |= _enumerate_router_paths(public_tasks.router)
    return paths


class TestScheduleUrlsResolveToRoutes(unittest.TestCase):
    """Every URL in scheduler.SCHEDULES must resolve to a registered
    FastAPI route.

    Caught: PR-A iv_daily_refresh URL prefix mismatch (2026-05-08).
    """

    @classmethod
    def setUpClass(cls):
        cls.registered_paths = _all_task_route_paths()

    def test_all_schedule_urls_registered(self):
        # SCHEDULES tuple shape (per scheduler.py line 42 comment):
        #   (job_id, cron_kwargs, task_endpoint, scope, description)
        missing = []
        for entry in SCHEDULES:
            job_id = entry[0]
            url = entry[2]
            if url not in self.registered_paths:
                missing.append(f"  {job_id}: {url}")

        self.assertFalse(
            missing,
            "SCHEDULES contains URLs that don't resolve to a registered "
            "task-router path:\n" + "\n".join(missing) +
            f"\n\nRegistered paths ({len(self.registered_paths)}):\n  "
            + "\n  ".join(sorted(self.registered_paths)),
        )

    def test_iv_daily_refresh_specifically(self):
        """Targeted assertion for the bug this PR fixes — explicit
        regression guard so a future revert is loud.
        """
        iv_entry = next(
            (e for e in SCHEDULES if e[0] == "iv_daily_refresh"), None,
        )
        self.assertIsNotNone(
            iv_entry, "iv_daily_refresh missing from SCHEDULES",
        )
        self.assertEqual(
            iv_entry[2], "/internal/tasks/iv/daily-refresh",
            "iv_daily_refresh URL must include the /internal prefix that "
            "internal_tasks.router actually mounts under. The pre-2026-05-08 "
            "value '/tasks/iv/daily-refresh' produced HTTP 404 on first fire.",
        )


if __name__ == "__main__":
    unittest.main()
