"""#1040 extension: cohort stop_loss force-closes bench the symbol (06-12).

The 06-12 SPY close: the 15-min monitor's COHORT stop (#1048) closed SPY at
15:30Z, but the #1040 cooldown writer fired only on per-symbol ENVELOPE
stops (result.symbol_loss_stops) — SPY was re-rankable at the 16:00Z scan
(whipsaw class, one layer up; manually benched that day). A stop is a stop:
cohort stop closes now write the same reentry_cooldowns row, same duration
convention (next session open), reason 'cohort_stop_force_close'.

target_profit and expiration_day closes do NOT bench — only stops do.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.jobs.handlers import intraday_risk_monitor as irm  # noqa: E402
from packages.quantum.services import reentry_cooldown as rc  # noqa: E402


def _spy_position():
    return {
        "id": "a5393e2b", "user_id": "u1", "symbol": "SPY",
        "quantity": -1.0, "avg_entry_price": 1.48, "max_credit": 1.48,
        "unrealized_pl": -48.0, "cohort_id": "3d289dca",
    }


def _monitor():
    m = irm.IntradayRiskMonitor.__new__(irm.IntradayRiskMonitor)
    m.supabase = MagicMock()
    return m


class TestCohortStopCooldownWriter(unittest.TestCase):
    def test_stop_close_writes_cooldown_row(self):
        m = _monitor()
        captured = {}

        def _fake_write(supabase, **kw):
            captured.update(kw)
            return True

        with patch.object(rc, "write_cooldown", side_effect=_fake_write), \
             patch.object(rc, "compute_cooldown_until",
                          return_value="2026-06-15T13:30:00+00:00"), \
             patch.object(rc, "is_enabled", return_value=True):
            ok = m._write_cohort_stop_cooldown(_spy_position(), "u1")

        self.assertTrue(ok)
        self.assertEqual(captured["symbol"], "SPY")
        self.assertEqual(captured["cohort_id"], "3d289dca")
        self.assertEqual(captured["reason"], "cohort_stop_force_close")
        self.assertEqual(captured["triggering_position_id"], "a5393e2b")
        self.assertEqual(captured["realized_loss"], -48.0)
        # same duration convention as the envelope writer
        self.assertEqual(captured["cooldown_until"], "2026-06-15T13:30:00+00:00")

    def test_kill_switch_respected(self):
        m = _monitor()
        with patch.object(rc, "is_enabled", return_value=False), \
             patch.object(rc, "write_cooldown") as w:
            self.assertFalse(m._write_cohort_stop_cooldown(_spy_position(), "u1"))
            w.assert_not_called()

    def test_write_failure_never_breaks_the_stop(self):
        m = _monitor()
        with patch.object(rc, "is_enabled", return_value=True), \
             patch.object(rc, "compute_cooldown_until", return_value="x"), \
             patch.object(rc, "write_cooldown", side_effect=RuntimeError("pg down")):
            self.assertFalse(m._write_cohort_stop_cooldown(_spy_position(), "u1"))


class TestWiring(unittest.TestCase):
    """The 5a force-close loop benches stops — and ONLY stops."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.src = (
            Path(__file__).parent.parent
            / "jobs" / "handlers" / "intraday_risk_monitor.py"
        ).read_text(encoding="utf-8")

    def test_stop_loss_close_calls_writer(self):
        idx = self.src.find('if reason == "stop_loss":')
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 120]
        self.assertIn("_write_cohort_stop_cooldown(pos, user_id)", block)

    def test_gated_on_stop_reason_only(self):
        # the call must be inside the stop_loss conditional — exactly one
        # call site, immediately after the reason check
        self.assertEqual(self.src.count("_write_cohort_stop_cooldown(pos"), 1)


class TestGateExcludesBenchedSymbol(unittest.TestCase):
    """The row this writer produces is exactly what the stage gate blocks:
    an active (cohort_id, symbol, cooldown_until>now) row → staging raises
    SymbolCooldownActive (the same reader the envelope-stop rows use —
    reason is not part of the filter)."""

    def test_active_row_blocks(self):
        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.gt.return_value.limit.return_value.execute \
            .return_value.data = [
                {"id": "cd-1", "cooldown_until": "2026-06-15T13:30:00+00:00"}
            ]
        self.assertTrue(rc.is_active(supabase, "3d289dca", "SPY"))


if __name__ == "__main__":
    unittest.main()
