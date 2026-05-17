"""Regression tests for per-job-name RQ work-horse timeout map.

Added 2026-05-17 after Phase 3 attempt (job_run 22516c54-...) failed
at the default 10m budget. Diagnostic confirmed cumulative job time
across 4 completed symbols (525s) crossed the 600s RQ ceiling mid-AMGN.
Misleading error log line attributed the failure to a per-contract
HTTP timeout; math showed the root cause was infrastructure-level
``job_timeout="10m"`` hardcoded in rq_enqueue.py:100.

F1 fix: per-job-name ``JOB_TIMEOUTS`` map with an explicit 6h budget
for ``iv_historical_backfill``. Default timeout unchanged so all other
jobs retain the runaway-detection semantics of the original 10m limit.

Source-level + unit tests, mirroring the convention from
``test_background_queue_routing.py``.
"""

import re
import unittest
from unittest.mock import patch, MagicMock

from packages.quantum.jobs.rq_enqueue import (
    DEFAULT_JOB_TIMEOUT,
    JOB_TIMEOUTS,
    enqueue_idempotent,
)


class TestJobTimeoutMapConstants(unittest.TestCase):
    """Direct constant-shape assertions."""

    def test_default_job_timeout_is_10m(self):
        """Default budget preserves runaway-detection for trading-day
        pipeline jobs (which complete in seconds; a 10m ceiling fires
        loud when something is clearly stuck)."""
        self.assertEqual(DEFAULT_JOB_TIMEOUT, "10m")

    def test_iv_historical_backfill_has_extended_timeout(self):
        """The job name + value that the 2026-05-17 diagnostic motivated.
        Projected full-universe runtime ~2.5h; 6h gives ~50-60% headroom
        over the conservative ~3.9h worst-case."""
        self.assertIn(
            "iv_historical_backfill", JOB_TIMEOUTS,
            "iv_historical_backfill must have an explicit JOB_TIMEOUTS "
            "entry. Default 10m budget killed Phase 3 (job_run "
            "22516c54-...) at exactly 600s — math: 4 symbols × ~131s + "
            "in-flight AMGN ≈ 599s. See diagnostic 2026-05-17.",
        )
        self.assertEqual(
            JOB_TIMEOUTS["iv_historical_backfill"], "6h",
            "iv_historical_backfill timeout should be 6h. Lowering "
            "below ~3-4h would risk killing legitimate full-universe "
            "backfill runs; raising much higher reduces runaway "
            "detection value with no observed need.",
        )

    def test_job_timeouts_map_uses_rq_compatible_format(self):
        """RQ accepts integer seconds or string durations with h/m/s
        suffixes. Lock the value format so a future PR author doesn't
        drift to e.g. '6 hours' or '21600s' (latter is fine but
        inconsistent)."""
        rq_time_pattern = re.compile(r"^\d+[hms]$")

        for job_name, timeout_value in JOB_TIMEOUTS.items():
            with self.subTest(job_name=job_name):
                self.assertIsInstance(
                    timeout_value, str,
                    f"{job_name}: expected str, got {type(timeout_value)!r}",
                )
                self.assertRegex(
                    timeout_value, rq_time_pattern,
                    f"{job_name}: timeout {timeout_value!r} doesn't "
                    f"match RQ format (digits + h/m/s suffix)",
                )

        self.assertRegex(
            DEFAULT_JOB_TIMEOUT, rq_time_pattern,
            f"DEFAULT_JOB_TIMEOUT {DEFAULT_JOB_TIMEOUT!r} must match "
            f"RQ format",
        )


class TestEnqueueIdempotentAppliesTimeoutMap(unittest.TestCase):
    """End-to-end: verify ``enqueue_idempotent`` actually passes the
    correct timeout to RQ for both mapped and unmapped job names."""

    @patch("packages.quantum.jobs.rq_enqueue.get_queue")
    def test_mapped_job_uses_extended_timeout(self, mock_get_queue):
        """``iv_historical_backfill`` enqueue must reach RQ with
        ``job_timeout='6h'`` (or whatever JOB_TIMEOUTS['iv_historical_backfill']
        is). This is the assertion that catches a future map drift OR
        a future regression at the call site."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_job.enqueued_at = None
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        enqueue_idempotent(
            job_name="iv_historical_backfill",
            idempotency_key="test-key",
            payload={"days": 60},
        )

        mock_queue.enqueue.assert_called_once()
        call_kwargs = mock_queue.enqueue.call_args.kwargs
        self.assertEqual(
            call_kwargs["job_timeout"],
            JOB_TIMEOUTS["iv_historical_backfill"],
            "iv_historical_backfill must reach RQ with the JOB_TIMEOUTS "
            "value, not the default 10m budget that killed Phase 3.",
        )

    @patch("packages.quantum.jobs.rq_enqueue.get_queue")
    def test_unmapped_job_uses_default_timeout(self, mock_get_queue):
        """Regression-guard: an unmapped job_name must fall back to
        ``DEFAULT_JOB_TIMEOUT``. This preserves the runaway-detection
        semantics for every existing trading-day pipeline job
        (alpaca_order_sync, intraday_risk_monitor, etc.)."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_job.enqueued_at = None
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        enqueue_idempotent(
            job_name="some_unmapped_job_name",
            idempotency_key="test-key",
            payload={},
        )

        mock_queue.enqueue.assert_called_once()
        call_kwargs = mock_queue.enqueue.call_args.kwargs
        self.assertEqual(
            call_kwargs["job_timeout"],
            DEFAULT_JOB_TIMEOUT,
            "Unmapped jobs must use DEFAULT_JOB_TIMEOUT. If this "
            "fails, either the call-site lookup regressed or "
            "JOB_TIMEOUTS gained an unintended entry.",
        )


if __name__ == "__main__":
    unittest.main()
