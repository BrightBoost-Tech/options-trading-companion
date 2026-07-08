"""One-beta exposure tripwire (meta-audit gap #3, 2026-07-08).

ALARM, never act: ≥2 open LIVE-routed positions with no bucket control →
critical on the immediate-egress allowlist. Simplest-correct version (any 2
live positions; bucket refinement stays filed as B1/B2). Alarm-on-onset
dedup by position-id set; scope-failed cycles skip; flag default-ON.
THE DISASTER PIN: the tripwire must never mutate position/order/ops state.
"""

import sys
from unittest.mock import MagicMock, patch

for _key in ("packages.quantum.jobs.handlers.intraday_risk_monitor",):
    if isinstance(sys.modules.get(_key), MagicMock):
        del sys.modules[_key]

from packages.quantum.jobs.handlers.intraday_risk_monitor import (
    IntradayRiskMonitor,
)


def _pos(pid, symbol="QQQ", status="open"):
    return {"id": pid, "symbol": symbol, "status": status,
            "portfolio_id": "live-pf"}


def _monitor(recent_alert_rows=None):
    m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
    sb = MagicMock()
    chain = MagicMock()
    for meth in ("select", "eq", "gte", "limit"):
        getattr(chain, meth).return_value = chain
    chain.execute.return_value = MagicMock(data=recent_alert_rows or [])
    sb.table.return_value = chain
    m.supabase = sb
    m._log_alert = MagicMock()
    return m


class TestFiring:
    def test_zero_and_one_position_no_alarm(self):
        m = _monitor()
        m._one_beta_tripwire("u1", [], True)
        m._one_beta_tripwire("u1", [_pos("a")], True)
        assert not m._log_alert.called

    def test_two_live_positions_fires_critical(self):
        m = _monitor()
        m._one_beta_tripwire("u1", [_pos("a", "QQQ"), _pos("b", "SPY")], True)
        assert m._log_alert.call_count == 1
        kw = m._log_alert.call_args.kwargs
        assert kw["alert_type"] == "concurrent_live_positions_uncontrolled"
        assert kw["severity"] == "critical"
        assert kw["metadata"]["position_set"] == "a,b"
        assert kw["metadata"]["count"] == 2

    def test_standing_set_does_not_realarm(self):
        """Onset dedup: the same open-set already alarmed → silent."""
        m = _monitor(recent_alert_rows=[
            {"id": "x", "metadata": {"position_set": "a,b"}},
        ])
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], True)
        assert not m._log_alert.called

    def test_third_position_new_set_realarms(self):
        m = _monitor(recent_alert_rows=[
            {"id": "x", "metadata": {"position_set": "a,b"}},
        ])
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b"), _pos("c")], True)
        assert m._log_alert.call_count == 1
        assert m._log_alert.call_args.kwargs["metadata"]["position_set"] == "a,b,c"

    def test_dedup_read_failure_alarms_anyway(self):
        """Fail-toward-alarming: a broken dedup read must not silence the
        exposure alarm."""
        m = _monitor()
        m.supabase.table.return_value.execute.side_effect = RuntimeError("db")
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], True)
        assert m._log_alert.call_count == 1

    def test_scope_failed_cycle_skips(self):
        """Scope-unknown = live_positions may contain shadows — skip rather
        than alarm on fiction."""
        m = _monitor()
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], False)
        assert not m._log_alert.called

    def test_closed_rows_do_not_count(self):
        m = _monitor()
        m._one_beta_tripwire(
            "u1", [_pos("a"), _pos("b", status="closed")], True
        )
        assert not m._log_alert.called


class TestPolarityAndSafety:
    def test_explicit_falsy_disables(self):
        for v in ("0", "false", "no", "off"):
            m = _monitor()
            with patch.dict("os.environ",
                            {"CONCURRENT_POSITION_ALARM_ENABLED": v}):
                m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], True)
            assert not m._log_alert.called

    def test_unset_and_empty_are_on(self):
        import os
        os.environ.pop("CONCURRENT_POSITION_ALARM_ENABLED", None)
        m = _monitor()
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], True)
        assert m._log_alert.call_count == 1

    def test_disaster_pin_never_mutates_anything(self):
        """A tripwire that closes/blocks something is a disaster. The method
        may READ risk_alerts and call _log_alert — nothing else. No update,
        no insert, no delete on any table through its own client calls."""
        m = _monitor()
        m._one_beta_tripwire("u1", [_pos("a"), _pos("b")], True)
        chain = m.supabase.table.return_value
        assert not chain.update.called
        assert not chain.insert.called
        assert not chain.delete.called
        for call in m.supabase.table.call_args_list:
            assert call.args[0] == "risk_alerts"

    def test_immediate_egress_allowlisted(self):
        from packages.quantum.observability.alerts import (
            _RISK_EGRESS_ALERT_TYPES,
        )
        assert "concurrent_live_positions_uncontrolled" in _RISK_EGRESS_ALERT_TYPES

    def test_production_call_path_wired(self):
        """#1126 rule: the tripwire must be called from the monitor's run
        path (after the live-scope block), not sit as an orphan method."""
        import inspect
        from packages.quantum.jobs.handlers import intraday_risk_monitor as mod

        src = inspect.getsource(mod)
        anchor = src.find("_scope_ok = False")
        assert anchor != -1
        wired = src.find("self._one_beta_tripwire(", anchor)
        assert wired != -1 and (wired - anchor) < 1200, (
            "tripwire not wired into the run path near the scope block"
        )
