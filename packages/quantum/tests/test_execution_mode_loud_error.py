"""Phase 2 (#A4 sequence) — Loud-error alert at execution_router for
unknown EXECUTION_MODE values.

SAFETY-CRITICAL site missed in H1-H5 doctrine sweep; corrected after
the 2026-04-30 BAC misroute incident. EXECUTION_MODE='micro_live'
(phase name, not a valid mode value) silently routed to internal_paper
for 5 days. The alert added at execution_router.py:get_execution_mode
ValueError branch catches this class of typo / documentation drift on
the first cycle that exercises it.
"""

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).parent.parent


def _read_router() -> str:
    return (REPO_ROOT / "brokers" / "execution_router.py").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestSourceLevelAlertPresent(unittest.TestCase):
    """Source-level: alert() call exists in get_execution_mode
    ValueError branch with critical severity + operator_action_required."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_router()

    def test_alert_call_in_get_execution_mode(self):
        self.assertIn("execution_mode_invalid_env_value", self.src)
        ast.parse(self.src)

    def test_alert_severity_critical(self):
        idx = self.src.find("execution_mode_invalid_env_value")
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 1500]
        self.assertTrue(
            'severity="critical"' in block or "severity='critical'" in block,
            "Alert must be severity='critical' — same convention as "
            "H5a site 9 and H5b site 236 (silent fallbacks that "
            "require operator intervention).",
        )

    def test_operator_action_required_present(self):
        idx = self.src.find("execution_mode_invalid_env_value")
        block = self.src[idx:idx + 1500]
        self.assertIn(
            "operator_action_required", block,
            "Critical alerts must include operator_action_required "
            "field per H5 convention.",
        )
        self.assertIn(
            "LIVE_ENABLED", block,
            "operator_action_required must mention LIVE_ENABLED "
            "(the second-stage safety check that catches a different "
            "class of misconfiguration than this alert).",
        )

    def test_consequence_field_explains_silent_degradation(self):
        idx = self.src.find("execution_mode_invalid_env_value")
        block = self.src[idx:idx + 1500]
        self.assertIn("consequence", block)
        self.assertTrue(
            "silently degraded" in block or "silent" in block.lower(),
            "consequence must explain the silent-degradation impact "
            "so operators understand why this is critical.",
        )

    def test_alert_emit_failure_does_not_break_fallback(self):
        """The alert call must be wrapped in try/except so that
        alert-path failures don't break the routing fallback. The
        genuine safety path (return INTERNAL_PAPER) must remain
        intact regardless of observability state."""
        idx = self.src.find("execution_mode_invalid_env_value")
        # Look in the surrounding window for try/except around the alert
        block = self.src[max(0, idx - 200):idx + 1500]
        self.assertIn("try:", block)
        self.assertIn("except Exception", block)

    def test_logger_warning_preserved(self):
        """Existing logger.warning is preserved as last-resort visibility
        even when the alert path itself fails."""
        self.assertIn(
            'logger.warning(f"[EXEC_ROUTER] Unknown EXECUTION_MODE',
            self.src,
        )

    def test_returns_internal_paper_unchanged(self):
        """The fallback return value is unchanged — alert is purely
        additive observability."""
        self.assertIn("return ExecutionMode.INTERNAL_PAPER", self.src)


class TestModuleSyntax(unittest.TestCase):
    def test_execution_router_parses(self):
        try:
            ast.parse(_read_router())
        except SyntaxError as e:
            self.fail(f"execution_router.py has a syntax error: {e}")


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral with mocks
# ─────────────────────────────────────────────────────────────────────


class TestBehavioralAlertFires(unittest.TestCase):
    """Behavioral: invoking get_execution_mode with invalid env value
    triggers the alert path. Patches at the import-target location so
    the in-function `from ... import alert` picks up the mock."""

    def test_alert_called_for_unknown_mode(self):
        with patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase") as mock_get:
            mock_get.return_value = MagicMock()

            with patch.dict("os.environ", {"EXECUTION_MODE": "micro_live"}):
                from packages.quantum.brokers.execution_router import (
                    get_execution_mode, ExecutionMode,
                )
                result = get_execution_mode()

            # Fallback behavior preserved
            self.assertEqual(result, ExecutionMode.INTERNAL_PAPER)

            # Alert was emitted
            self.assertEqual(
                mock_alert.call_count, 1,
                "alert() must be called exactly once per invalid mode "
                "invocation.",
            )

            # Inspect call kwargs
            call_kwargs = mock_alert.call_args.kwargs
            self.assertEqual(
                call_kwargs.get("alert_type"), "execution_mode_invalid_env_value",
            )
            self.assertEqual(call_kwargs.get("severity"), "critical")

            metadata = call_kwargs.get("metadata", {})
            self.assertEqual(metadata.get("raw_value"), "micro_live")
            self.assertIn("alpaca_live", metadata.get("valid_values", []))
            self.assertIn("operator_action_required", metadata)

    def test_valid_mode_no_alert(self):
        """Valid EXECUTION_MODE values must not trigger the alert path."""
        with patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase") as mock_get:
            mock_get.return_value = MagicMock()

            # Use alpaca_paper since alpaca_live needs LIVE_ENABLED
            with patch.dict("os.environ", {"EXECUTION_MODE": "alpaca_paper"}):
                from packages.quantum.brokers.execution_router import (
                    get_execution_mode, ExecutionMode,
                )
                result = get_execution_mode()

            self.assertEqual(result, ExecutionMode.ALPACA_PAPER)
            self.assertEqual(
                mock_alert.call_count, 0,
                "Valid mode must not emit the unknown-mode alert.",
            )

    def test_alert_failure_does_not_break_fallback(self):
        """If the alert path itself fails, get_execution_mode must
        still return INTERNAL_PAPER (the fallback). Routing decision
        must not depend on alert-emit success."""
        with patch(
            "packages.quantum.observability.alerts.alert",
            side_effect=Exception("alert system down"),
        ), patch(
            "packages.quantum.observability.alerts._get_admin_supabase"
        ) as mock_get:
            mock_get.return_value = MagicMock()

            with patch.dict("os.environ", {"EXECUTION_MODE": "micro_live"}):
                from packages.quantum.brokers.execution_router import (
                    get_execution_mode, ExecutionMode,
                )
                # Must not raise — alert failure swallowed, fallback works
                result = get_execution_mode()

            self.assertEqual(result, ExecutionMode.INTERNAL_PAPER)


if __name__ == "__main__":
    unittest.main()
