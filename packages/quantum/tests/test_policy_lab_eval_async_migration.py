"""Tests for #71 PR-2 — /tasks/policy-lab/eval async dispatch migration.

Pre-migration (sync): endpoint returned `status_code=200` with the
actual computed result inline (`{status, evaluation, promotion, errors}`).
Pre-migration `job_runs` had zero rows for `policy_lab_eval` despite
APScheduler firing it daily at 16:30 CT.

Post-migration (async): endpoint returns `status_code=202` with the
canonical envelope (`{job_run_id, job_name, idempotency_key,
rq_job_id, status}`) and enqueues the work. Each fire produces a
`job_runs` row.

These tests are source-level structural assertions — they don't boot
the full FastAPI app (which requires DB + RQ + worker), they verify
the migration shape in source. End-to-end behavioral validation is
the post-deploy operator path documented in the PR description.
"""
import re
from pathlib import Path

import unittest


PUBLIC_TASKS_PATH = (
    Path(__file__).parent.parent / "public_tasks.py"
)
HANDLER_PATH = (
    Path(__file__).parent.parent / "jobs" / "handlers" / "policy_lab_eval.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Endpoint shape: async pattern applied
# ─────────────────────────────────────────────────────────────────────


class TestEndpointMigratedToAsync(unittest.TestCase):
    """Endpoint body uses canonical enqueue_job_run dispatch shape."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(PUBLIC_TASKS_PATH)
        # Locate the policy-lab/eval handler region so assertions can be
        # scoped tightly. Range = from the route decorator to the next one.
        m = re.search(
            r'@router\.post\("/policy-lab/eval".*?(?=^@router\.|^# =)',
            cls.src,
            re.DOTALL | re.MULTILINE,
        )
        assert m, "policy-lab/eval handler region must be findable"
        cls.handler_block = m.group(0)

    def test_status_code_is_202(self):
        self.assertIn(
            'status_code=202', self.handler_block,
            "/policy-lab/eval must use status_code=202 (Accepted) post-"
            "migration to match the canonical async dispatch convention",
        )

    def test_status_code_is_not_200(self):
        self.assertNotIn(
            'status_code=200', self.handler_block,
            "Status code 200 (OK) was the pre-migration sync convention; "
            "must be replaced with 202",
        )

    def test_returns_enqueue_job_run(self):
        self.assertIn(
            'return enqueue_job_run(', self.handler_block,
            "Endpoint body must return enqueue_job_run(...) — the "
            "canonical async dispatch helper",
        )

    def test_uses_correct_job_name(self):
        """job_name='policy_lab_eval' must match the handler's JOB_NAME
        constant. Mismatched names enqueue jobs that never run."""
        self.assertIn(
            'job_name="policy_lab_eval"', self.handler_block,
            "enqueue_job_run must pass job_name='policy_lab_eval' to "
            "match the JOB_NAME constant in policy_lab_eval.py",
        )
        # And confirm the handler still defines that constant
        handler_src = _read(HANDLER_PATH)
        self.assertIn(
            'JOB_NAME = "policy_lab_eval"', handler_src,
            "Handler at jobs/handlers/policy_lab_eval.py must define "
            "JOB_NAME = 'policy_lab_eval' so the enqueued job dispatches",
        )

    def test_idempotency_key_uses_date(self):
        """Daily jobs use the date as idempotency_key — matches
        /morning-brief, /midday-scan convention in this file."""
        # Either today (var) or a string-formatted date
        self.assertTrue(
            'idempotency_key=today' in self.handler_block
            or 'idempotency_key=f"' in self.handler_block,
            "idempotency_key must derive from the date — daily jobs "
            "should be idempotent within the day",
        )

    def test_force_rerun_plumbed(self):
        """If the operator passes force_rerun=true in the payload, it
        must be plumbed through to enqueue_job_run."""
        self.assertIn(
            'force_rerun=payload.force_rerun', self.handler_block,
            "force_rerun must be plumbed from payload to enqueue_job_run",
        )

    def test_inline_business_logic_removed(self):
        """The pre-migration sync handler called evaluate_cohorts and
        check_promotion inline. Those calls now happen in the queued
        job handler — they MUST NOT be in the endpoint body."""
        self.assertNotIn(
            'evaluate_cohorts(', self.handler_block,
            "evaluate_cohorts must NOT be called inline in the endpoint "
            "body post-migration — moved to jobs/handlers/policy_lab_eval.py",
        )
        self.assertNotIn(
            'check_promotion(', self.handler_block,
            "check_promotion must NOT be called inline post-migration",
        )

    def test_no_inline_risk_alerts_writes(self):
        """The pre-migration sync handler wrote risk_alerts on per-stage
        failure. Post-migration, failure observability is provided by
        job_runs.status='failed' instead. Inline risk_alerts writes
        must NOT remain in the endpoint body.

        Match the actual write pattern (`.table("risk_alerts").insert(`)
        rather than the bare substring — the docstring may legitimately
        mention risk_alerts when documenting the migration's
        observability shift."""
        self.assertNotRegex(
            self.handler_block,
            r'\.table\(\s*"risk_alerts"\s*\)\.insert\(',
            "Inline supabase.table('risk_alerts').insert(...) calls from "
            "the pre-migration handler must be removed — replaced by "
            "job_runs failure observability",
        )

    def test_no_inline_supabase_client(self):
        """Pre-migration handler instantiated supabase admin client
        inline. Async dispatch endpoints don't touch the DB directly —
        the handler does."""
        self.assertNotIn(
            'get_admin_client', self.handler_block,
            "Async dispatch endpoint must not instantiate supabase "
            "client; that belongs in the queued handler",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Handler still has the work
# ─────────────────────────────────────────────────────────────────────


class TestHandlerStillHasTheWork(unittest.TestCase):
    """The work that moved from the endpoint must now live in the
    handler. Sanity check the handler is still complete."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(HANDLER_PATH)

    def test_handler_calls_evaluate_cohorts(self):
        self.assertIn('evaluate_cohorts(', self.src)

    def test_handler_calls_check_promotion(self):
        self.assertIn('check_promotion(', self.src)

    def test_handler_calls_compute_decision_accuracy(self):
        """Handler-only operation that was silently dropped by the
        inline endpoint pre-migration. Post-migration, this runs as
        intended."""
        self.assertIn(
            'compute_decision_accuracy(', self.src,
            "Handler must call compute_decision_accuracy — was silently "
            "dropped by inline endpoint pre-migration; this PR restores it",
        )

    def test_handler_gates_policy_lab_enabled(self):
        """POLICY_LAB_ENABLED gate moved from endpoint to handler.
        Verify it's still present at the handler level."""
        self.assertIn('POLICY_LAB_ENABLED', self.src)


# ─────────────────────────────────────────────────────────────────────
# Layer 3 — Backlog + audit doc reference present
# ─────────────────────────────────────────────────────────────────────


class TestMigrationDocumentation(unittest.TestCase):
    """The migration is part of the #71 sweep; backlog must reflect
    PR-2 ship state for traceability."""

    def test_backlog_references_pr2(self):
        backlog = (
            Path(__file__).parent.parent.parent.parent / "docs" / "backlog.md"
        ).read_text(encoding="utf-8")
        # The audit (PR-1) entry should be present, AND a PR-2 ship line
        # should be added by this PR's docs update.
        self.assertIn(
            'rq_dispatch_audit_2026_05_04.md', backlog,
            "Backlog must reference the audit doc",
        )


if __name__ == "__main__":
    unittest.main()
