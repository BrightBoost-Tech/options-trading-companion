"""
Tests for the external risk-alert egress wired into
``packages.quantum.observability.alerts.alert``.

Context (loss-protection hardening, 2026-06-29): every risk event was
DB-only (a ``risk_alerts`` row). For a TIGHT allowlist of critical/high
RISK categories (brake fire / force_close, per-symbol loss, job dead-letter,
exit_protection_disarmed) the alert ALSO egresses through the EXISTING
``ops_health_service.send_ops_alert_v2`` webhook sender so an unattended
loss-protection event reaches the operator off-platform.

Invariants under test:
    1. A force_close (brake-fire class) risk event through alert() with
       OPS_ALERT_WEBHOOK_URL set egresses — the sender is CALLED (load-bearing).
    2. URL UNSET → SAFE: no crash, DB row still written, sender no-ops /
       suppressed, no real network egress.
    3. A warn-level / non-risk alert → NO egress (anti-spam).
    4. The webhook sender raising → caller still succeeds, DB write intact
       (best-effort egress).

The webhook SENDER is always MOCKED — no real webhook is ever sent. The
``_maybe_egress_risk_alert`` helper imports ``send_ops_alert_v2`` lazily from
``ops_health_service``, so we patch it at that module path.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.observability import alerts
from packages.quantum.observability.alerts import alert

_SENDER_PATH = "packages.quantum.services.ops_health_service.send_ops_alert_v2"
_WEBHOOK_ENV = "OPS_ALERT_WEBHOOK_URL"


class _EnvGuard:
    """Context manager: set/unset OPS_ALERT_WEBHOOK_URL, restore after."""

    def __init__(self, value):
        self._value = value
        self._prior = None

    def __enter__(self):
        self._prior = os.environ.get(_WEBHOOK_ENV)
        if self._value is None:
            os.environ.pop(_WEBHOOK_ENV, None)
        else:
            os.environ[_WEBHOOK_ENV] = self._value
        return self

    def __exit__(self, *exc):
        if self._prior is None:
            os.environ.pop(_WEBHOOK_ENV, None)
        else:
            os.environ[_WEBHOOK_ENV] = self._prior
        return False


class TestRiskEventEgresses(unittest.TestCase):
    def test_force_close_egresses_sender_called(self):
        """LOAD-BEARING: a force_close (brake-fire/per-symbol-loss class)
        critical alert with the webhook URL set CALLS the egress sender —
        egress actually happened, not merely a DB row written."""
        supabase = MagicMock()
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH
        ) as sender:
            sender.return_value = {"sent": True, "webhook_sent": True}
            alert(
                supabase,
                alert_type="force_close",
                message="Force-closed AAPL: daily brake fire",
                severity="critical",
                position_id="p-1",
                symbol="AAPL",
            )

        # DB row still written (source of truth). CONTRACT CHANGED — A9
        # receipt (2026-07-07): after the send, alert() stamps a delivery
        # receipt back onto the row, so table("risk_alerts") is now touched
        # twice (insert + receipt UPDATE). The insert stays exactly once.
        supabase.table.assert_called_with("risk_alerts")
        supabase.table.return_value.insert.return_value.execute.assert_called_once()
        supabase.table.return_value.update.assert_called_once()

        # Egress happened: the EXISTING sender was called once.
        sender.assert_called_once()
        kwargs = sender.call_args.kwargs
        self.assertEqual(kwargs["alert_type"], "force_close")
        # 'critical' passes straight through to the ops vocabulary.
        self.assertEqual(kwargs["severity"], "critical")
        # client=None → no duplicate risk_alerts row from the sender's own
        # Channel 1; only the webhook (Channel 2) runs.
        self.assertIsNone(kwargs["client"])
        # Symbol/position threaded into the egress details.
        self.assertEqual(kwargs["details"].get("symbol"), "AAPL")
        self.assertEqual(kwargs["details"].get("position_id"), "p-1")

    def test_high_severity_per_symbol_loss_egresses_mapped_to_error(self):
        """A 'high' per-symbol-loss protection-degraded alert egresses, and
        'high' is mapped to the sender's 'error' (the sender's severity_order
        knows critical/error/warning, not 'high')."""
        supabase = MagicMock()
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH
        ) as sender:
            alert(
                supabase,
                alert_type="loss_per_symbol_protection_degraded",
                message="loss_per_symbol protection degraded for SPY",
                severity="high",
                symbol="SPY",
            )
        sender.assert_called_once()
        self.assertEqual(sender.call_args.kwargs["severity"], "error")


class TestUrlUnsetIsSafe(unittest.TestCase):
    def test_url_unset_db_written_and_no_crash(self):
        """URL UNSET → path is SAFE: DB row still written, no exception. The
        sender is still invoked (it owns the no_webhook suppression), but with
        no URL it does not egress — we don't duplicate that gating here."""
        supabase = MagicMock()
        with _EnvGuard(None), patch(_SENDER_PATH) as sender:
            sender.return_value = {
                "sent": False,
                "suppressed_reason": "no_webhook",
            }
            alert(
                supabase,
                alert_type="force_close",
                message="Force-closed AAPL",
                severity="critical",
            )
        # DB write intact.
        supabase.table.return_value.insert.return_value.execute.assert_called_once()
        # Sender consulted; gating is its responsibility → suppressed, no
        # network egress. (We assert no crash + DB intact above.)
        sender.assert_called_once()

    def test_url_unset_real_sender_no_network(self):
        """End-to-end with the REAL sender (no mock) and URL unset: must not
        raise and must not perform any network egress. Patch requests.post to
        prove it is never called."""
        supabase = MagicMock()
        with _EnvGuard(None), patch(
            "requests.post"
        ) as post:
            alert(
                supabase,
                alert_type="force_close",
                message="Force-closed AAPL",
                severity="critical",
            )
        post.assert_not_called()


