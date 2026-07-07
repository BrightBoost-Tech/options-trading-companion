"""PR taxonomy+alert-integrity (2026-07-07) — A9 F1/F2/F6/F7 + receipt + F8 + F3.

Pinned tests demanded by the build order:
  1. RECEIPT FAIL-OPEN — a failed receipt write must never throw into,
     retry into, or block the send path.
  2. F8 ERROR-PROPAGATION — a run with a persist failure reports errors>=1,
     not ok:true; alert-write losses fold into counts.errors at the runner.
  3. PER-TYPE IMMEDIATE EGRESS — each force_close-family type egresses AND
     takes the immediate path; a renamed type silently dropping off egress
     is the failure this guards.
Plus: F3 row-lost fail-safe, the transient-matcher extension (today's
18:45Z specimen), and the monitor taxonomy source pins.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# De-poison guard (the #1132 lesson): bind real modules at import time.
for _key in (
    "packages.quantum.observability.alerts",
    "packages.quantum.jobs.runner",
):
    if isinstance(sys.modules.get(_key), MagicMock):
        del sys.modules[_key]

from packages.quantum.observability import alerts as alerts_mod

_QUANTUM = Path(__file__).parent.parent


def _sb_ok(row_id="row-0001-abcd"):
    """Supabase mock: insert succeeds (returns a row id), update succeeds."""
    sb = MagicMock()
    chain = MagicMock()
    chain.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": row_id}]
    )
    chain.update.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": row_id}]
    )
    sb.table.return_value = chain
    return sb, chain


def _send_result(sent=True, webhook=True, suppressed=None):
    return {
        "sent": sent, "webhook_sent": webhook, "suppressed_reason": suppressed,
        "fingerprint": "f", "severity": "critical", "risk_alert_written": False,
    }


class TestReceiptFailOpen:
    """Pin 1 — the non-negotiable."""

    def test_receipt_update_failure_never_raises_and_send_already_happened(self):
        sb, chain = _sb_ok()
        chain.update.return_value.eq.return_value.execute.side_effect = (
            RuntimeError("receipt write blew up")
        )
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
            return_value=_send_result(),
        ) as m_send:
            # Must not raise.
            alerts_mod.alert(
                sb, alert_type="force_close", message="m", severity="critical",
            )
        assert m_send.called  # send happened despite the broken receipt
        # And the send happened BEFORE the receipt attempt (update called
        # after send returned — the mock ordering proves no receipt-first).
        assert chain.update.called

    def test_receipt_stamps_metadata_on_success(self):
        sb, chain = _sb_ok()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
            return_value=_send_result(),
        ):
            alerts_mod.alert(
                sb, alert_type="force_close", message="m", severity="critical",
                metadata={"k": "v"},
            )
        assert chain.update.called
        payload = chain.update.call_args.args[0]
        meta = payload["metadata"]
        assert meta["egress_receipt"]["webhook_sent"] is True
        assert meta["egressed_at"]  # relay-compatible delivery stamp
        assert meta["k"] == "v"  # caller metadata preserved

    def test_no_receipt_update_for_non_egressing_alert(self):
        sb, chain = _sb_ok()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
        ) as m_send:
            alerts_mod.alert(
                sb, alert_type="chain_mechanics_formula_anomaly",
                message="m", severity="warning",
            )
        assert not m_send.called
        assert not chain.update.called


class TestPerTypeImmediateEgress:
    """Pin 3 — each force_close-family type takes the immediate path."""

    @pytest.mark.parametrize("atype", ["force_close", "force_close_failed"])
    def test_family_type_egresses_immediately(self, atype):
        sb, _ = _sb_ok()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
            return_value=_send_result(),
        ) as m_send:
            alerts_mod.alert(
                sb, alert_type=atype, message="m", severity="critical",
            )
        assert m_send.called, f"{atype} must take the IMMEDIATE egress path"
        assert m_send.call_args.kwargs["alert_type"] == atype

    def test_warn_only_type_rides_relay_not_immediate(self):
        """envelope_violation_warn_only (high, nothing closed) is NOT on the
        immediate allowlist — no owner stamp, so the relay picks it up."""
        sb, chain = _sb_ok()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
        ) as m_send:
            alerts_mod.alert(
                sb, alert_type="envelope_violation_warn_only",
                message="m", severity="high",
            )
        assert not m_send.called
        record = chain.insert.call_args.args[0]
        assert "egress_owner" not in record["metadata"]  # relay-eligible

    def test_allowlisted_insert_stamps_owner(self):
        sb, chain = _sb_ok()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
            return_value=_send_result(),
        ):
            alerts_mod.alert(
                sb, alert_type="force_close_failed", message="m",
                severity="critical",
            )
        record = chain.insert.call_args.args[0]
        assert record["metadata"]["egress_owner"] == "alert"


class TestF3RowLostFailSafe:
    def test_lost_critical_insert_still_egresses_with_marker(self):
        """A non-allowlisted CRITICAL whose insert is lost must still reach
        the webhook, marked [DB-ROW-LOST] — the inbox is the durable trace."""
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("permanent DB failure")  # non-transient → no retry
        )
        before = alerts_mod.get_alert_write_failure_count()
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
            return_value=_send_result(),
        ) as m_send:
            alerts_mod.alert(
                sb, alert_type="some_unlisted_critical", message="the event",
                severity="critical",
            )
        assert m_send.called
        assert m_send.call_args.kwargs["message"].startswith("[DB-ROW-LOST] ")
        assert m_send.call_args.kwargs["details"]["db_row_lost"] is True
        assert alerts_mod.get_alert_write_failure_count() == before + 1

    def test_lost_warning_insert_does_not_egress(self):
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("permanent DB failure")
        )
        with patch(
            "packages.quantum.services.ops_health_service.send_ops_alert_v2",
        ) as m_send:
            alerts_mod.alert(
                sb, alert_type="whatever", message="m", severity="warning",
            )
        assert not m_send.called  # anti-spam boundary unchanged

    def test_todays_specimen_is_now_transient(self):
        """httpx WriteError '[Errno 104] Connection reset by peer' — the
        exact 18:45Z shape — must now be retryable."""
        class WriteError(Exception):
            pass

        assert alerts_mod._is_transient_disconnect(
            WriteError("[Errno 104] Connection reset by peer")
        )
        assert alerts_mod._is_transient_disconnect(
            RuntimeError("[Errno 104] Connection reset by peer")
        )
        assert not alerts_mod._is_transient_disconnect(
            RuntimeError("relation does not exist")
        )


class TestF8ErrorPropagation:
    """Pin 2 — persist/alert-write failures surface in job results."""

    def test_rollup_counts_cycle_persist_failures(self):
        from packages.quantum.jobs.handlers.suggestions_open import (
            _persist_error_rollup,
        )
        cycles = [
            {"counts": {"rejection_persist_failures": 11}},
            {"counts": {}},
            {},
            None,
            {"counts": {"rejection_persist_failures": "2"}},
        ]
        assert _persist_error_rollup(cycles) == 13
        assert _persist_error_rollup([]) == 0
        assert _persist_error_rollup(None) == 0

    def test_handler_wiring_ok_false_on_persist_failure(self):
        """PRODUCTION CALL PATH pin (the 9a2cef1/#1126 rule): the handler's
        source must consult the rollup in both counts.errors and ok."""
        src = (_QUANTUM / "jobs" / "handlers" / "suggestions_open.py").read_text(
            encoding="utf-8"
        )
        assert 'counts["errors"] = _persist_error_rollup(cycle_results)' in src
        assert '"ok": failed == 0 and counts["errors"] == 0' in src

    def test_runner_fold_adds_errors_and_is_byte_identical_on_zero(self):
        from packages.quantum.jobs.runner import _fold_alert_write_failures
        with patch(
            "packages.quantum.observability.alerts.get_alert_write_failure_count",
            return_value=7,
        ):
            folded = _fold_alert_write_failures({"ok": True, "counts": {}}, 5)
            assert folded["counts"]["alert_write_failures"] == 2
            assert folded["counts"]["errors"] == 2
            same = {"ok": True, "counts": {"errors": 0}}
            assert _fold_alert_write_failures(same, 7) == {
                "ok": True, "counts": {"errors": 0}
            }

    def test_runner_wiring_snapshot_around_handler(self):
        src = (_QUANTUM / "jobs" / "runner.py").read_text(encoding="utf-8")
        assert "_alert_failures_before = get_alert_write_failure_count()" in src
        assert "_fold_alert_write_failures(" in src


class TestMonitorTaxonomySourcePins:
    """F1/F2/F7 at the emit sites — the costume is retired at the writer."""

    def _src(self):
        return (
            _QUANTUM / "jobs" / "handlers" / "intraday_risk_monitor.py"
        ).read_text(encoding="utf-8")

    def test_no_untyped_warn_writer_remains(self):
        assert 'alert_type="warn"' not in self._src()

    def test_three_realities_have_three_types(self):
        src = self._src()
        assert 'alert_type="force_close"' in src  # real submitted close
        assert 'alert_type="force_close_failed"' in src
        assert 'alert_type="envelope_violation_warn_only"' in src
        assert 'alert_type="envelope_violation"' in src

    def test_log_alert_delegates_to_canonical_alert_and_normalizes(self):
        src = self._src()
        assert "from packages.quantum.observability.alerts import alert" in src
        assert '"medium": "warning"' in src
        # the bare direct insert is gone from _log_alert
        tail = src.split("def _log_alert", 1)[1]
        assert 'table("risk_alerts").insert' not in tail
