"""Tests for #98 — loud alert at submit_and_track needs_manual_review
write site.

Catches Alpaca-rejected orders before they create silent ghost positions.

Background: 2026-05-01 16:45 UTC, BAC close was rejected by Alpaca 3x
with "insufficient options buying power" (required $296, available
$203.88). submit_and_track marked the order needs_manual_review and
returned a dict — correctly per safety design — but no alert fired
for 5+ hours. The H5a alert at paper_exit_evaluator.py:1226 only
fires for RAISED exceptions; submit_and_track returns a dict on this
path. This PR closes the coverage gap by alerting at the write site,
which catches all callers regardless of how they handle the return.
"""

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).parent.parent
HANDLER_PATH = REPO_ROOT / "brokers" / "alpaca_order_handler.py"


def _read_handler() -> str:
    return HANDLER_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestSourceLevelAlertPresent(unittest.TestCase):
    """Source-level: alert() call exists at the needs_manual_review
    write site with critical severity + operator_action_required."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_handler()

    def test_alert_call_present(self):
        self.assertIn(
            "paper_order_marked_needs_manual_review", self.src,
            "Alert type 'paper_order_marked_needs_manual_review' must exist "
            "in alpaca_order_handler.py",
        )
        ast.parse(self.src)

    def test_alert_severity_critical(self):
        idx = self.src.find("paper_order_marked_needs_manual_review")
        self.assertGreater(idx, 0)
        block = self.src[max(0, idx - 200):idx + 1500]
        self.assertTrue(
            'severity="critical"' in block or "severity='critical'" in block,
            "Alert must be severity='critical' — same convention as H5a "
            "site 9 (paper_exit_alpaca_submit_fallback_to_internal) and "
            "H5b site 236 (paper_autopilot_circuit_breaker_failed).",
        )

    def test_operator_action_required_present(self):
        idx = self.src.find("paper_order_marked_needs_manual_review")
        block = self.src[max(0, idx - 200):idx + 2000]
        self.assertIn(
            "operator_action_required", block,
            "Critical alerts must include operator_action_required field "
            "per H5 convention.",
        )
        # Spec mandates the 4-step recovery procedure
        self.assertIn(
            "manually close", block,
            "operator_action_required must instruct the manual-close path",
        )

    def test_consequence_field_explains_divergence(self):
        idx = self.src.find("paper_order_marked_needs_manual_review")
        block = self.src[max(0, idx - 200):idx + 2000]
        self.assertIn("consequence", block)
        self.assertTrue(
            "diverge" in block.lower() or "broker may still hold" in block.lower(),
            "consequence must explain the broker-vs-DB divergence so "
            "operators understand why this is critical.",
        )

    def test_alert_emit_failure_does_not_break_marker_write(self):
        """The alert call must be wrapped in try/except so that
        alert-path failures don't break the needs_manual_review marker
        write or the function's return contract."""
        idx = self.src.find("paper_order_marked_needs_manual_review")
        block = self.src[max(0, idx - 500):idx + 2000]
        self.assertIn("try:", block)
        self.assertIn("except Exception", block)

    def test_marker_write_preserved(self):
        """The original UPDATE that writes status='needs_manual_review'
        is unchanged — alert is purely additive observability."""
        self.assertIn('"status": "needs_manual_review"', self.src)
        self.assertIn('"broker_status": "needs_manual_review"', self.src)

    def test_return_contract_unchanged(self):
        """Function still returns the same dict shape — callers depending
        on `result['status'] == 'needs_manual_review'` keep working."""
        self.assertIn(
            'return {"status": "needs_manual_review"',
            self.src,
        )


class TestModuleSyntax(unittest.TestCase):
    def test_handler_parses(self):
        try:
            ast.parse(_read_handler())
        except SyntaxError as e:
            self.fail(f"alpaca_order_handler.py has a syntax error: {e}")


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral with mocks
# ─────────────────────────────────────────────────────────────────────


def _make_supabase_mock():
    """Build a chain mock that records all .table().update().eq().execute() calls."""
    mock = MagicMock()
    chain = MagicMock()
    for method in ("select", "eq", "in_", "lt", "neq", "single", "limit", "order"):
        getattr(chain, method).return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    mock.table.return_value = chain
    return mock


