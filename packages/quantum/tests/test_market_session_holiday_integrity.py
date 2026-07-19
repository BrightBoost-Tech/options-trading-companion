"""F-A10-HOLIDAY — canonical market-session integrity (holidays + half-days).

The defect: ``jobs/handlers/utils.is_market_day()`` was WEEKDAY-ONLY while its
docstring falsely claimed the scheduler handled holidays. APScheduler's
CronTrigger fires mon–fri regardless of exchange holidays, so entry-suggestion
generation (suggestions_open / suggestions_close) and the live pre-submit
market-hours gate (brokers/safety_checks) ran on Thanksgiving, Labor Day, etc.

These tests inject at the CALENDAR SOURCE (the broker calendar fetch) and
assert TOP-LEVEL gating — never a source-string pin. The broker calendar is the
holiday/half-day oracle; the tests simulate its response (a row for a trading
day, ``[]`` for a closed day, an exception for an unreadable calendar).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from packages.quantum.services.market_session import (
    MarketCalendarUnavailable,
    MarketSession,
    get_market_session,
)
from packages.quantum.jobs.handlers import suggestions_open, suggestions_close
from packages.quantum.jobs.handlers.utils import is_market_day
from packages.quantum.brokers import safety_checks

UTC = timezone.utc
_ET = ZoneInfo("America/New_York")


# ── Broker-calendar fixtures: (start, end) -> rows ────────────────────────
def _cal_regular(start, end):
    return [{"date": start.isoformat(), "open": "09:30", "close": "16:00"}]


def _cal_always_open(start, end):
    # Wide session so is_open_at(real now) is deterministically True.
    return [{"date": start.isoformat(), "open": "00:00", "close": "23:59:59"}]


def _cal_early_close(start, end):
    return [{"date": start.isoformat(), "open": "09:30", "close": "13:00"}]


def _cal_closed(start, end):
    # Successful ZERO-row single-date query = non-trading day (weekend/holiday).
    return []


def _cal_unreadable(start, end):
    raise RuntimeError("alpaca calendar 503")


def _mock_alpaca(calendar_fn):
    client = MagicMock()
    client.get_calendar.side_effect = calendar_fn
    return client


# ─────────────────────────────────────────────────────────────────────────
# 1. get_market_session — the ONE session representation
# ─────────────────────────────────────────────────────────────────────────
class TestMarketSessionResolver(unittest.TestCase):
    def test_ordinary_weekday_opens_normally(self):
        s = get_market_session(datetime(2026, 6, 9, 15, 0, tzinfo=UTC),  # Tue
                               calendar_fn=_cal_regular)
        self.assertTrue(s.is_trading_day)
        self.assertFalse(s.is_early_close)
        self.assertEqual(s.open_at.hour, 9)
        self.assertEqual(s.open_at.minute, 30)
        self.assertEqual(s.close_at.hour, 16)

    def test_weekend_is_not_a_trading_day(self):
        # 2026-06-06 is a Saturday; the broker calendar returns no row.
        s = get_market_session(datetime(2026, 6, 6, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_closed)
        self.assertFalse(s.is_trading_day)
        self.assertIsNone(s.open_at)

    def test_thanksgiving_2026_11_26_holiday(self):
        # Thanksgiving is a THURSDAY (a weekday) — weekday logic would pass it;
        # the broker calendar returns [] so it is correctly a non-trading day.
        s = get_market_session(datetime(2026, 11, 26, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_closed)
        self.assertFalse(s.is_trading_day)

    def test_labor_day_2026_09_07_holiday(self):
        # Labor Day is a MONDAY (a weekday). Broker calendar [] → non-trading.
        s = get_market_session(datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_closed)
        self.assertFalse(s.is_trading_day)

    def test_early_close_2026_11_27_half_day(self):
        # Day after Thanksgiving — 13:00 ET early close.
        s = get_market_session(datetime(2026, 11, 27, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_early_close)
        self.assertTrue(s.is_trading_day)
        self.assertTrue(s.is_early_close)
        self.assertEqual(s.close_at.hour, 13)
        # Open before 13:00 ET, closed after — the early close is HONORED.
        self.assertTrue(s.is_open_at(datetime(2026, 11, 27, 12, 0, tzinfo=_ET)))
        self.assertFalse(s.is_open_at(datetime(2026, 11, 27, 13, 30, tzinfo=_ET)))

    def test_dst_boundary_summer_vs_winter_offset(self):
        # ET session is DST-correct with no offset arithmetic: EDT = -4h, EST = -5h.
        summer = get_market_session(datetime(2026, 6, 9, 15, 0, tzinfo=UTC),
                                    calendar_fn=_cal_regular)
        winter = get_market_session(datetime(2026, 1, 13, 15, 0, tzinfo=UTC),
                                    calendar_fn=_cal_regular)
        self.assertEqual(summer.open_at.utcoffset(), timedelta(hours=-4))
        self.assertEqual(winter.open_at.utcoffset(), timedelta(hours=-5))

    def test_calendar_source_failure_fails_closed(self):
        with self.assertRaises(MarketCalendarUnavailable):
            get_market_session(datetime(2026, 6, 9, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_unreadable)

    def test_no_broker_client_fails_closed(self):
        # _default_calendar_fn path: no Alpaca client (internal-paper / no creds)
        # is UNREADABLE for entries, not a silent "assume open".
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=None):
            with self.assertRaises(MarketCalendarUnavailable):
                get_market_session(datetime(2026, 6, 9, 15, 0, tzinfo=UTC))

    def test_trading_day_row_with_unparseable_bounds_fails_closed(self):
        # A trading-day row we cannot price is unreadable — never fabricate a
        # regular session (H9).
        def _bad(start, end):
            return [{"date": start.isoformat(), "open": "", "close": ""}]
        with self.assertRaises(MarketCalendarUnavailable):
            get_market_session(datetime(2026, 6, 9, 15, 0, tzinfo=UTC),
                               calendar_fn=_bad)

    def test_broker_calendar_wins_over_naive_weekday(self):
        # Documents the disagreement policy: the broker CALENDAR is the single
        # source of trading-day truth. On Labor Day (a Monday), naive weekday
        # logic says "trade" but the broker says closed — the BROKER wins.
        s = get_market_session(datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
                               calendar_fn=_cal_closed)
        self.assertEqual(s, MarketSession(session_date=s.session_date,
                                          is_trading_day=False))


# ─────────────────────────────────────────────────────────────────────────
# 2. is_market_day() — the shared entry gate, driven through the real route
# ─────────────────────────────────────────────────────────────────────────
class TestIsMarketDayRoute(unittest.TestCase):
    def test_broker_open_is_trading_day(self):
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=_mock_alpaca(_cal_regular)):
            ok, reason = is_market_day()
            self.assertTrue(ok)
            self.assertIn("trading_day", reason)

    def test_broker_closed_is_not_trading_day(self):
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=_mock_alpaca(_cal_closed)):
            ok, reason = is_market_day()
            self.assertFalse(ok)
            self.assertIn("market_closed", reason)

    def test_unreadable_calendar_raises_for_caller_to_fail_closed(self):
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=_mock_alpaca(_cal_unreadable)):
            with self.assertRaises(MarketCalendarUnavailable):
                is_market_day()


# ─────────────────────────────────────────────────────────────────────────
# 3. suggestions_open (ENTRY) — fail CLOSED on unreadable, skip holidays
# ─────────────────────────────────────────────────────────────────────────
class TestSuggestionsOpenEntryGating(unittest.TestCase):
    def _run(self, calendar_fn, active_users=None):
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=_mock_alpaca(calendar_fn)), \
             patch.object(suggestions_open, "run_midday_cycle") as cycle, \
             patch.object(suggestions_open, "get_admin_client",
                          return_value=MagicMock()), \
             patch.object(suggestions_open, "get_active_user_ids",
                          return_value=(active_users or [])):
            result = suggestions_open.run({})
            return result, cycle

    def test_holiday_fast_path_no_entries(self):
        result, cycle = self._run(_cal_closed)
        self.assertTrue(result["ok"])
        self.assertTrue(result["fast_path"])
        self.assertIn("market_closed", result["reason"])
        cycle.assert_not_called()

    def test_calendar_unreadable_fails_closed_typed_truth(self):
        result, cycle = self._run(_cal_unreadable)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("blocked"))
        self.assertEqual(result["counts"]["errors"], 1)  # runner → 'partial'
        self.assertIn("market_calendar_unavailable", result["reason"])
        cycle.assert_not_called()

    def test_trading_day_passes_the_gate(self):
        # Trading day + no active users → proceeds past the gate to the
        # no_active_users fast-path (proves the gate did NOT skip/fail-close).
        result, _ = self._run(_cal_regular, active_users=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "no_active_users")


# ─────────────────────────────────────────────────────────────────────────
# 4. suggestions_close (EXIT/management) — holiday-aware, but NEVER blocks
#    exits on a transient calendar outage (preserve always-ran semantics)
# ─────────────────────────────────────────────────────────────────────────
class TestSuggestionsCloseExitGating(unittest.TestCase):
    def _run(self, calendar_fn, active_users=None):
        with patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                   return_value=_mock_alpaca(calendar_fn)), \
             patch.object(suggestions_close, "run_morning_cycle") as cycle, \
             patch.object(suggestions_close, "get_admin_client",
                          return_value=MagicMock()), \
             patch.object(suggestions_close, "get_active_user_ids",
                          return_value=(active_users or [])):
            result = suggestions_close.run({})
            return result, cycle

    def test_holiday_skips_close_cycle(self):
        result, cycle = self._run(_cal_closed)
        self.assertTrue(result["ok"])
        self.assertTrue(result["fast_path"])
        self.assertIn("market_closed", result["reason"])
        cycle.assert_not_called()

    def test_calendar_unreadable_proceeds_not_blocked(self):
        # Exit path: a calendar outage must NOT skip exit management. With no
        # active users it reaches the no_active_users fast-path — proving it did
        # NOT return the market_closed skip.
        result, _ = self._run(_cal_unreadable, active_users=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "no_active_users")


# ─────────────────────────────────────────────────────────────────────────
# 5. safety_checks (LIVE pre-submit) — holiday/half-day aware, fail closed
# ─────────────────────────────────────────────────────────────────────────
class TestSafetyChecksMarketHours(unittest.TestCase):
    def _market_hours_check(self, calendar_fn):
        alpaca = MagicMock()
        alpaca.get_calendar.side_effect = calendar_fn
        alpaca.get_buying_power.return_value = 100000.0
        alpaca.get_day_trade_count.return_value = 0
        alpaca.is_pdt_restricted.return_value = False
        alpaca.get_account.return_value = {"equity": 100000.0}
        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
        order = {"requested_price": 1.0, "requested_qty": 1, "order_json": {}}
        result = safety_checks.run_pre_submit_checks(alpaca, supabase, order, "u1")
        return next(c for c in result["checks"] if c["name"] == "market_hours"), result

    def test_holiday_blocks_live_submit(self):
        check, result = self._market_hours_check(_cal_closed)
        self.assertFalse(check["passed"])
        self.assertFalse(result["approved"])
        self.assertIsNotNone(result["blocked_reason"])

    def test_calendar_unreadable_blocks_live_submit(self):
        check, result = self._market_hours_check(_cal_unreadable)
        self.assertFalse(check["passed"])
        self.assertIn("market_calendar_unavailable", check["detail"])
        self.assertFalse(result["approved"])

    def test_open_trading_day_passes_market_hours(self):
        # Wide-open session so the "open now" reading is deterministic.
        check, _ = self._market_hours_check(_cal_always_open)
        self.assertTrue(check["passed"])


# ─────────────────────────────────────────────────────────────────────────
# 6. ops-health holiday honesty — #1229 broker guard is LOAD-BEARING; a
#    broker-closed weekday must NOT produce false data_stale / job_late
# ─────────────────────────────────────────────────────────────────────────
class TestOpsHealthHolidayHonesty(unittest.TestCase):
    def test_broker_closed_holiday_reads_market_closed(self):
        from packages.quantum.services.ops_health_service import is_us_market_hours
        # Thanksgiving 2026-11-26, 15:00Z = 10:00 ET — RTH by wall clock.
        rth_holiday = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
        # Holiday-BLIND wall-clock alone would (wrongly) read OPEN on this weekday...
        self.assertTrue(is_us_market_hours(rth_holiday))
        # ...but the #1229 broker-authoritative closed reading makes it honest,
        # which is exactly what suppresses false data_stale / job_late alerts.
        self.assertFalse(is_us_market_hours(rth_holiday, broker_is_open=False))


if __name__ == "__main__":
    unittest.main()
