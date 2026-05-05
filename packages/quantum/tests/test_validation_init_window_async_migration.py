"""Tests for #71 PR-3 — /tasks/validation/init-window async dispatch migration.

Pre-migration (sync): endpoint called
`GoLiveValidationService.ensure_forward_window_initialized` inline,
returned a custom envelope including the service result + idempotency
key + bucket_date + as_of timestamp. status_code=200.

Post-migration (async): endpoint enqueues `validation_init_window`
job and returns the canonical `{job_run_id, ...}` envelope.
status_code=202. The new handler at
`packages/quantum/jobs/handlers/validation_init_window.py` runs the
service call inside a worker; auto-discovered via the existing
`packages/quantum/jobs/registry.py` mechanism.

Key design decision (vs PR-2): the paper-mode + paused gates remain at
the endpoint to reject before enqueue, avoiding noisy
"queued then failed" job_runs rows. This matches the existing
_check_readiness_hardening_gates pattern.
"""
import re
import unittest
from pathlib import Path


PUBLIC_TASKS_PATH = (
    Path(__file__).parent.parent / "public_tasks.py"
)
HANDLER_PATH = (
    Path(__file__).parent.parent / "jobs" / "handlers"
    / "validation_init_window.py"
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
        # Scope handler region from route decorator to next route or section
        # marker. Tightens assertions to just this endpoint's body.
        m = re.search(
            r'@router\.post\("/validation/init-window".*?(?=^@router\.|^# =)',
            cls.src,
            re.DOTALL | re.MULTILINE,
        )
        assert m, "validation/init-window handler region must be findable"
        cls.handler_block = m.group(0)

    def test_status_code_is_202(self):
        self.assertIn(
            'status_code=202', self.handler_block,
            "/validation/init-window must use status_code=202 post-migration",
        )

    def test_status_code_is_not_200(self):
        self.assertNotIn(
            'status_code=200', self.handler_block,
            "Status code 200 (OK) was the pre-migration sync convention",
        )

    def test_returns_enqueue_job_run(self):
        self.assertIn(
            'return enqueue_job_run(', self.handler_block,
            "Endpoint body must return enqueue_job_run(...)",
        )

    def test_uses_correct_job_name(self):
        """job_name='validation_init_window' must match the handler's
        JOB_NAME constant. Mismatched names enqueue jobs that never
        dispatch (handler discover_handlers wouldn't match)."""
        self.assertIn(
            'job_name="validation_init_window"', self.handler_block,
            "enqueue_job_run must pass job_name='validation_init_window'",
        )

    def test_force_rerun_plumbed(self):
        self.assertIn(
            'force_rerun=payload.force_rerun', self.handler_block,
            "force_rerun must be plumbed from payload to enqueue_job_run",
        )

    def test_inline_service_call_removed(self):
        """The pre-migration sync handler called
        ensure_forward_window_initialized inline; the call must now be
        ONLY in the handler module, not in the endpoint body."""
        self.assertNotIn(
            'ensure_forward_window_initialized', self.handler_block,
            "ensure_forward_window_initialized must NOT be called inline "
            "in the endpoint body — moved to "
            "jobs/handlers/validation_init_window.py",
        )

    def test_no_inline_service_instantiation(self):
        """Pre-migration handler did `service = GoLiveValidationService(...)`.
        That instantiation belongs in the handler now."""
        self.assertNotIn(
            'GoLiveValidationService(', self.handler_block,
            "Service instantiation must move to the handler",
        )

    def test_preserves_paper_mode_gate(self):
        """The _check_readiness_hardening_gates gate is design-intent
        kept at the endpoint to reject before enqueue. Migration must
        not drop it (would cause paper-mode-violating jobs to enqueue,
        produce 'failed' job_runs rows, and pollute observability)."""
        self.assertIn(
            '_check_readiness_hardening_gates', self.handler_block,
            "Paper-mode gate must remain at the endpoint per design — "
            "rejects before enqueue, avoids noisy job_runs rows",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Handler exists and is auto-discoverable
# ─────────────────────────────────────────────────────────────────────


class TestHandlerScaffolded(unittest.TestCase):
    """The new handler exists, follows the registry contract, and is
    auto-discoverable by `packages/quantum/jobs/registry.discover_handlers`."""

    def test_handler_file_exists(self):
        self.assertTrue(
            HANDLER_PATH.exists(),
            f"Handler file must exist at {HANDLER_PATH}",
        )

    def test_handler_defines_job_name_constant(self):
        src = _read(HANDLER_PATH)
        self.assertIn(
            'JOB_NAME = "validation_init_window"', src,
            "Handler must declare JOB_NAME='validation_init_window' for "
            "discover_handlers() to register it",
        )

    def test_handler_defines_run_function_with_payload(self):
        """Registry contract: def run(payload, ctx=None) -> dict."""
        src = _read(HANDLER_PATH)
        self.assertRegex(
            src,
            r'def run\(payload[^)]*\)',
            "Handler must define run(payload, ...) per registry contract",
        )

    def test_handler_calls_service(self):
        """The work that moved from the endpoint must now live in the
        handler — verify the service call is present."""
        src = _read(HANDLER_PATH)
        self.assertIn('ensure_forward_window_initialized', src)

    def test_handler_is_thin_wrapper(self):
        """Per scope: handler should NOT replicate functionality the
        sync endpoint had (custom logging, alerts, multi-user fan-out).
        Sanity check by file size — handler should be small."""
        src_lines = _read(HANDLER_PATH).count("\n")
        self.assertLess(
            src_lines, 100,
            f"Handler should be a thin wrapper (<100 lines); got "
            f"{src_lines}. Audit was 'pure migration, no behavior "
            f"changes' — extra logic suggests scope drift.",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 3 — Auto-discovery sanity
# ─────────────────────────────────────────────────────────────────────


class TestHandlerAutoDiscovered(unittest.TestCase):
    """The registry's auto-discovery picks up the new handler.

    discover_handlers() walks packages/quantum/jobs/handlers/ for any
    module exporting JOB_NAME + run(payload, ...). If the new handler
    file passes both checks, it gets registered.
    """

    def test_registry_discovers_validation_init_window(self):
        try:
            from packages.quantum.jobs.registry import discover_handlers
        except ImportError as e:
            self.skipTest(f"jobs.registry not importable: {e}")
        handlers = discover_handlers()
        self.assertIn(
            "validation_init_window", handlers,
            "discover_handlers() must register the new handler. If it's "
            "missing, the file's JOB_NAME constant or run() signature "
            "violates the registry contract.",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 4 — Backlog ship line present
# ─────────────────────────────────────────────────────────────────────


class TestMigrationDocumented(unittest.TestCase):
    def test_backlog_references_pr3(self):
        backlog = (
            Path(__file__).parent.parent.parent.parent / "docs" / "backlog.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'PR-3', backlog,
            "Backlog must include a PR-3 ship line under #71",
        )


if __name__ == "__main__":
    unittest.main()
