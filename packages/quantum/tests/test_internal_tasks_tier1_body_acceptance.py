"""Tests for #71 Tier 1 fix — extend body acceptance for force_rerun
on the 3 CLI-exposed internal_tasks endpoints with body-dropping or
partial-body signatures.

Same shape as PR #905's test_internal_tasks_force_rerun_body.py.
Pre-fix the endpoints either declared no request body parameter
(``alpaca_order_sync_task`` — full drop) or accepted only specific
fields via ``Body(..., embed=True)`` (``calibration_update_task``,
``walk_forward_autotune_task`` — partial drop), so the CLI's
``payload={"force_rerun": true}`` was silently discarded by FastAPI
before reaching ``enqueue_job_run``. Re-fires within the same
idempotency window hit terminal-state dedup and never executed.

The 3 endpoints are CLI-exposed via ``scripts/run_signed_task.py``,
which sets ``payload["force_rerun"] = True`` whenever ``--force-rerun``
or ``--force`` is passed (lines 770-775).

Source-level structural assertions only — full FastAPI app context
is heavy and not needed to validate the contract: each endpoint must
accept ``Body``, extract ``force_rerun``, and pass it to
``enqueue_job_run``. Defaults for previously-named primary fields
(window_days=30, lookback_days=60, cohort_name=None) must be
preserved so SCHEDULES + body-less callers keep working.
"""

import re
import unittest
from pathlib import Path


INTERNAL_TASKS = (
    Path(__file__).parent.parent / "internal_tasks.py"
)


TIER1_ENDPOINTS = (
    "alpaca_order_sync_task",
    "calibration_update_task",
    "walk_forward_autotune_task",
)


class TestTier1EndpointsAcceptBodyAndForwardForceRerun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = INTERNAL_TASKS.read_text(encoding="utf-8")

    def _function_body(self, fn_name: str) -> str:
        """Extract the source range from `async def <fn_name>(` to
        the next `@router.post` (next endpoint) — gives us a window
        scoped to that endpoint's signature + body."""
        anchor = self.src.find(f"async def {fn_name}(")
        self.assertGreater(
            anchor, 0, f"endpoint {fn_name} not found in internal_tasks.py",
        )
        end_match = re.search(
            r"\n@router\.post\(", self.src[anchor + 50:]
        )
        end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        return self.src[anchor:end]

    # ── Per-endpoint body shape ──────────────────────────────────────

    def test_all_three_accept_body_param(self):
        for fn in TIER1_ENDPOINTS:
            with self.subTest(fn=fn):
                body = self._function_body(fn)
                self.assertIn(
                    "body: Optional[Dict] = Body(", body,
                    f"{fn} must accept Optional[Dict] body to receive "
                    f"force_rerun and other CLI-sent fields",
                )

    def test_all_three_default_body_to_none(self):
        for fn in TIER1_ENDPOINTS:
            with self.subTest(fn=fn):
                body = self._function_body(fn)
                self.assertIn("Body(default=None)", body)
                self.assertIn("(payload_in.get" if fn != "alpaca_order_sync_task"
                              else "(body or {})", body)

    def test_all_three_extract_and_forward_force_rerun(self):
        for fn in TIER1_ENDPOINTS:
            with self.subTest(fn=fn):
                body = self._function_body(fn)
                self.assertIn('"force_rerun"', body)
                self.assertIn("force_rerun=force_rerun", body)

    def test_all_three_propagate_force_rerun_to_payload_for_audit(self):
        """When force_rerun is True, the kwarg is forwarded AND a
        marker is included in the payload so the recorded job_run
        result preserves the trigger context. Matches PR #905
        convention."""
        for fn in TIER1_ENDPOINTS:
            with self.subTest(fn=fn):
                body = self._function_body(fn)
                self.assertIn(
                    '({"force_rerun": True} if force_rerun else {})', body,
                    f"{fn} should mark force_rerun in payload for audit",
                )

    # ── Backward-compat: defaults preserved ──────────────────────────

    def test_calibration_update_preserves_window_days_default(self):
        # SCHEDULES + body-less callers send no window_days. Default
        # must remain 30 so the migration is invisible to them.
        body = self._function_body("calibration_update_task")
        self.assertIn('payload_in.get("window_days", 30)', body)

    def test_walk_forward_autotune_preserves_lookback_default(self):
        body = self._function_body("walk_forward_autotune_task")
        self.assertIn('payload_in.get("lookback_days", 60)', body)

    def test_walk_forward_autotune_preserves_cohort_name_default_none(self):
        body = self._function_body("walk_forward_autotune_task")
        # cohort_name default was None pre-fix; must remain None when
        # caller omits the field.
        self.assertIn('cohort_name = payload_in.get("cohort_name")', body)

    # ── Removal of legacy embed=True signatures ──────────────────────

    def test_calibration_update_no_longer_uses_embed_for_window_days(self):
        """The pre-fix shape ``window_days: int = Body(30, embed=True)``
        silently dropped force_rerun. Migrating to a single dict body
        means this declaration must be gone."""
        body = self._function_body("calibration_update_task")
        self.assertNotIn(
            "window_days: int = Body(", body,
            "calibration_update_task must use single dict body, not "
            "embed=True per-field — that's the bug class being fixed.",
        )

    def test_walk_forward_autotune_no_longer_uses_embed_for_lookback(self):
        body = self._function_body("walk_forward_autotune_task")
        self.assertNotIn(
            "lookback_days: int = Body(", body,
            "walk_forward_autotune_task must use single dict body, "
            "not embed=True per-field — that's the bug class being fixed.",
        )

    def test_walk_forward_autotune_no_longer_uses_embed_for_cohort(self):
        body = self._function_body("walk_forward_autotune_task")
        self.assertNotIn(
            "cohort_name: str = Body(", body,
        )

    # ── Sanity: alpaca_order_sync gets the full body-add treatment ──

    def test_alpaca_order_sync_force_rerun_round_trip_pattern(self):
        """alpaca_order_sync_task is the closest analog to PR #905's
        iv_daily_refresh fix — full body-add, no pre-existing body
        param. Verify it follows the exact same shape so future
        readers find a single convention."""
        body = self._function_body("alpaca_order_sync_task")
        # The (body or {}).get pattern matches iv_daily_refresh /
        # daily_progression_eval verbatim.
        self.assertIn('(body or {}).get("force_rerun", False)', body)
        self.assertIn("force_rerun=force_rerun", body)


if __name__ == "__main__":
    unittest.main()
