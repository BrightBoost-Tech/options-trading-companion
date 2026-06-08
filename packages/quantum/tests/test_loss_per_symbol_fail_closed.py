"""loss_per_symbol fail-closed on an unpriceable mark (#1035 extension).

The per-symbol loss envelope (check_loss_envelopes) reads pos['unrealized_pl'].
For a position whose mark was unpriceable this pass (_mark_unpriceable, set by
intraday_risk_monitor._refresh_marks), the old behavior would (a) act on the
STALE retained value or (b) — via _pos_field's `or 0` — coerce a None mark to
0 = no-breach = silent protection skip. Both are wrong: a phantom-profit mark
could mask a real loss.

Fix (mirrors #1035's stop_loss asymmetry): skip the position from the
per-symbol loss decision, record it in degraded_per_symbol, and have the
monitor raise a loud high-severity alert + retry next pass. Never act on a
stale/fabricated value; never silently skip protection.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.risk.risk_envelope import (  # noqa: E402
    check_loss_envelopes,
    check_all_envelopes,
    EnvelopeConfig,
)

EQUITY = 2300.0  # 3% per-symbol loss limit ≈ $69


def _pos(pos_id, unrealized_pl, unpriceable=False, symbol="NFLX"):
    p = {
        "id": pos_id, "symbol": symbol, "quantity": 2.0,
        "avg_entry_price": 3.08, "unrealized_pl": unrealized_pl,
        "portfolio_id": "pf-1",
    }
    if unpriceable:
        p["_mark_unpriceable"] = True
    return p


class TestCheckLossEnvelopesDegraded(unittest.TestCase):
    def _cfg(self):
        return EnvelopeConfig()

    def test_unpriceable_position_not_force_closed_and_recorded(self):
        # A genuine breach value (−$200) but the mark is unpriceable → must NOT
        # fire on the stale value; recorded as degraded instead.
        degraded = []
        violations, force_close, status = check_loss_envelopes(
            EQUITY, 0.0, 0.0, [_pos("p-unpx", -200.0, unpriceable=True)],
            self._cfg(), degraded_out=degraded,
        )
        self.assertEqual(force_close, [])  # not force-closed on a stale value
        self.assertEqual(
            [v for v in violations if v.envelope == "loss_per_symbol"], [])
        self.assertEqual(len(degraded), 1)
        self.assertEqual(degraded[0]["position_id"], "p-unpx")
        self.assertEqual(degraded[0]["stale_unrealized_pl"], -200.0)

    def test_priceable_breach_fires_byte_identical(self):
        # Clean mark at a real breach → fires exactly as before.
        degraded = []
        violations, force_close, status = check_loss_envelopes(
            EQUITY, 0.0, 0.0, [_pos("p-real", -200.0)],
            self._cfg(), degraded_out=degraded,
        )
        self.assertEqual(force_close, ["p-real"])
        loss_v = [v for v in violations if v.envelope == "loss_per_symbol"]
        self.assertEqual(len(loss_v), 1)
        self.assertEqual(degraded, [])

    def test_priceable_within_limit_does_not_fire(self):
        degraded = []
        violations, force_close, _ = check_loss_envelopes(
            EQUITY, 0.0, 0.0, [_pos("p-ok", -10.0)],
            self._cfg(), degraded_out=degraded,
        )
        self.assertEqual(force_close, [])
        self.assertEqual(degraded, [])

    def test_backward_compatible_without_degraded_out(self):
        # Legacy 3-tuple callers (no degraded_out) still work; the unpriceable
        # position is simply skipped (not force-closed on stale).
        violations, force_close, _ = check_loss_envelopes(
            EQUITY, 0.0, 0.0, [_pos("p-unpx", -200.0, unpriceable=True)],
            self._cfg(),
        )
        self.assertEqual(force_close, [])

    def test_check_all_envelopes_surfaces_degraded(self):
        result = check_all_envelopes(
            positions=[_pos("p-unpx", -200.0, unpriceable=True)],
            equity=EQUITY, daily_pnl=0.0, weekly_pnl=0.0, config=self._cfg(),
        )
        self.assertEqual(len(result.degraded_per_symbol), 1)
        self.assertEqual(result.degraded_per_symbol[0]["position_id"], "p-unpx")
        self.assertNotIn("p-unpx", result.force_close_ids)
        self.assertIn("degraded_per_symbol", result.to_dict())


class TestMonitorDegradedAlert(unittest.TestCase):
    def _monitor(self):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        m.supabase = MagicMock()
        return m

    def test_alert_raised_per_degraded_position(self):
        m = self._monitor()
        alerts = []
        m._log_alert = lambda **k: alerts.append(k)
        result = types.SimpleNamespace(degraded_per_symbol=[
            {"position_id": "p1", "symbol": "NFLX", "stale_unrealized_pl": -200.0},
            {"position_id": "p2", "symbol": "BAC", "stale_unrealized_pl": -50.0},
        ])
        n = m._alert_loss_per_symbol_degraded(result, "u1")
        self.assertEqual(n, 2)
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(
            a["alert_type"] == "loss_per_symbol_protection_degraded" for a in alerts))
        self.assertTrue(all(a["severity"] == "high" for a in alerts))
        self.assertEqual(alerts[0]["position_id"], "p1")

    def test_no_degraded_no_alert(self):
        m = self._monitor()
        alerts = []
        m._log_alert = lambda **k: alerts.append(k)
        result = types.SimpleNamespace(degraded_per_symbol=[])
        self.assertEqual(m._alert_loss_per_symbol_degraded(result, "u1"), 0)
        self.assertEqual(alerts, [])

    def test_alert_does_not_throw_on_none_field(self):
        m = self._monitor()
        m._log_alert = lambda **k: None
        result = types.SimpleNamespace(degraded_per_symbol=[
            {"position_id": None, "symbol": None, "stale_unrealized_pl": None},
        ])
        self.assertEqual(m._alert_loss_per_symbol_degraded(result, "u1"), 1)


if __name__ == "__main__":
    unittest.main()
