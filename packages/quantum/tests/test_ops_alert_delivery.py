"""v5-A4 ops-health alert delivery (N2, 2026-06-11).

Pre-fix, ops-health DETECTED issues but never DELIVERED them:
- delivery was webhook-only and OPS_ALERT_WEBHOOK_URL has never been set on
  this deployment → every alert died with suppressed_reason="no_webhook"
  (including the 25-day calibration freeze — found by audit, not by ops);
- the severity map {"error": 2, "warning": 1} OMITTED "critical" →
  severity_order.get("critical", 0) = 0 < warning(1) → the MOST severe
  class (job_never_run) was the only one always suppressed;
- with a real channel added, the nightly-by-construction data_stale would
  have become steady-state noise → its ALERT is market-hours gated.

Pins:
- critical outranks error outranks warning (the inverted-suppression bug)
- dual-channel: risk_alerts written via the canonical alert() when client
  is passed, sent=True without any webhook; severity maps
  critical→critical / error→high / warning→warning (H11 sweeps read
  critical+high)
- below-min suppression still suppresses BOTH channels
- webhook failure does not retract a successful risk_alerts delivery
- is_us_market_hours boundary behavior + the data_stale gate in the handler
- all five handler send sites pass client= (source pins)
"""

import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Stub alpaca-py per convention.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services import ops_health_service as ohs  # noqa: E402


class TestSeverityOrderFix(unittest.TestCase):
    def test_critical_not_suppressed_below_warning_min(self):
        """The inverted-suppression bug: critical used to map to 0 and lose
        to min_severity=warning. It must now pass the threshold and (with a
        client) deliver to risk_alerts."""
        client = MagicMock()
        with patch.object(ohs, "os") as _os:
            _os.getenv.return_value = None  # no webhook
            res = ohs.send_ops_alert_v2(
                "job_never_run", "scheduler down", severity="critical",
                min_severity="warning", client=client,
            )
        self.assertNotEqual(res["suppressed_reason"], "below_min_severity")
        self.assertTrue(res["risk_alert_written"])
        self.assertTrue(res["sent"])

    def test_warning_below_error_min_suppresses_both_channels(self):
        client = MagicMock()
        res = ohs.send_ops_alert_v2(
            "job_late", "late", severity="warning",
            min_severity="error", client=client,
        )
        self.assertEqual(res["suppressed_reason"], "below_min_severity")
        self.assertFalse(res["risk_alert_written"])
        self.assertFalse(res["sent"])
        client.table.assert_not_called()


class TestDualChannel(unittest.TestCase):
    def _send(self, client, severity="error", webhook=None):
        env = {"OPS_ALERT_WEBHOOK_URL": webhook} if webhook else {}
        with patch.dict("os.environ", env, clear=False):
            if not webhook:
                import os as _os
                _os.environ.pop("OPS_ALERT_WEBHOOK_URL", None)
            return ohs.send_ops_alert_v2(
                "data_stale", "stale msg", details={"x": 1},
                severity=severity, min_severity="warning", client=client,
            )

    def test_risk_alerts_written_without_webhook(self):
        """The headline fix: delivery no longer depends on a webhook that
        was never configured."""
        client = MagicMock()
        captured = {}

        def _fake_alert(c, **kw):
            captured.update(kw)

        with patch(
            "packages.quantum.observability.alerts.alert", side_effect=_fake_alert
        ):
            res = self._send(client)
        self.assertTrue(res["sent"])
        self.assertTrue(res["risk_alert_written"])
        self.assertFalse(res["webhook_sent"])
        self.assertEqual(captured["alert_type"], "ops_data_stale")
        self.assertEqual(captured["severity"], "high")  # error → high
        self.assertEqual(captured["metadata"]["source"], "ops_health_check")

    def test_severity_mapping_to_risk_alerts(self):
        for ops_sev, risk_sev in (("critical", "critical"), ("error", "high"),
                                  ("warning", "warning")):
            captured = {}
            with patch(
                "packages.quantum.observability.alerts.alert",
                side_effect=lambda c, **kw: captured.update(kw),
            ):
                ohs.send_ops_alert_v2(
                    "job_failure", "m", severity=ops_sev,
                    min_severity="warning", client=MagicMock(),
                )
            self.assertEqual(captured["severity"], risk_sev, ops_sev)

    def test_no_client_is_designed_channel2_only_at_info(self):
        """CONTRACT CHANGED — A9-F6 (2026-07-07): client=None is the DESIGNED
        channel-2-only mode (the caller already wrote the risk_alerts row and
        passes None precisely to avoid a duplicate). The old loud 'webhook-only
        legacy mode' WARNING read as pipeline degradation on every healthy
        immediate egress; it is now an honest INFO line and must NOT log at
        WARNING or above."""
        with self.assertLogs(
            "packages.quantum.services.ops_health_service", level="INFO"
        ) as cm:
            res = ohs.send_ops_alert_v2(
                "job_failure", "m", severity="error",
                min_severity="warning", client=None,
            )
        self.assertFalse(res["risk_alert_written"])
        self.assertTrue(any("channel-2" in m for m in cm.output))
        self.assertFalse(any(
            m.startswith(("WARNING", "ERROR", "CRITICAL"))
            and "no supabase client" in m
            for m in cm.output
        ))

    def test_risk_alert_failure_does_not_crash(self):
        with patch(
            "packages.quantum.observability.alerts.alert",
            side_effect=RuntimeError("db down"),
        ):
            res = ohs.send_ops_alert_v2(
                "job_failure", "m", severity="error",
                min_severity="warning", client=MagicMock(),
            )
        self.assertFalse(res["risk_alert_written"])
        # no webhook either → suppressed_reason records the void
        self.assertEqual(res["suppressed_reason"], "no_webhook")

    def test_webhook_failure_does_not_retract_risk_alert_delivery(self):
        with patch(
            "packages.quantum.observability.alerts.alert", side_effect=lambda c, **kw: None
        ), patch.dict("os.environ", {"OPS_ALERT_WEBHOOK_URL": "http://x"}), patch(
            "requests.post", side_effect=RuntimeError("net down")
        ):
            res = ohs.send_ops_alert_v2(
                "job_failure", "m", severity="error",
                min_severity="warning", client=MagicMock(),
            )
        self.assertTrue(res["sent"])
        self.assertTrue(res["risk_alert_written"])
        self.assertFalse(res["webhook_sent"])
        self.assertIsNone(res["suppressed_reason"])


