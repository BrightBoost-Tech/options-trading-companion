"""Tests for #115 PR-A Layer 5 fix.

Pre-fix the iv_daily_refresh and daily_progression_eval endpoints
had no body parameter in their FastAPI signatures, so the CLI's
``payload={"force_rerun": true}`` was silently discarded before
reaching ``enqueue_job_run``. Same UTC day re-fires hit terminal-
state dedup and never executed. Discovered 2026-05-09 during
PR-A chain validation after Layer 3+4 fixes shipped.

Source-level structural assertions only — full FastAPI app context
is heavy and not needed to validate the contract: the endpoint
must accept ``Body``, extract ``force_rerun``, and pass it to
``enqueue_job_run``.
"""

import re
import unittest
from pathlib import Path


INTERNAL_TASKS = (
    Path(__file__).parent.parent / "internal_tasks.py"
)


class TestEndpointsAcceptBodyAndForwardForceRerun(unittest.TestCase):

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

    def test_iv_daily_refresh_accepts_body_param(self):
        body = self._function_body("iv_daily_refresh_task")
        self.assertIn("body: Optional[Dict] = Body(", body)

    def test_iv_daily_refresh_forwards_force_rerun(self):
        body = self._function_body("iv_daily_refresh_task")
        self.assertIn('(body or {}).get("force_rerun"', body)
        self.assertIn("force_rerun=force_rerun", body)

    def test_daily_progression_eval_accepts_body_param(self):
        body = self._function_body("daily_progression_eval_task")
        self.assertIn("body: Optional[Dict] = Body(", body)

    def test_daily_progression_eval_forwards_force_rerun(self):
        body = self._function_body("daily_progression_eval_task")
        self.assertIn('(body or {}).get("force_rerun"', body)
        self.assertIn("force_rerun=force_rerun", body)

    def test_force_rerun_propagated_to_payload_for_logging(self):
        """When force_rerun is True, the kwarg is forwarded AND a
        marker is included in the payload so the recorded job_run
        result preserves the trigger context. Both endpoints follow
        the same pattern."""
        for fn_name in (
            "iv_daily_refresh_task",
            "daily_progression_eval_task",
        ):
            body = self._function_body(fn_name)
            self.assertIn(
                '({"force_rerun": True} if force_rerun else {})', body,
                f"{fn_name} should mark force_rerun in payload for audit",
            )

    def test_default_body_is_none_safe(self):
        """When the body is omitted entirely (scheduled fire path),
        endpoints must default to force_rerun=False without crashing.
        ``Body(default=None)`` + ``(body or {}).get(...)`` covers
        both no-body and explicit-empty-body cases.
        """
        for fn_name in (
            "iv_daily_refresh_task",
            "daily_progression_eval_task",
        ):
            body = self._function_body(fn_name)
            self.assertIn("Body(default=None)", body)
            self.assertIn("(body or {}).get", body)


if __name__ == "__main__":
    unittest.main()
