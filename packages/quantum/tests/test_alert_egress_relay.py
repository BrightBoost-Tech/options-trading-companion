"""A3 (2026-07-02) — direct-insert risk_alerts egress relay.

Contract under pin:
- a direct-insert critical/high row egresses within one poll (Channel-2-only
  send, then metadata marked egressed_at + egress_owner=relay);
- already-egressed rows, alert()-owned rows (#1096 pre-stamp), and ops_*
  Channel-1 rows are SKIPPED (double-send boundaries);
- webhook down → row left unmarked (retried next cycle), relay never raises,
  and 3 consecutive failures break the loop (no 100×10s timeout pile-up);
- the epoch watermark is honored server-side (pre-deploy rows untouched);
- per-poll rate guard caps sends and logs when capped;
- alert() pre-stamps egress_owner ONLY for allowlisted critical/high and
  never mutates the caller's metadata dict.
"""

import logging
import unittest
from unittest.mock import patch

from packages.quantum.services import ops_health_service as ohs
from packages.quantum.observability import alerts as alerts_mod


def _row(i, severity="critical", alert_type="force_close", meta=None,
         created="2026-07-02T04:30:00+00:00"):
    return {
        "id": f"id-{i}", "alert_type": alert_type, "severity": severity,
        "message": f"boom {i}", "symbol": None, "position_id": None,
        "created_at": created, "metadata": dict(meta) if meta else {},
    }


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, sink, rows, fail_select=False):
        self._sink = sink
        self._rows = rows
        self._fail_select = fail_select
        self._update_payload = None
        self._update_id = None

    def select(self, cols):
        self._sink["select"] = cols
        return self

    def in_(self, col, vals):
        self._sink["in"] = (col, list(vals))
        return self

    def gt(self, col, val):
        self._sink["gt"] = (col, val)
        return self

    def order(self, col, desc=False):
        self._sink["order"] = (col, desc)
        return self

    def limit(self, n):
        self._sink["limit"] = n
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._update_id = val
        return self

    def execute(self):
        if self._update_payload is not None:
            self._sink.setdefault("updates", []).append(
                {"id": self._update_id, "payload": self._update_payload}
            )
            return _Result(None)
        if self._fail_select:
            raise RuntimeError("db down")
        return _Result(list(self._rows))


class _FakeClient:
    def __init__(self, rows, fail_select=False):
        self.sink = {}
        self._rows = rows
        self._fail_select = fail_select

    def table(self, name):
        assert name == "risk_alerts"
        return _FakeQuery(self.sink, self._rows, self._fail_select)


_SENT = {"webhook_sent": True, "sent": True, "suppressed_reason": None}
_DOWN = {"webhook_sent": False, "sent": False, "suppressed_reason": "exception:boom"}


