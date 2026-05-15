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


class TestIvHistoricalBackfillUsesCanonicalEnqueue(unittest.TestCase):
    """Sibling regression guard for the α PR #935 +
    2026-05-14 plumbing PR pair. The handler shipped in #935 but
    the operator-trigger plumbing (HTTP route + run_signed_task
    entry) was missing — surfaced during Phase 1 trigger
    verification. This test defends both the canonical
    ``enqueue_job_run`` wiring AND the underscored ``job_name``
    contract, mirroring the iv_daily_refresh guards above.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = INTERNAL_TASKS_PATH.read_text(encoding="utf-8")

    def _function_body(self, fn_signature_prefix: str) -> str:
        anchor = self.src.find(fn_signature_prefix)
        self.assertGreater(
            anchor, 0,
            f"{fn_signature_prefix} missing from internal_tasks.py",
        )
        end_match = re.search(
            r"\n(@router\.post|async def |def )",
            self.src[anchor + 50:],
        )
        body_end = (
            anchor + 50 + end_match.start()
            if end_match else len(self.src)
        )
        return self.src[anchor:body_end]

    def test_route_uses_enqueue_job_run(self):
        body = self._function_body("async def iv_historical_backfill_task(")
        self.assertIn(
            "enqueue_job_run(", body,
            "iv_historical_backfill_task must use the canonical "
            "enqueue_job_run path (DB + RQ push). Same class as the "
            "iv_daily_refresh PR-A regression (2026-05-08).",
        )
        self.assertNotIn(
            "enqueue_idempotent(", body,
            "iv_historical_backfill_task uses the legacy DB-only "
            "enqueue path. Migrate to enqueue_job_run.",
        )

    def test_route_uses_underscored_job_name(self):
        body = self._function_body("async def iv_historical_backfill_task(")
        self.assertIn(
            'job_name="iv_historical_backfill"', body,
            "iv_historical_backfill_task must pass the underscored "
            "job_name to enqueue_job_run, matching the handler's "
            "JOB_NAME constant. Hyphenated job_names don't resolve "
            "via discover_handlers().",
        )

    def test_handler_job_name_underscored(self):
        handler_path = (
            INTERNAL_TASKS_PATH.parent / "jobs" / "handlers"
            / "iv_historical_backfill.py"
        )
        handler_src = handler_path.read_text(encoding="utf-8")
        self.assertIn(
            'JOB_NAME = "iv_historical_backfill"', handler_src,
        )

    def test_route_path_resolves_via_router(self):
        """The route must register at /internal/tasks/iv/historical-backfill
        — same prefix-handling pattern as iv_daily_refresh. Catches
        the same class of bug that produced PR-A's 404 on first fire.
        """
        from packages.quantum import internal_tasks
        registered_paths = {
            getattr(r, "path", None) for r in internal_tasks.router.routes
        }
        self.assertIn(
            "/internal/tasks/iv/historical-backfill",
            registered_paths,
            "iv_historical_backfill HTTP route not registered. Without "
            "this, run_signed_task.py iv_historical_backfill would 404 — "
            "the exact gap that surfaced during 2026-05-14 Phase 1 "
            "trigger verification.",
        )


# ─────────────────────────────────────────────────────────────────────
# #71 Tier 3 (PR closing the sweep arc) — codebase-wide CI gate
# ─────────────────────────────────────────────────────────────────────


# packages/quantum/ root (sibling of `tests/`).
_QUANTUM_ROOT = INTERNAL_TASKS_PATH.parent

# Subdirectories that are NOT production code. Walk skips them entirely.
# - `scripts/` is operator-facing tooling (smoke scripts, CLI entry
#   points). The remaining legacy importer
#   `rq_smoke_morning_brief.py` lives here intentionally; future
#   cleanup tracked separately (#118).
# - `tests/` is the test suite itself.
# - `__pycache__/` is bytecode cache.
# - `venv/` is a local virtualenv that may exist on operator machines
#   (out of git but glob-walked anyway).
_NON_PRODUCTION_DIRS = {"scripts", "tests", "__pycache__", "venv", ".venv"}

# Forbidden import. Matches both single and multi-space variants and
# tolerates trailing comments.
_LEGACY_IMPORT_RE = re.compile(
    r"from\s+packages\.quantum\.jobs\.enqueue\s+import\s+enqueue_idempotent",
)


class TestNoProductionCodeImportsLegacyEnqueue(unittest.TestCase):
    """Codebase-wide CI gate: production code must NOT import
    ``enqueue_idempotent`` from the legacy DB-only path
    ``packages.quantum.jobs.enqueue``. Canonical path is
    ``packages.quantum.public_tasks.enqueue_job_run`` (DB + RQ push
    + pause/go-live gates).

    History:
      - PR #901 (#115 PR-A Layer 2): added the iv_daily_refresh-
        scoped guard above. Other internal_tasks endpoints still
        used the legacy path at that time, so the assertion was
        deliberately narrow.
      - PR #910 (#71 Tier 2): deleted the last 4 production-code
        callers (the dormant duplicate endpoints
        /morning-brief, /midday-scan, /weekly-report,
        /universe/sync at /internal/tasks/*) along with the
        cascading legacy imports.
      - This PR (#71 Tier 3): widens the guard codebase-wide for
        production code. Closes the #71 sweep arc.

    Anything new that matches the forbidden import pattern fails CI
    here, with a message pointing to the canonical migration target.
    """

    def test_no_production_module_imports_legacy_enqueue(self):
        violations = []

        for py_file in _QUANTUM_ROOT.rglob("*.py"):
            relative_parts = py_file.relative_to(_QUANTUM_ROOT).parts
            if any(part in _NON_PRODUCTION_DIRS for part in relative_parts):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            if _LEGACY_IMPORT_RE.search(content):
                violations.append(
                    str(py_file.relative_to(_QUANTUM_ROOT)).replace("\\", "/")
                )

        self.assertEqual(
            violations, [],
            "Production code imports legacy enqueue_idempotent from "
            "`packages.quantum.jobs.enqueue` in the following file(s):\n  "
            + "\n  ".join(violations) + "\n\n"
            "Migrate to the canonical path:\n"
            "  `from packages.quantum.public_tasks import enqueue_job_run`\n\n"
            "The legacy path writes a `status='queued'` row to job_runs "
            "but never pushes to RQ — the worker never picks it up. See "
            "PR #901 for the iv_daily_refresh case study and PR #910 for "
            "the Tier 2 sweep that deleted the last legacy callers.",
        )

    def test_excluded_directories_are_truly_non_production(self):
        """Defense against future drift: assert each excluded directory
        either (a) doesn't exist or (b) contains only the file shapes we
        expect (scripts/, tests/, etc.). Catches the case where a future
        contributor mass-renames a production directory to something the
        exclusion filter incidentally matches.
        """
        for non_prod in _NON_PRODUCTION_DIRS:
            candidate = _QUANTUM_ROOT / non_prod
            if not candidate.exists():
                continue
            self.assertTrue(
                candidate.is_dir(),
                f"Non-production exclusion `{non_prod}` exists at "
                f"{candidate} but is not a directory — exclusion filter "
                f"may be matching unintended files.",
            )


if __name__ == "__main__":
    unittest.main()
