"""F-CAL-DATETIME-BOUNDS — SDK datetime calendar bounds must be readable.

Incident (2026-07-20, mid-session): ``suggestions_open`` fail-closed on a valid
trading Monday with two forced-partial jobs (df3c56e9 / 25a96ae6),
``counts.errors=1``, reason ``market_calendar_unavailable`` on a space-separated
``'2026-07-20 09:30:00'`` bound. Root cause: the alpaca-py ``Calendar`` model
returns ``.open``/``.close`` as (naive ET) ``datetime`` objects whose ``str()``
is space-separated (``'2026-07-20 09:30:00'``); ``AlpacaClient.get_calendar``
``str()``'d them and ``market_session._parse_session_time`` accepted only
``HH:MM``/``HH:MM:SS`` or a ``'T'``-ISO datetime — the space form matched
NEITHER → ``None`` → ``MarketCalendarUnavailable`` → entry gate fail-closed.

The fix is two layers over ONE parsing authority (``_parse_session_time``):
(A) the parser accepts ``datetime`` / ``time`` objects and BOTH ``'T'``- and
space-separated ISO strings (aware→ET, naive→ET wall-time); (B) the broker
wrapper normalizes through the SAME helper and emits bare ``'HH:MM'`` strings.

These tests inject at the SDK/client boundary (not the parser) and assert
TOP-LEVEL behavior through the real route — no source-string pins.
"""

import sys
import types
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from packages.quantum.services.market_session import (
    MarketCalendarUnavailable,
    _parse_session_time,
    get_market_session,
    normalize_session_bound,
)
from packages.quantum.jobs.handlers import suggestions_open

UTC = timezone.utc
_ET = ZoneInfo("America/New_York")
# A known TRADING Monday used for the resolver-level cases (12:00 ET).
_MON = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────────
# 1. _parse_session_time — the ONE parsing authority, every accepted shape
# ─────────────────────────────────────────────────────────────────────────
class TestParseSessionTime(unittest.TestCase):
    def test_naive_datetime_is_et_wallclock_not_utc(self):
        # A naive SDK datetime's clock fields ARE the ET session wall-time —
        # they must NOT be reinterpreted as UTC (that would shift 09:30 → 05:30).
        self.assertEqual(_parse_session_time(datetime(2026, 7, 20, 9, 30)), time(9, 30))

    def test_aware_datetime_converts_to_et(self):
        # 13:30 UTC in July == 09:30 EDT — conversion must happen, not passthrough.
        aware = datetime(2026, 7, 20, 13, 30, tzinfo=UTC)
        self.assertEqual(_parse_session_time(aware), time(9, 30))

    def test_aware_datetime_already_et(self):
        aware = datetime(2026, 7, 20, 9, 30, tzinfo=_ET)
        self.assertEqual(_parse_session_time(aware), time(9, 30))

    def test_time_object_passthrough(self):
        self.assertEqual(_parse_session_time(time(9, 30)), time(9, 30))

    def test_space_separated_string(self):
        # THE regression shape.
        self.assertEqual(_parse_session_time("2026-07-20 09:30:00"), time(9, 30))

    def test_t_separated_string(self):
        self.assertEqual(_parse_session_time("2026-07-20T09:30:00"), time(9, 30))

    def test_offset_aware_string_converts_to_et(self):
        # -04:00 == EDT for July → 09:30 ET.
        self.assertEqual(_parse_session_time("2026-07-20T09:30:00-04:00"), time(9, 30))

    def test_utc_offset_string_converts_to_et(self):
        # +00:00 (UTC) 13:30 in July → 09:30 ET (conversion via the string path).
        self.assertEqual(_parse_session_time("2026-07-20T13:30:00+00:00"), time(9, 30))
        # ...and the trailing-Z spelling of the same instant.
        self.assertEqual(_parse_session_time("2026-07-20T13:30:00Z"), time(9, 30))

    def test_bare_hh_mm(self):
        self.assertEqual(_parse_session_time("09:30"), time(9, 30))

    def test_bare_hh_mm_ss(self):
        self.assertEqual(_parse_session_time("09:30:00"), time(9, 30))

    def test_fractional_seconds_space_string(self):
        self.assertEqual(_parse_session_time("2026-07-20 09:30:00.000"), time(9, 30))

    def test_fractional_seconds_bare(self):
        # Fractional seconds are ACCEPTED (never a parse failure) and preserved on
        # the time; real session bounds are on-the-minute so this is inert, and
        # normalize_session_bound renders it cleanly (see below).
        self.assertEqual(_parse_session_time("09:30:00.500"), time(9, 30, 0, 500000))
        self.assertEqual(normalize_session_bound("09:30:00.500"), "09:30:00")
        # On-the-minute fractional (.000) collapses to a clean minute time.
        self.assertEqual(_parse_session_time("09:30:00.000"), time(9, 30))

    def test_early_close_1300(self):
        self.assertEqual(_parse_session_time("13:00"), time(13, 0))
        self.assertEqual(_parse_session_time("2026-07-20 13:00:00"), time(13, 0))

    def test_malformed_returns_none(self):
        self.assertIsNone(_parse_session_time("garbage"))

    def test_date_only_string_returns_none(self):
        # A date with no time component must NEVER become a midnight session.
        self.assertIsNone(_parse_session_time("2026-07-20"))

    def test_bare_date_object_returns_none(self):
        self.assertIsNone(_parse_session_time(date(2026, 7, 20)))

    def test_none_and_empty_return_none(self):
        self.assertIsNone(_parse_session_time(None))
        self.assertIsNone(_parse_session_time(""))
        self.assertIsNone(_parse_session_time("   "))


