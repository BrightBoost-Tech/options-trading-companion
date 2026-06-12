"""'Selected then vanished' must be impossible (2026-06-12, job ac2f0c08).

The 16:00Z suggestions_open run selected MARA (score=86.6) and then died
mid-pipeline on an UnboundLocalError out of run_midday_cycle. The
handler's per-user `except Exception` swallowed the death into a
notes[] entry; job_runs recorded status 'succeeded'; no alert fired; the
16:06Z paper_auto_execute found 0 pending suggestions and nobody was
told why. These tests pin the loud-death contract:

1. A cycle death fires a CRITICAL `suggestions_open_cycle_died`
   risk_alert with the error class and a traceback tail, and prints the
   traceback to the job log.
2. Alert-dispatch failure must not mask the original error (the run
   still completes with failed=1).
3. A healthy cycle fires no death alert.
4. Source pin: the orchestrator sizing loop's `price <= 0` skip — the
   one previously-silent `continue` — logs the skip reason.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.quantum.jobs.handlers import suggestions_open

_UID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"


async def _dying_cycle(client, uid):
    raise RuntimeError("cannot access local variable '_x' (simulated)")


async def _healthy_cycle(client, uid):
    return {"skipped": False, "reason": "ok", "counts": {}}


def _run_handler():
    return suggestions_open.run({"user_id": _UID})


class TestCycleDeathIsLoud(unittest.TestCase):
    def _patched(self, cycle, alert_mock):
        return [
            patch.object(suggestions_open, "is_market_day",
                         return_value=(True, "open")),
            patch.object(suggestions_open, "get_admin_client",
                         return_value=MagicMock()),
            patch.object(suggestions_open, "ensure_default_strategy_exists"),
            patch.object(suggestions_open, "load_strategy_config",
                         return_value={"version": 1}),
            patch.object(suggestions_open, "run_midday_cycle", cycle),
            patch("packages.quantum.observability.alerts.alert", alert_mock),
            # The staleness gate blocks (fast-path ok=True) in any env
            # without market-data API keys — these tests are about the
            # per-user death path, so pin the gate open.
            patch(
                "packages.quantum.risk.staleness_gate.check_staleness_gate",
                return_value=SimpleNamespace(
                    blocked=False, reason="", age_seconds=0.0,
                    stale_symbols=[],
                ),
            ),
        ]

    def _run_with(self, cycle, alert_mock):
        patches = self._patched(cycle, alert_mock)
        for p in patches:
            p.start()
        try:
            return _run_handler()
        finally:
            for p in patches:
                p.stop()

    def test_cycle_death_fires_critical_alert_with_traceback(self):
        alert_mock = MagicMock()
        result = self._run_with(_dying_cycle, alert_mock)

        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"]["failed"], 1)
        # The note (legacy surface) is retained...
        self.assertTrue(
            any("Failed for user" in n for n in result["notes"])
        )
        # ...and the alert (new surface) fired, critical, with class +
        # traceback + downstream consequence.
        alert_mock.assert_called_once()
        kwargs = alert_mock.call_args.kwargs
        self.assertEqual(kwargs["alert_type"], "suggestions_open_cycle_died")
        self.assertEqual(kwargs["severity"], "critical")
        self.assertEqual(kwargs["user_id"], _UID)
        self.assertEqual(kwargs["metadata"]["error_class"], "RuntimeError")
        self.assertIn("RuntimeError", kwargs["metadata"]["traceback_tail"])
        self.assertIn(
            "paper_auto_execute", kwargs["metadata"]["consequence"]
        )

    def test_alert_failure_does_not_mask_cycle_death(self):
        alert_mock = MagicMock(side_effect=RuntimeError("alerts down"))
        result = self._run_with(_dying_cycle, alert_mock)
        # The run still completes and still reports the failure.
        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"]["failed"], 1)

    def test_healthy_cycle_fires_no_death_alert(self):
        alert_mock = MagicMock()
        result = self._run_with(_healthy_cycle, alert_mock)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["failed"], 0)
        alert_mock.assert_not_called()


class TestSizingLoopHasNoSilentSkip(unittest.TestCase):
    """Source pin on the orchestrator: the `price <= 0` continue — the
    only previously-silent candidate skip in the sizing loop — must log
    the skip reason before continuing."""

    def test_unpriceable_candidate_skip_is_logged(self):
        src = (
            Path(__file__).parent.parent
            / "services" / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")
        anchor = src.find("if price <= 0:")
        self.assertNotEqual(anchor, -1)
        # Window ends at the continue STATEMENT (own line at block
        # indent), not the word "continue" in a comment.
        window = src[anchor:src.find("\n            continue", anchor)]
        self.assertIn(
            "print(", window,
            "the price<=0 skip in run_midday_cycle's sizing loop must "
            "log why the candidate was dropped — a selected candidate "
            "must never vanish silently (2026-06-12 doctrine)",
        )
        self.assertIn("Skipped", window)


if __name__ == "__main__":
    unittest.main()