class TestAntiSpam(unittest.TestCase):
    def test_warn_level_risk_type_does_not_egress(self):
        """A warn-level row on an allowlisted type must NOT egress —
        only critical/high egress."""
        supabase = MagicMock()
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH
        ) as sender:
            alert(
                supabase,
                alert_type="force_close",
                message="warn-only force_close note",
                severity="warning",
            )
        supabase.table.return_value.insert.return_value.execute.assert_called_once()
        sender.assert_not_called()

    def test_non_risk_critical_type_does_not_egress(self):
        """A critical alert whose type is NOT on the risk allowlist must NOT
        egress (e.g. a high-severity concentration warn the table stores as
        'high' / an unrelated critical) — anti-spam allowlist gate."""
        supabase = MagicMock()
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH
        ) as sender:
            alert(
                supabase,
                alert_type="some_unrelated_event",
                message="not a loss-protection category",
                severity="critical",
            )
            alert(
                supabase,
                alert_type="concentration_symbol",
                message="concentration high row",
                severity="high",
            )
        sender.assert_not_called()


class TestEgressBestEffort(unittest.TestCase):
    def test_sender_raises_caller_still_succeeds(self):
        """Webhook sender raising must NOT break the caller; the DB row write
        is intact (best-effort egress)."""
        supabase = MagicMock()
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH, side_effect=RuntimeError("webhook boom")
        ) as sender:
            # MUST NOT raise.
            alert(
                supabase,
                alert_type="exit_protection_disarmed",
                message="close retries suspended",
                severity="critical",
                position_id="p-9",
            )
        sender.assert_called_once()
        # DB write happened despite the egress failure.
        supabase.table.return_value.insert.return_value.execute.assert_called_once()

    def test_egress_runs_even_if_db_insert_failed(self):
        """Egress is AFTER the insert and independent of its success — if the
        DB write raised (caught internally), the operator is still notified."""
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("db down")
        )
        with _EnvGuard("https://hooks.example.test/T/B/X"), patch(
            _SENDER_PATH
        ) as sender:
            # MUST NOT raise.
            alert(
                supabase,
                alert_type="force_close",
                message="Force-closed AAPL while DB is down",
                severity="critical",
            )
        sender.assert_called_once()


class TestAllowlistShape(unittest.TestCase):
    def test_allowlist_contains_the_loss_protection_categories(self):
        """Guard the allowlist against accidental shrink: the documented
        loss-protection categories must stay covered."""
        for t in (
            "force_close",
            "exit_protection_disarmed",
            "job_dead_lettered",
            "loss_per_symbol_protection_degraded",
            "stop_loss_protection_degraded",
        ):
            self.assertIn(t, alerts._RISK_EGRESS_ALERT_TYPES)

    def test_ops_prefixed_types_not_in_allowlist(self):
        """ops_* categories are egressed by ops_health_service itself — they
        must NOT be re-egressed here (no double-send)."""
        for t in alerts._RISK_EGRESS_ALERT_TYPES:
            self.assertFalse(t.startswith("ops_"))


if __name__ == "__main__":
    unittest.main()
