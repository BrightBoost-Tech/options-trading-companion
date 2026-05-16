"""Tests for background worker queue routing.

Verifies the Option B mitigation for the 2026-05-15 worker-queue
blocker (Tier 1 backlog candidate). Specifically:

1. ``iv_historical_backfill`` route in ``internal_tasks.py`` passes
   ``queue_name=BACKGROUND_QUEUE`` to ``enqueue_job_run`` so the
   multi-hour run goes to the dedicated background Railway worker.
2. Other ``internal_tasks.py`` routes (e.g. ``iv_daily_refresh``)
   remain on the default "otc" queue — regression-guard against a
   future blanket change accidentally routing trading-day pipeline
   jobs to background.
3. ``enqueue_idempotent`` (``packages/quantum/jobs/rq_enqueue.py``)
   propagates ``queue_name`` through to the actual RQ ``Queue``
   construction.
4. ``make_job_id`` is queue-agnostic — same ``job_name`` +
   ``idempotency_key`` produces the same job_id regardless of the
   target queue. This is intentional: a job that's been routed to
   "background" should still dedup against an earlier "otc"
   enqueue of the same logical job, preventing cross-queue
   double-execution if the routing is ever flipped mid-cycle.

Test convention follows ``test_internal_tasks_tier1_body_acceptance.py``
and ``test_iv_daily_refresh_enqueue_canonical.py``: source-level
structural assertions for route shape (no FastAPI test client needed
to validate the contract), plus targeted unit tests for the small
``rq_enqueue`` helpers.
"""

import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from packages.quantum.jobs.rq_enqueue import (
    BACKGROUND_QUEUE,
    enqueue_idempotent,
    make_job_id,
)


INTERNAL_TASKS_PATH = (
    Path(__file__).parent.parent / "internal_tasks.py"
)


def _function_body(src: str, fn_name: str) -> str:
    """Extract the source range from ``async def <fn_name>(`` to the
    next ``@router.post`` (next endpoint) — gives a window scoped to
    that endpoint's signature + body. Mirrors the helper in
    ``test_internal_tasks_tier1_body_acceptance.py``."""
    anchor = src.find(f"async def {fn_name}(")
    assert anchor > 0, f"endpoint {fn_name} not found in internal_tasks.py"
    end_match = re.search(r"\n@router\.post\(", src[anchor + 50:])
    end = (anchor + 50 + end_match.start()) if end_match else len(src)
    return src[anchor:end]


class TestIvHistoricalBackfillRoutesToBackgroundQueue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = INTERNAL_TASKS_PATH.read_text(encoding="utf-8")

    def test_background_queue_constant_imported(self):
        """``internal_tasks.py`` must import BACKGROUND_QUEUE from
        the canonical source (``packages.quantum.jobs.rq_enqueue``)
        so the route + constant stay in lockstep."""
        self.assertIn(
            "from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE",
            self.src,
            "internal_tasks.py must import BACKGROUND_QUEUE from "
            "rq_enqueue — do not inline the string 'background' at "
            "the call site (would drift from the constant).",
        )

    def test_iv_historical_backfill_passes_background_queue_name(self):
        """The ``iv_historical_backfill`` route's ``enqueue_job_run``
        call MUST pass ``queue_name=BACKGROUND_QUEUE``. Without this,
        the multi-hour Phase 1/3 run blocks the "otc" worker and
        starves the trading-day pipeline (reproduced 2026-05-15
        job_run ``9627c667-61e5-4915-a83c-a584b03bab0a``)."""
        body = _function_body(self.src, "iv_historical_backfill_task")
        self.assertIn(
            "queue_name=BACKGROUND_QUEUE", body,
            "iv_historical_backfill_task must route to "
            "BACKGROUND_QUEUE so the multi-hour run does not starve "
            "the primary 'otc' worker. See backlog Tier 1 candidate "
            "2026-05-15 worker-queue blocker.",
        )

    def test_iv_daily_refresh_does_not_route_to_background(self):
        """Regression-guard: trading-day pipeline jobs stay on the
        default queue. ``iv_daily_refresh`` runs every weekday at
        04:30 CT and writes ~70 rows in ~4 min — must not be
        accidentally routed to background, where the background
        worker may be busy on a multi-hour backfill."""
        body = _function_body(self.src, "iv_daily_refresh_task")
        self.assertNotIn(
            "queue_name=BACKGROUND_QUEUE", body,
            "iv_daily_refresh_task must remain on the default 'otc' "
            "queue. Background queue is for long-running jobs only.",
        )
        self.assertNotIn(
            'queue_name="background"', body,
            "iv_daily_refresh_task must not route to background "
            "queue (inline string form).",
        )


class TestEnqueueIdempotentQueuePlumbing(unittest.TestCase):
    """Unit tests for the rq_enqueue helpers — small but
    load-bearing for the multi-queue split."""

    def test_background_queue_constant_value(self):
        """The constant value must match the RQ queue name the
        Railway worker-background service listens on (``rq worker
        background``). Drift here would silently fail in production
        (jobs enqueued, never consumed)."""
        self.assertEqual(BACKGROUND_QUEUE, "background")

    @patch("packages.quantum.jobs.rq_enqueue.get_queue")
    def test_enqueue_idempotent_passes_queue_name_to_get_queue(
        self, mock_get_queue
    ):
        """``enqueue_idempotent(queue_name=X)`` must pass X through
        to ``get_queue(X)`` so the actual RQ Queue is constructed on
        the right named queue. Without this propagation the
        BACKGROUND_QUEUE routing in internal_tasks.py would be a
        no-op."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_job.enqueued_at = None
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        enqueue_idempotent(
            job_name="test_job",
            idempotency_key="test-key",
            payload={"foo": "bar"},
            queue_name=BACKGROUND_QUEUE,
        )

        mock_get_queue.assert_called_once_with("background")

    @patch("packages.quantum.jobs.rq_enqueue.get_queue")
    def test_enqueue_idempotent_defaults_to_otc(self, mock_get_queue):
        """Regression-guard: the default queue stays "otc" so
        existing callers (every other route) keep their current
        behavior."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_job.enqueued_at = None
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        enqueue_idempotent(
            job_name="test_job",
            idempotency_key="test-key",
            payload={},
        )

        mock_get_queue.assert_called_once_with("otc")


class TestMakeJobIdIsQueueAgnostic(unittest.TestCase):
    """Documents intended behavior: a job's identity (hash) is
    independent of which queue it's routed to."""

    def test_make_job_id_signature_does_not_accept_queue_name(self):
        """If a future refactor adds ``queue_name`` to
        ``make_job_id``, the same logical job enqueued to "otc" vs
        "background" would hash differently and could be
        double-executed across queues. Fail loud if the signature
        changes — design review required."""
        sig = inspect.signature(make_job_id)
        self.assertEqual(
            list(sig.parameters.keys()),
            ["job_name", "idempotency_key"],
            "make_job_id must remain queue-agnostic. Adding "
            "queue_name to the hash input would allow the same "
            "logical job to be double-executed across queues. If "
            "this is intentional, document the new semantics + "
            "audit all enqueue call sites.",
        )

    def test_same_inputs_produce_same_job_id_irrespective_of_queue(self):
        """End-to-end behavioral assertion: the job_id hash is
        determined entirely by ``job_name + idempotency_key``."""
        job_id_a = make_job_id("iv_historical_backfill", "2026-05-15-key")
        job_id_b = make_job_id("iv_historical_backfill", "2026-05-15-key")
        self.assertEqual(job_id_a, job_id_b)


if __name__ == "__main__":
    unittest.main()