# ─────────────────────────────────────────────────────────────────────────
# 2. normalize_session_bound — the wrapper normalizer (bare-time strings)
# ─────────────────────────────────────────────────────────────────────────
class TestNormalizeSessionBound(unittest.TestCase):
    def test_datetime_to_bare_hh_mm(self):
        self.assertEqual(normalize_session_bound(datetime(2026, 7, 20, 9, 30)), "09:30")

    def test_space_string_to_bare_hh_mm(self):
        self.assertEqual(normalize_session_bound("2026-07-20 16:00:00"), "16:00")

    def test_time_object_to_bare_hh_mm(self):
        self.assertEqual(normalize_session_bound(time(16, 0)), "16:00")

    def test_early_close_to_bare(self):
        self.assertEqual(normalize_session_bound("2026-07-20 13:00:00"), "13:00")

    def test_nonzero_seconds_keep_hh_mm_ss(self):
        self.assertEqual(normalize_session_bound(time(9, 30, 15)), "09:30:15")

    def test_malformed_returns_none(self):
        self.assertIsNone(normalize_session_bound("garbage"))

    def test_date_only_returns_none(self):
        self.assertIsNone(normalize_session_bound("2026-07-20"))


# ─────────────────────────────────────────────────────────────────────────
# 3. get_market_session — the regression shape through the resolver
# ─────────────────────────────────────────────────────────────────────────
class TestResolverAcceptsDatetimeBounds(unittest.TestCase):
    @staticmethod
    def _cal(open_val, close_val):
        def _fn(start, end):
            return [{"date": start.isoformat(), "open": open_val, "close": close_val}]
        return _fn

    def test_space_separated_bounds_open_normally(self):
        s = get_market_session(_MON, calendar_fn=self._cal(
            "2026-07-20 09:30:00", "2026-07-20 16:00:00"))
        self.assertTrue(s.is_trading_day)
        self.assertFalse(s.is_early_close)
        self.assertEqual((s.open_at.hour, s.open_at.minute), (9, 30))
        self.assertEqual(s.close_at.hour, 16)

    def test_naive_datetime_bounds_open_normally(self):
        s = get_market_session(_MON, calendar_fn=self._cal(
            datetime(2026, 7, 20, 9, 30), datetime(2026, 7, 20, 16, 0)))
        self.assertTrue(s.is_trading_day)
        self.assertEqual((s.open_at.hour, s.open_at.minute), (9, 30))

    def test_early_close_datetime_bounds(self):
        s = get_market_session(_MON, calendar_fn=self._cal(
            "2026-07-20 09:30:00", "2026-07-20 13:00:00"))
        self.assertTrue(s.is_trading_day)
        self.assertTrue(s.is_early_close)
        self.assertEqual(s.close_at.hour, 13)

    def test_malformed_bounds_still_fail_closed(self):
        with self.assertRaises(MarketCalendarUnavailable):
            get_market_session(_MON, calendar_fn=self._cal("garbage", "nonsense"))

    def test_date_only_bounds_still_fail_closed(self):
        with self.assertRaises(MarketCalendarUnavailable):
            get_market_session(_MON, calendar_fn=self._cal("2026-07-20", "2026-07-20"))


