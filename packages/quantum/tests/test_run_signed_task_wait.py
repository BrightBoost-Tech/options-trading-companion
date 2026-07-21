"""Tests for the optional --wait / status-follow in scripts/run_signed_task.py.

The signed CLI returns after the HTTP 202 enqueue; --wait follows the returned
job_run_id to a terminal state via the SIGNED read-only status route
(scope 'tasks:job_status') and surfaces the redacted terminal reason.

All HTTP is mocked at the ``requests`` boundary — NOTHING hits production.
Time is injected (sleep_fn / monotonic_fn) so the polling loop is deterministic
and instant.

Covers the required matrix:
  queued->running->succeeded (exit 0) · partial · failed · cancelled ·
  timeout (nonzero) · 404 job-not-found · status-route auth failure ·
  and the DEFAULT no-wait path (returns after 202 WITHOUT polling).
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add scripts to path (mirrors test_run_signed_task.py convention).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from run_signed_task import (  # noqa: E402
    _follow_job_status,
    run_task,
    WAIT_TERMINAL_STATES,
    JOB_STATUS_SCOPE,
)

JID = "11111111-1111-1111-1111-111111111111"
BASE = "https://api.test"


def _resp(status_code=200, body=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = {} if body is None else body
    return r


def _noop_sleep(*_a, **_k):
    return None


def _frozen_clock():
    """Monotonic that never advances — the deadline is never reached."""
    return 0.0


# =============================================================================
# _follow_job_status — polling matrix (direct, HTTP mocked)
# =============================================================================

class TestFollowJobStatus(unittest.TestCase):

    def _follow(self, get_side_effect, poll_seconds=1, max_wait=120,
                monotonic_fn=_frozen_clock):
        with patch("run_signed_task.requests.get", side_effect=get_side_effect) as mget:
            rc = _follow_job_status(
                base_url=BASE,
                job_run_id=JID,
                secret="s",
                key_id=None,
                poll_seconds=poll_seconds,
                max_wait=max_wait,
                sleep_fn=_noop_sleep,
                monotonic_fn=monotonic_fn,
            )
        return rc, mget

    def test_queued_running_succeeded_exit_zero(self):
        rc, mget = self._follow([
            _resp(200, {"status": "queued"}),
            _resp(200, {"status": "running"}),
            _resp(200, {"status": "succeeded", "duration_ms": 1234,
                        "result": {"counts": {"processed": 2}}}),
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(mget.call_count, 3)

    def test_partial_exit_nonzero(self):
        rc, mget = self._follow([
            _resp(200, {"status": "partial", "result": {"errors_count": 1}}),
        ])
        self.assertEqual(rc, 1)
        self.assertEqual(mget.call_count, 1)

    def test_failed_exit_nonzero(self):
        rc, _ = self._follow([
            _resp(200, {"status": "failed", "reason": "handler raised ValueError"}),
        ])
        self.assertEqual(rc, 1)

    def test_cancelled_exit_nonzero(self):
        rc, _ = self._follow([
            _resp(200, {"status": "cancelled",
                        "cancelled_reason": "global_ops_pause",
                        "cancelled_detail": "streak_breaker_tripped"}),
        ])
        self.assertEqual(rc, 1)

    def test_dead_lettered_and_failed_retryable_are_terminal_nonzero(self):
        # Both are terminal-for-wait (mirror the enqueue-side set) and nonzero.
        for term in ("dead_lettered", "failed_retryable"):
            rc, mget = self._follow([_resp(200, {"status": term})])
            self.assertEqual(rc, 1, term)
            self.assertEqual(mget.call_count, 1, term)

    def test_timeout_exit_nonzero(self):
        # Always 'running'; the injected clock crosses max_wait after 2 sleeps.
        times = iter([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
        rc, mget = self._follow(
            get_side_effect=lambda *a, **k: _resp(200, {"status": "running"}),
            max_wait=120,
            monotonic_fn=lambda: next(times),
        )
        self.assertEqual(rc, 1)
        self.assertGreaterEqual(mget.call_count, 1)

    def test_job_not_found_404_exit_nonzero(self):
        rc, mget = self._follow([_resp(404, {"detail": "Job run not found"})])
        self.assertEqual(rc, 1)
        self.assertEqual(mget.call_count, 1)

    def test_status_route_auth_failure_401_exit_nonzero(self):
        rc, mget = self._follow([_resp(401, {"detail": "Invalid signature"})])
        self.assertEqual(rc, 1)
        self.assertEqual(mget.call_count, 1)

    def test_status_route_auth_failure_403_exit_nonzero(self):
        rc, _ = self._follow([_resp(403, {"detail": "Scope mismatch"})])
        self.assertEqual(rc, 1)

    def test_never_enqueues_or_retries_only_gets(self):
        # Pure polling: the follow loop must only ever issue GETs, never POSTs.
        with patch("run_signed_task.requests.post") as mpost:
            rc, mget = self._follow([
                _resp(200, {"status": "running"}),
                _resp(200, {"status": "succeeded"}),
            ])
        self.assertEqual(rc, 0)
        mpost.assert_not_called()

    def test_signs_each_poll_with_job_status_scope(self):
        captured = {}

        def _capture(url, headers=None, timeout=None):
            captured["scope"] = headers.get("X-Task-Scope")
            return _resp(200, {"status": "succeeded"})

        with patch("run_signed_task.requests.get", side_effect=_capture):
            rc = _follow_job_status(
                base_url=BASE, job_run_id=JID, secret="s", key_id=None,
                poll_seconds=1, max_wait=5,
                sleep_fn=_noop_sleep, monotonic_fn=_frozen_clock,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(captured["scope"], JOB_STATUS_SCOPE)


# =============================================================================
# run_task — DEFAULT (no-wait) byte-identical + --wait end-to-end
# =============================================================================

class TestRunTaskWaitWiring(unittest.TestCase):

    ENV = {
        "BASE_URL": BASE,
        "TASK_SIGNING_SECRET": "test-secret",
        "GITHUB_STEP_SUMMARY": "",  # falsy -> write_step_summary no-ops
    }

    def test_default_no_wait_returns_after_202_without_polling(self):
        """DEFAULT path: no --wait -> return right after the 202, NO status GET."""
        post_resp = _resp(202, {"job_run_id": JID, "status": "queued"})
        with patch.dict(os.environ, self.ENV, clear=False), \
                patch("run_signed_task.requests.post", return_value=post_resp) as mpost, \
                patch("run_signed_task.requests.get") as mget:
            rc = run_task(task_name="ops_health_check", skip_time_gate=True)
        self.assertEqual(rc, 0)
        self.assertEqual(mpost.call_count, 1)
        mget.assert_not_called()  # the byte-identical proof: zero polling

    def test_wait_true_follows_job_run_id_to_success(self):
        """--wait drives run_task -> _follow_job_status end-to-end (HTTP mocked)."""
        post_resp = _resp(202, {"job_run_id": JID, "status": "queued"})
        get_resp = _resp(200, {"status": "succeeded", "duration_ms": 10})
        with patch.dict(os.environ, self.ENV, clear=False), \
                patch("run_signed_task.requests.post", return_value=post_resp), \
                patch("run_signed_task.requests.get", return_value=get_resp) as mget, \
                patch("run_signed_task.time.sleep", _noop_sleep):
            rc = run_task(task_name="ops_health_check", skip_time_gate=True,
                          wait=True, poll_seconds=1, max_wait=10)
        self.assertEqual(rc, 0)
        self.assertEqual(mget.call_count, 1)

    def test_wait_true_terminal_failure_exits_nonzero(self):
        post_resp = _resp(202, {"job_run_id": JID, "status": "queued"})
        get_resp = _resp(200, {"status": "failed", "reason": "boom"})
        with patch.dict(os.environ, self.ENV, clear=False), \
                patch("run_signed_task.requests.post", return_value=post_resp), \
                patch("run_signed_task.requests.get", return_value=get_resp), \
                patch("run_signed_task.time.sleep", _noop_sleep):
            rc = run_task(task_name="ops_health_check", skip_time_gate=True,
                          wait=True, poll_seconds=1, max_wait=10)
        self.assertEqual(rc, 1)

    def test_wait_true_without_job_run_id_is_noop(self):
        """--wait but the response carries no job_run_id -> nothing to follow."""
        post_resp = _resp(200, {"status": "ok"})  # synchronous task shape
        with patch.dict(os.environ, self.ENV, clear=False), \
                patch("run_signed_task.requests.post", return_value=post_resp), \
                patch("run_signed_task.requests.get") as mget:
            rc = run_task(task_name="ops_health_check", skip_time_gate=True, wait=True)
        self.assertEqual(rc, 0)
        mget.assert_not_called()


if __name__ == "__main__":
    unittest.main()
