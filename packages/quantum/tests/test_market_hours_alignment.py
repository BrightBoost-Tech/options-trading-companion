"""Market-hours ET alignment — regression tests for the CT-shifted schedule.

The bug (2026-06-05 detection-failure diagnostic): the daily schedule was
the ET session transcribed as CT numbers, one hour late relative to the
market —
  - the monitor's _is_market_open used 9:30-16:00 *Chicago* → effective
    window 14:30-21:00Z vs the real 13:30-20:00Z: BLIND for the first hour
    of every session (the −$202 NFLX excursion happened there, unseen) and
    a phantom post-close hour;
  - the cron (hour="9-16" CT) didn't even fire before 14:00Z;
  - the morning exit-eval ran at 8:15 CT = 9:15 ET, PRE-OPEN, on
    stale/closing marks — a structural no-op for price-based exits;
  - the afternoon exit-eval ran at 15:00 CT = 16:00 ET, AT the closing
    bell — staged exits had zero time to fill.

The fix (timing/gating only — no exit logic touched): broker-authoritative
get_clock() gate with a CORRECT America/New_York wall-clock fallback (never
the CT numbers); cron windows shifted to cover the real session; morning
eval → 8:35 CT (9:35 ET, post-open); afternoon eval → 14:45 CT (15:45 ET).
"""

import os
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

from packages.quantum.jobs.handlers.intraday_risk_monitor import (
    IntradayRiskMonitor,
    _fallback_is_market_open_et,
)

UTC = ZoneInfo("UTC")


def _dt(s: str) -> datetime:
    """'2026-06-09 13:45' → aware UTC datetime (a Tuesday unless noted)."""
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestEtFallback(unittest.TestCase):
    """The degraded-mode wall-clock check: America/New_York, 9:30-16:00 ET."""

    def test_regression_first_hour_is_open(self):
        """13:45Z in June = 9:45 ET — OPEN. The old CT code (9:45 ET read
        as 8:45 'CT-market-time') returned False: the blind hour."""
        self.assertTrue(_fallback_is_market_open_et(_dt("2026-06-09 13:45")))

    def test_regression_phantom_post_close_hour_is_closed(self):
        """20:30Z in June = 16:30 ET — CLOSED. The old CT code (15:30 CT)
        returned True: the phantom hour."""
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-06-09 20:30")))

    def test_open_at_the_bell(self):
        self.assertTrue(_fallback_is_market_open_et(_dt("2026-06-09 13:30")))

    def test_pre_open_closed(self):
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-06-09 13:00")))

    def test_close_boundary(self):
        self.assertTrue(_fallback_is_market_open_et(_dt("2026-06-09 20:00")))
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-06-09 20:01")))

    def test_weekend_closed(self):
        # 2026-06-06 is a Saturday
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-06-06 15:00")))

    def test_dst_winter_offsets(self):
        """EST (winter): open = 14:30Z. The session is defined in ET, so the
        ET check is DST-safe with no offset arithmetic."""
        # 2026-01-13 is a Tuesday
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-01-13 14:00")))  # 9:00 EST
        self.assertTrue(_fallback_is_market_open_et(_dt("2026-01-13 14:45")))   # 9:45 EST
        self.assertTrue(_fallback_is_market_open_et(_dt("2026-01-13 20:55")))   # 15:55 EST
        self.assertFalse(_fallback_is_market_open_et(_dt("2026-01-13 21:05")))  # 16:05 EST


class TestBrokerClockGate(unittest.TestCase):
    """_is_market_open: broker clock primary, ET fallback on error."""

    def _monitor(self):
        return IntradayRiskMonitor.__new__(IntradayRiskMonitor)

    def test_clock_open(self):
        client = MagicMock()
        client.get_market_clock.return_value = {
            "is_open": True, "next_open": "x", "next_close": "y", "timestamp": "t",
        }
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=client,
        ):
            self.assertTrue(self._monitor()._is_market_open())

    def test_clock_closed(self):
        client = MagicMock()
        client.get_market_clock.return_value = {
            "is_open": False, "next_open": "x", "next_close": "y", "timestamp": "t",
        }
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=client,
        ):
            self.assertFalse(self._monitor()._is_market_open())

    def test_clock_error_falls_back_to_et_not_ct(self):
        """Clock API down → the ET fallback decides (and the monitor stays
        live during the session). Sentinel-patch the fallback to prove the
        error path routes through it."""
        client = MagicMock()
        client.get_market_clock.side_effect = RuntimeError("clock api down")
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=client,
        ), patch(
            "packages.quantum.jobs.handlers.intraday_risk_monitor._fallback_is_market_open_et",
            return_value=True,
        ) as fb:
            self.assertTrue(self._monitor()._is_market_open())
            fb.assert_called_once()

    def test_clock_cached_within_ttl(self):
        client = MagicMock()
        client.get_market_clock.return_value = {
            "is_open": True, "next_open": "x", "next_close": "y", "timestamp": "t",
        }
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=client,
        ):
            m = self._monitor()
            self.assertTrue(m._is_market_open())
            self.assertTrue(m._is_market_open())
        self.assertEqual(client.get_market_clock.call_count, 1)


class TestScheduleExpressions(unittest.TestCase):
    """Source-level pins on scheduler.py (no module import — the scheduler
    module has runtime side effects)."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(
            os.path.dirname(__file__), "..", "scheduler.py"
        )
        with open(path, "r", encoding="utf-8") as f:
            cls.src = f.read()

    def test_monitor_cron_covers_the_open(self):
        # */15 cadence KEPT; hours shifted to cover 8:30 CT (9:30 ET) open.
        self.assertIn(
            '("intraday_risk_monitor",       dict(minute="*/15", hour="8-15")',
            self.src,
        )
        self.assertNotIn('intraday_risk_monitor",       dict(minute="*/15", hour="9-16")', self.src)

    def test_order_sync_cron_covers_the_open(self):
        self.assertIn(
            '("alpaca_order_sync",           dict(minute="*/5", hour="8-15")',
            self.src,
        )

    def test_morning_eval_after_the_open(self):
        # 8:35 CT = 9:35 ET — post-open, fresh marks for price-based exits.
        self.assertIn(
            '("paper_exit_evaluate_morning",  dict(hour=8,  minute=35)',
            self.src,
        )
        self.assertNotIn('paper_exit_evaluate_morning",  dict(hour=8,  minute=15)', self.src)

    def test_afternoon_eval_before_the_bell(self):
        # 14:45 CT = 15:45 ET — staged exits get 15 min to fill.
        self.assertIn(
            '("paper_exit_evaluate_afternoon", dict(hour=14, minute=45)',
            self.src,
        )

    def test_mark_to_market_still_after_afternoon_eval(self):
        # Dependency order preserved: afternoon eval (14:45) < MTM (15:30).
        self.assertIn('("paper_mark_to_market",        dict(hour=15, minute=30)', self.src)


class TestClockWrapper(unittest.TestCase):
    def test_get_market_clock_shape(self):
        from packages.quantum.brokers.alpaca_client import AlpacaClient

        client = AlpacaClient.__new__(AlpacaClient)
        clk = types.SimpleNamespace(
            is_open=True, next_open="2026-06-08T13:30:00Z",
            next_close="2026-06-05T20:00:00Z", timestamp="2026-06-05T17:00:00Z",
        )
        client._client = MagicMock()
        client._call_with_retry = lambda fn: clk
        out = client.get_market_clock()
        self.assertEqual(out["is_open"], True)
        self.assertIn("next_open", out)
        self.assertIn("next_close", out)


if __name__ == "__main__":
    unittest.main()