# ── Fake alpaca-py SDK boundary (hermetic: the SDK is not installed locally) ──
def _install_sdk_stub():
    """patch.dict target: a minimal ``alpaca.trading.requests.GetCalendarRequest``
    that records start/end so the fake SDK client can echo the requested date."""

    class _StubReq:
        def __init__(self, start=None, end=None):
            self.start = start
            self.end = end

    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    requests = types.ModuleType("alpaca.trading.requests")
    requests.GetCalendarRequest = _StubReq
    return {
        "alpaca": alpaca,
        "alpaca.trading": trading,
        "alpaca.trading.requests": requests,
    }


def _sdk_row(d, open_val, close_val):
    return types.SimpleNamespace(date=d, open=open_val, close=close_val)


def _make_wrapper(sdk_get_calendar):
    """Build a REAL AlpacaClient (bypassing __init__/creds/SDK auth) with a fake
    underlying SDK ``._client``; the real ``get_calendar`` wrapper + retry run."""
    from packages.quantum.brokers.alpaca_client import AlpacaClient

    client = AlpacaClient.__new__(AlpacaClient)
    sdk = MagicMock()
    sdk.get_calendar.side_effect = sdk_get_calendar
    client._client = sdk
    return client


# ─────────────────────────────────────────────────────────────────────────
# 4. AlpacaClient.get_calendar — the REAL wrapper honors its bare-time contract
# ─────────────────────────────────────────────────────────────────────────
class TestBrokerWrapperContract(unittest.TestCase):
    def _run_wrapper(self, open_val, close_val, d=date(2026, 7, 20)):
        with patch.dict(sys.modules, _install_sdk_stub()):
            client = _make_wrapper(lambda req: [_sdk_row(d, open_val, close_val)])
            return client.get_calendar(d, d)

    def test_datetime_bounds_normalize_to_bare_et(self):
        rows = self._run_wrapper(datetime(2026, 7, 20, 9, 30), datetime(2026, 7, 20, 16, 0))
        self.assertEqual(rows, [{"date": "2026-07-20", "open": "09:30", "close": "16:00"}])

    def test_space_string_bounds_normalize_to_bare_et(self):
        rows = self._run_wrapper("2026-07-20 09:30:00", "2026-07-20 16:00:00")
        self.assertEqual(rows[0]["open"], "09:30")
        self.assertEqual(rows[0]["close"], "16:00")

    def test_time_object_bounds_normalize_to_bare_et(self):
        rows = self._run_wrapper(time(9, 30), time(16, 0))
        self.assertEqual(rows[0]["open"], "09:30")
        self.assertEqual(rows[0]["close"], "16:00")

    def test_early_close_normalizes(self):
        rows = self._run_wrapper(datetime(2026, 7, 20, 9, 30), datetime(2026, 7, 20, 13, 0))
        self.assertEqual(rows[0]["close"], "13:00")

    def test_unnormalizable_bound_passes_raw_diagnostic(self):
        # A bound the helper cannot read keeps its raw stringified value so the
        # resolver still fails CLOSED with the bad value visible — never a
        # fabricated time.
        rows = self._run_wrapper("garbage", "nonsense")
        self.assertEqual(rows[0]["open"], "garbage")
        self.assertEqual(rows[0]["close"], "nonsense")

    def test_empty_sdk_rows_stay_empty(self):
        with patch.dict(sys.modules, _install_sdk_stub()):
            client = _make_wrapper(lambda req: [])
            self.assertEqual(client.get_calendar(date(2026, 7, 20), date(2026, 7, 20)), [])