def _make_alpaca_mock(*, raise_with_message: str = "broker error"):
    """Build an alpaca client mock that always raises on submit_option_order."""
    alpaca = MagicMock()
    alpaca.paper = False
    alpaca.cancel_open_orders_for_symbols.return_value = []
    alpaca.submit_option_order.side_effect = Exception(raise_with_message)
    return alpaca


def _make_close_order(order_id: str = "test-order-1"):
    """Build a minimal close-order dict matching production shape."""
    return {
        "id": order_id,
        "position_id": "pos-123",  # close order
        "order_json": {
            "limit_price": 1.50,
            "side": "buy",
            "legs": [
                {"symbol": "BAC260605C00051000", "side": "buy", "ratio_qty": 1},
                {"symbol": "BAC260605C00056000", "side": "sell", "ratio_qty": 1},
            ],
        },
    }


class TestBehavioralAlertFires(unittest.TestCase):
    """Behavioral: when submit_and_track exhausts retries, the critical
    alert fires with the expected metadata."""

    def test_alert_fires_on_max_attempts_exhausted(self):
        from packages.quantum.brokers import alpaca_order_handler

        with patch(
            "packages.quantum.observability.alerts.alert"
        ) as mock_alert, patch(
            "packages.quantum.observability.alerts._get_admin_supabase"
        ) as mock_admin_sup, patch.object(
            alpaca_order_handler, "time"
        ) as mock_time:
            mock_admin_sup.return_value = MagicMock()
            # Avoid real sleeps in retry loop
            mock_time.monotonic.return_value = 0.0
            mock_time.sleep.return_value = None

            alpaca = _make_alpaca_mock(
                raise_with_message="insufficient options buying power",
            )
            supabase = _make_supabase_mock()
            order = _make_close_order(order_id="bac-close-test")

            result = alpaca_order_handler.submit_and_track(
                alpaca=alpaca,
                supabase=supabase,
                order=order,
                user_id="test-user",
            )

            # Return contract preserved
            self.assertEqual(result["status"], "needs_manual_review")
            self.assertEqual(result["attempts"], 3)

            # Alert was emitted once
            self.assertEqual(
                mock_alert.call_count, 1,
                "alert() must be called exactly once when "
                "submit_and_track marks needs_manual_review.",
            )

            kwargs = mock_alert.call_args.kwargs
            self.assertEqual(
                kwargs.get("alert_type"),
                "paper_order_marked_needs_manual_review",
            )
            self.assertEqual(kwargs.get("severity"), "critical")
            self.assertEqual(kwargs.get("user_id"), "test-user")

            metadata = kwargs.get("metadata", {})
            self.assertEqual(metadata.get("attempts"), 3)
            self.assertEqual(metadata.get("order_id"), "bac-close-test")
            self.assertIn("operator_action_required", metadata)
            self.assertIn("consequence", metadata)
            self.assertIn(
                "insufficient", metadata.get("last_error", "").lower(),
            )
            # Close-order context preserved for operator triage
            self.assertTrue(metadata.get("is_close_order"))

    def test_alert_failure_does_not_break_marker_or_return(self):
        """If the alert helper raises, the marker write must still
        complete and the function must still return its normal dict."""
        from packages.quantum.brokers import alpaca_order_handler

        with patch(
            "packages.quantum.observability.alerts.alert",
            side_effect=Exception("alert system down"),
        ), patch(
            "packages.quantum.observability.alerts._get_admin_supabase"
        ) as mock_admin_sup, patch.object(
            alpaca_order_handler, "time"
        ) as mock_time:
            mock_admin_sup.return_value = MagicMock()
            mock_time.monotonic.return_value = 0.0
            mock_time.sleep.return_value = None

            alpaca = _make_alpaca_mock(raise_with_message="broker down")
            supabase = _make_supabase_mock()
            order = _make_close_order(order_id="alert-fail-test")

            # Must not raise
            result = alpaca_order_handler.submit_and_track(
                alpaca=alpaca,
                supabase=supabase,
                order=order,
                user_id="test-user",
            )
            self.assertEqual(result["status"], "needs_manual_review")

            # The marker UPDATE must have been called
            update_calls = [
                call_args
                for call_args in supabase.table.return_value.update.call_args_list
                if call_args.args
                and call_args.args[0].get("status") == "needs_manual_review"
            ]
            self.assertGreaterEqual(
                len(update_calls), 1,
                "needs_manual_review marker UPDATE must complete even when "
                "the alert helper itself fails.",
            )


if __name__ == "__main__":
    unittest.main()