class TestRelayCore(unittest.TestCase):
    def test_direct_insert_critical_egressed_within_one_poll(self):
        client = _FakeClient([_row(1)])
        with patch.object(ohs, "send_ops_alert_v2", return_value=dict(_SENT)) as m:
            res = ohs.relay_direct_insert_alerts(client)
        self.assertEqual(res["sent"], 1)
        self.assertEqual(res["failed"], 0)
        # Channel-2 only: the existing row IS the DB record.
        self.assertIsNone(m.call_args.kwargs["client"])
        self.assertEqual(m.call_args.kwargs["severity"], "critical")
        updates = client.sink["updates"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["id"], "id-1")
        marked = updates[0]["payload"]["metadata"]
        self.assertEqual(marked["egress_owner"], "relay")
        self.assertIn("egressed_at", marked)

    def test_high_severity_maps_to_error(self):
        client = _FakeClient([_row(1, severity="high")])
        with patch.object(ohs, "send_ops_alert_v2", return_value=dict(_SENT)) as m:
            ohs.relay_direct_insert_alerts(client)
        self.assertEqual(m.call_args.kwargs["severity"], "error")

    def test_already_egressed_skipped(self):
        client = _FakeClient([_row(1, meta={"egressed_at": "2026-07-02T04:00:00+00:00"})])
        with patch.object(ohs, "send_ops_alert_v2") as m:
            res = ohs.relay_direct_insert_alerts(client)
        m.assert_not_called()
        self.assertEqual(res["skipped"], 1)
        self.assertNotIn("updates", client.sink)

    def test_alert_owned_rows_skipped(self):
        client = _FakeClient([_row(1, meta={"egress_owner": "alert"})])
        with patch.object(ohs, "send_ops_alert_v2") as m:
            res = ohs.relay_direct_insert_alerts(client)
        m.assert_not_called()
        self.assertEqual(res["skipped"], 1)

    def test_ops_channel1_rows_skipped(self):
        client = _FakeClient([_row(1, alert_type="ops_data_stale", severity="high")])
        with patch.object(ohs, "send_ops_alert_v2") as m:
            res = ohs.relay_direct_insert_alerts(client)
        m.assert_not_called()
        self.assertEqual(res["skipped"], 1)

    def test_webhook_down_left_unmarked_and_retriable(self):
        client = _FakeClient([_row(1)])
        with patch.object(ohs, "send_ops_alert_v2", return_value=dict(_DOWN)):
            res = ohs.relay_direct_insert_alerts(client)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["sent"], 0)
        # Unmarked → the next poll retries it.
        self.assertNotIn("updates", client.sink)

    def test_three_consecutive_failures_break_the_loop(self):
        rows = [_row(i) for i in range(6)]
        client = _FakeClient(rows)
        with patch.object(ohs, "send_ops_alert_v2", return_value=dict(_DOWN)) as m:
            res = ohs.relay_direct_insert_alerts(client)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(res["failed"], 3)

    def test_query_error_never_raises(self):
        client = _FakeClient([], fail_select=True)
        res = ohs.relay_direct_insert_alerts(client)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["sent"], 0)

    def test_no_client_never_raises(self):
        res = ohs.relay_direct_insert_alerts(None)
        self.assertEqual(res["failed"], 1)

    def test_epoch_watermark_in_query_default(self):
        client = _FakeClient([])
        with patch.object(ohs, "send_ops_alert_v2"):
            ohs.relay_direct_insert_alerts(client)
        col, val = client.sink["gt"]
        self.assertEqual(col, "created_at")
        self.assertEqual(val, ohs.ALERT_RELAY_EPOCH_DEFAULT)

    def test_epoch_watermark_env_override(self):
        client = _FakeClient([])
        with patch.dict("os.environ", {"ALERT_RELAY_EPOCH": "2026-07-03T00:00:00+00:00"}):
            with patch.object(ohs, "send_ops_alert_v2"):
                ohs.relay_direct_insert_alerts(client)
        self.assertEqual(client.sink["gt"][1], "2026-07-03T00:00:00+00:00")

    def test_rate_guard_caps_and_logs(self):
        rows = [_row(i) for i in range(12)]
        client = _FakeClient(rows)
        with patch.object(ohs, "send_ops_alert_v2", return_value=dict(_SENT)):
            with self.assertLogs(level=logging.WARNING) as cm:
                res = ohs.relay_direct_insert_alerts(client, max_per_poll=10)
        self.assertEqual(res["sent"], 10)
        self.assertTrue(res["capped"])
        self.assertEqual(len(client.sink["updates"]), 10)
        self.assertTrue(any("cap" in line for line in cm.output))

    def test_below_min_severity_marked_skipped_not_retried_forever(self):
        client = _FakeClient([_row(1)])
        suppressed = {"webhook_sent": False, "sent": False,
                      "suppressed_reason": "below_min_severity"}
        with patch.object(ohs, "send_ops_alert_v2", return_value=suppressed):
            res = ohs.relay_direct_insert_alerts(client)
        self.assertEqual(res["skipped"], 1)
        marked = client.sink["updates"][0]["payload"]["metadata"]
        self.assertEqual(marked["egress_skipped"], "below_min_severity")
        self.assertNotIn("egressed_at", marked)


class _InsertCapture:
    def __init__(self):
        self.records = []

    def table(self, name):
        return self

    def insert(self, record):
        self.records.append(record)
        return self

    def execute(self):
        return _Result(None)


class TestAlertPreStamp(unittest.TestCase):
    def test_allowlisted_critical_stamped(self):
        client = _InsertCapture()
        alerts_mod.alert(client, alert_type="force_close",
                         message="m", severity="critical")
        self.assertEqual(client.records[0]["metadata"]["egress_owner"], "alert")

    def test_non_allowlisted_not_stamped(self):
        client = _InsertCapture()
        alerts_mod.alert(client, alert_type="some_random_type",
                         message="m", severity="critical")
        self.assertNotIn("egress_owner", client.records[0]["metadata"])

    def test_allowlisted_low_severity_not_stamped(self):
        client = _InsertCapture()
        alerts_mod.alert(client, alert_type="force_close",
                         message="m", severity="warning")
        self.assertNotIn("egress_owner", client.records[0]["metadata"])

    def test_caller_metadata_never_mutated(self):
        client = _InsertCapture()
        caller_meta = {"k": "v"}
        alerts_mod.alert(client, alert_type="force_close", message="m",
                         severity="critical", metadata=caller_meta)
        self.assertEqual(caller_meta, {"k": "v"})
        self.assertEqual(client.records[0]["metadata"]["egress_owner"], "alert")
        self.assertEqual(client.records[0]["metadata"]["k"], "v")


class TestHandlerIsolation(unittest.TestCase):
    def test_relay_step_failure_never_raises(self):
        from packages.quantum.jobs.handlers import ops_health_check as ohc

        with patch.object(ohc, "relay_direct_insert_alerts",
                          side_effect=RuntimeError("relay bug")):
            out = ohc._run_alert_relay(object())
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