class TestMarketHoursGate(unittest.TestCase):
    def test_broker_closed_overrides_weekday_wall_clock_on_holiday(self):
        labor_day_rth = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)
        self.assertFalse(
            ohs.is_us_market_hours(
                labor_day_rth,
                broker_is_open=False,
            )
        )

    def test_broker_open_overrides_wall_clock(self):
        saturday = datetime(2026, 6, 13, 15, 0, tzinfo=timezone.utc)
        self.assertTrue(
            ohs.is_us_market_hours(saturday, broker_is_open=True)
        )

    def test_weekday_open(self):
        self.assertTrue(ohs.is_us_market_hours(
            datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc)))

    def test_weekday_pre_open(self):
        self.assertFalse(ohs.is_us_market_hours(
            datetime(2026, 6, 11, 13, 29, tzinfo=timezone.utc)))

    def test_weekday_post_close(self):
        self.assertFalse(ohs.is_us_market_hours(
            datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc)))

    def test_open_boundary_inclusive(self):
        self.assertTrue(ohs.is_us_market_hours(
            datetime(2026, 6, 11, 13, 30, tzinfo=timezone.utc)))

    def test_weekend(self):
        self.assertFalse(ohs.is_us_market_hours(
            datetime(2026, 6, 13, 15, 0, tzinfo=timezone.utc)))

    # A10 winter-close fix (2026-07-12): ET wall-clock, DST-correct.
    def test_winter_close_is_21z_not_20z(self):
        # EST: market closes 16:00 ET = 21:00Z. The 20:00–21:00Z hour that the
        # old hardcoded 20:00Z window read as CLOSED is now correctly OPEN.
        self.assertTrue(ohs.is_us_market_hours(   # 20:30Z EST = 15:30 ET (the blind hour)
            datetime(2026, 11, 17, 20, 30, tzinfo=timezone.utc)))
        self.assertTrue(ohs.is_us_market_hours(   # 20:59Z EST = 15:59 ET (last minute)
            datetime(2026, 11, 17, 20, 59, tzinfo=timezone.utc)))
        self.assertFalse(ohs.is_us_market_hours(  # 21:00Z EST = 16:00 ET (close)
            datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)))

    def test_summer_close_still_20z(self):
        # EDT: market closes 16:00 ET = 20:00Z (byte-identical to the old window).
        self.assertTrue(ohs.is_us_market_hours(   # 19:59Z EDT = 15:59 ET
            datetime(2026, 7, 15, 19, 59, tzinfo=timezone.utc)))
        self.assertFalse(ohs.is_us_market_hours(  # 20:00Z EDT = 16:00 ET (close)
            datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)))

    def test_winter_open_is_1430z(self):
        # EST open: 9:30 ET = 14:30Z (vs EDT 13:30Z).
        self.assertTrue(ohs.is_us_market_hours(
            datetime(2026, 11, 17, 14, 30, tzinfo=timezone.utc)))
        self.assertFalse(ohs.is_us_market_hours(  # 14:29Z EST = 9:29 ET (pre-open)
            datetime(2026, 11, 17, 14, 29, tzinfo=timezone.utc)))


class TestHandlerWiring(unittest.TestCase):
    """Source pins on the handler: every send passes client=, the data_stale
    alert is market-hours gated, and the synthetic proof hook exists."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.src = (
            Path(__file__).parent.parent / "jobs" / "handlers" / "ops_health_check.py"
        ).read_text(encoding="utf-8")

    def test_all_send_sites_pass_client(self):
        sends = self.src.count("send_ops_alert_v2(")
        clients = self.src.count("client=client,")
        self.assertGreaterEqual(sends, 6)  # 5 issue sites + synthetic hook
        self.assertEqual(clients, sends)

    def test_data_stale_market_hours_gate(self):
        self.assertIn("is_us_market_hours()", self.src)
        self.assertIn("outside_market_hours", self.src)

    def test_synthetic_delivery_hook(self):
        self.assertIn('payload.get("synthetic_delivery_test")', self.src)
        self.assertIn('"synthetic_delivery_test",', self.src)


class TestEndpointWiring(unittest.TestCase):
    """The signed endpoint must ACCEPT and FORWARD the synthetic flag — the
    first dispatch attempt 422'd on extra_forbidden, and the endpoint
    rebuilds job_payload so an accepted-but-unforwarded flag would silently
    no-op (the dishonest middle state)."""

    def test_payload_model_accepts_flag(self):
        from packages.quantum.public_tasks_models import OpsHealthCheckPayload
        p = OpsHealthCheckPayload(synthetic_delivery_test=True)
        self.assertTrue(p.synthetic_delivery_test)
        self.assertFalse(OpsHealthCheckPayload().synthetic_delivery_test)

    def test_endpoint_forwards_flag_and_suffixes_idempotency(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "public_tasks.py"
        ).read_text(encoding="utf-8")
        self.assertIn('job_payload["synthetic_delivery_test"] = True', src)
        self.assertIn('idempotency_key = f"{idempotency_key}-synthetic"', src)


if __name__ == "__main__":
    unittest.main()