# ─────────────────────────────────────────────────────────────────────────
# 5. END-TO-END entry gate: REAL wrapper → get_market_session → is_market_day
#    → suggestions_open.run, driven by a SPACE-separated valid Monday row.
# ─────────────────────────────────────────────────────────────────────────
class TestSuggestionsOpenEndToEnd(unittest.TestCase):
    @staticmethod
    def _today_et():
        return datetime.now(timezone.utc).astimezone(_ET).date()

    def _space_row_sdk(self, open_t="09:30:00", close_t="16:00:00"):
        # Echo the REQUESTED date (get_market_session queries today's ET date), so
        # the row always matches regardless of when the suite runs. Bounds are the
        # space-separated SDK-datetime str() form — the incident shape.
        def _fn(req):
            d = req.start
            return [_sdk_row(d, f"{d.isoformat()} {open_t}", f"{d.isoformat()} {close_t}")]
        return _fn

    def _drive(self, sdk_get_calendar, active_users):
        cycle = AsyncMock(return_value={"executed": "sentinel"})
        stack = [
            patch.dict(sys.modules, _install_sdk_stub()),
            patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                  return_value=_make_wrapper(sdk_get_calendar)),
            patch.object(suggestions_open, "get_admin_client", return_value=MagicMock()),
            patch.object(suggestions_open, "get_active_user_ids", return_value=active_users),
            patch.object(suggestions_open, "run_midday_cycle", cycle),
            patch.object(suggestions_open, "ensure_default_strategy_exists"),
            patch.object(suggestions_open, "load_strategy_config", return_value={"version": 1}),
            patch.object(suggestions_open, "_get_decision_context_class", return_value=None),
            patch("packages.quantum.policy_lab.config.is_policy_lab_enabled",
                  return_value=False),
            patch("packages.quantum.risk.staleness_gate.check_staleness_gate",
                  return_value=types.SimpleNamespace(blocked=False, reason="", age_seconds=0,
                                                     stale_symbols=[])),
        ]
        for p in stack:
            p.start()
        try:
            return suggestions_open.run({}), cycle
        finally:
            for p in reversed(stack):
                p.stop()

    def test_space_row_no_active_users_passes_calendar_gate(self):
        # No active users → proceeds PAST the calendar gate to the
        # no_active_users fast-path. Proves the gate did NOT fail-close on the
        # space-separated bounds (the regression).
        result, cycle = self._drive(self._space_row_sdk(), active_users=[])
        self.assertNotIn("market_calendar_unavailable", str(result.get("reason", "")))
        self.assertFalse(result.get("blocked", False))
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "no_active_users")
        cycle.assert_not_awaited()

    def test_space_row_active_user_invokes_midday_cycle(self):
        # With a stub active user the real route reaches run_midday_cycle (mocked
        # to a no-op sentinel — no real scan).
        result, cycle = self._drive(self._space_row_sdk(),
                                    active_users=["11111111-2222-3333-4444-555555555555"])
        self.assertFalse(result.get("blocked", False))
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["processed"], 1)
        self.assertEqual(result["counts"]["errors"], 0)
        cycle.assert_awaited_once()

    def test_early_close_space_row_still_trades(self):
        result, cycle = self._drive(self._space_row_sdk(close_t="13:00:00"), active_users=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "no_active_users")

    def test_empty_calendar_is_ordinary_non_trading_fast_path(self):
        # Holiday/weekend [] → ordinary non-trading fast path (ok, market_closed),
        # NOT the fail-closed blocked path.
        result, cycle = self._drive(lambda req: [], active_users=[])
        self.assertTrue(result["ok"])
        self.assertTrue(result["fast_path"])
        self.assertIn("market_closed", result["reason"])
        self.assertFalse(result.get("blocked", False))
        cycle.assert_not_awaited()

    def test_malformed_row_still_fails_closed_typed_truth(self):
        # A genuinely malformed trading-day row still fails CLOSED through the
        # real two-layer route: wrapper passes the raw diagnostic, resolver
        # raises, suggestions_open surfaces counts.errors=1 + blocked.
        def _bad(req):
            d = req.start
            return [_sdk_row(d, "garbage", "nonsense")]
        result, cycle = self._drive(_bad, active_users=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("blocked"))
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertIn("market_calendar_unavailable", result["reason"])
        cycle.assert_not_awaited()

    def test_broker_exception_fails_closed_typed_truth(self):
        # A real broker-calendar EXCEPTION (non-transient → no retry backoff) →
        # wrapper raises → resolver → MarketCalendarUnavailable → typed partial.
        def _boom(req):
            raise ValueError("synthetic calendar read failure")
        result, cycle = self._drive(_boom, active_users=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("blocked"))
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertIn("market_calendar_unavailable", result["reason"])
        cycle.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
