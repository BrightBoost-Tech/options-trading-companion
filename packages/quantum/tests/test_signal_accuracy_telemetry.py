"""Gap-2 (2026-07-02) — rolling signal-accuracy telemetry. OBSERVE-ONLY.

Pins: degraded ⇔ overall n ≥ MIN_N AND hit_rate < floor; insufficient sample
or missing telemetry never alerts; a view-read failure returns [] and the
health-check section never raises; the alert is warning-severity with the
standard fingerprint cooldown. No decision path reads any of this.
"""

from unittest.mock import MagicMock, patch

from packages.quantum.services.ops_health_service import (
    evaluate_signal_accuracy,
    get_signal_accuracy,
)


def _row(scope="overall", n=10, wins=1, hit_rate=0.1, brier=0.41, brier_n=10):
    # F-A9-1: the view column is realized_trade_win_rate (renamed from the
    # mislabeled hit_rate). The param name stays for brevity; the emitted key
    # reflects the real view.
    return {
        "scope": scope, "n": n, "wins": wins, "realized_trade_win_rate": hit_rate,
        "brier": brier, "brier_n": brier_n,
        "window_start": "2026-06-01T00:00:00+00:00",
        "window_end": "2026-07-01T00:00:00+00:00",
    }


class TestEvaluate:
    def test_degraded_at_meaningful_sample(self):
        v = evaluate_signal_accuracy([_row(n=10, hit_rate=0.1)], min_n=8, min_hit_rate=0.2)
        assert v["degraded"] is True
        assert "realized_trade_win_rate" in v["reason"]

    def test_insufficient_sample_never_degraded(self):
        v = evaluate_signal_accuracy([_row(n=7, hit_rate=0.0)], min_n=8, min_hit_rate=0.2)
        assert v["degraded"] is False
        assert v["reason"].startswith("insufficient_sample")

    def test_healthy_hit_rate_not_degraded(self):
        v = evaluate_signal_accuracy([_row(n=20, wins=9, hit_rate=0.45)], min_n=8, min_hit_rate=0.2)
        assert v["degraded"] is False
        assert v["reason"] == "ok"

    def test_boundary_hit_rate_at_floor_not_degraded(self):
        v = evaluate_signal_accuracy([_row(n=10, hit_rate=0.2)], min_n=8, min_hit_rate=0.2)
        assert v["degraded"] is False

    def test_missing_overall_scope_is_no_telemetry(self):
        v = evaluate_signal_accuracy([_row(scope="strategy:IRON_CONDOR", n=20, hit_rate=0.0)])
        assert v["degraded"] is False
        assert v["reason"] == "no_telemetry"

    def test_empty_rows_no_telemetry(self):
        v = evaluate_signal_accuracy([])
        assert v["degraded"] is False

    def test_unparseable_row_never_degrades(self):
        v = evaluate_signal_accuracy([{"scope": "overall", "n": "x", "hit_rate": "y"}])
        assert v["degraded"] is False


class TestViewReader:
    def test_read_failure_returns_empty(self):
        client = MagicMock()
        client.table.side_effect = RuntimeError("db down")
        assert get_signal_accuracy(client) == []

    def test_reads_view_rows(self):
        client = MagicMock()
        (
            client.table.return_value.select.return_value.execute.return_value
        ) = MagicMock(data=[_row()])
        rows = get_signal_accuracy(client)
        assert rows and rows[0]["scope"] == "overall"
        client.table.assert_called_once_with("signal_accuracy_rolling")


class TestHandlerSection:
    def test_degraded_alerts_warning_with_cooldown(self):
        from packages.quantum.jobs.handlers import ops_health_check as ohc

        client = MagicMock()
        with patch.object(ohc, "get_signal_accuracy", return_value=[_row(n=10, hit_rate=0.1)]):
            with patch.object(ohc, "should_suppress_alert", return_value=(False, None)):
                with patch.object(
                    ohc, "send_ops_alert_v2", return_value={"sent": True}
                ) as m:
                    out = ohc._check_signal_accuracy(client, "warning", 30)
        assert out["degraded"] is True
        assert out["alerted"] is True
        assert m.call_args.args[0] == "signal_accuracy_degraded"
        assert m.call_args.kwargs["severity"] == "warning"

    def test_cooldown_suppresses(self):
        from packages.quantum.jobs.handlers import ops_health_check as ohc

        client = MagicMock()
        with patch.object(ohc, "get_signal_accuracy", return_value=[_row(n=10, hit_rate=0.1)]):
            with patch.object(ohc, "should_suppress_alert", return_value=(True, "t")):
                with patch.object(ohc, "send_ops_alert_v2") as m:
                    out = ohc._check_signal_accuracy(client, "warning", 30)
        m.assert_not_called()
        assert out["suppressed"] == "cooldown"

    def test_healthy_no_alert(self):
        from packages.quantum.jobs.handlers import ops_health_check as ohc

        client = MagicMock()
        with patch.object(ohc, "get_signal_accuracy", return_value=[_row(n=20, hit_rate=0.5)]):
            with patch.object(ohc, "send_ops_alert_v2") as m:
                out = ohc._check_signal_accuracy(client, "warning", 30)
        m.assert_not_called()
        assert out["degraded"] is False

    def test_section_never_raises(self):
        from packages.quantum.jobs.handlers import ops_health_check as ohc

        client = MagicMock()
        with patch.object(ohc, "get_signal_accuracy", side_effect=RuntimeError("boom")):
            out = ohc._check_signal_accuracy(client, "warning", 30)
        assert "error" in out
        assert out["degraded"] is False
