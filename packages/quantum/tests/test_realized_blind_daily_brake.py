"""v5-A2 realized-blind daily brake (N1, 2026-06-11).

The daily-loss envelope's feeders computed daily_pnl as the OPEN-book
unrealized sum — blind to realized losses and fees (a closed losing trade
vanishes from the sum). Empirical 06-11: broker-true day was −$188 (−8.3%,
equity 2075.42 vs last_equity 2263.85) while the proxy read ≈−4%; and the
autopilot circuit breaker (a) never fed weekly_pnl at all and (b) skipped
the entire check on an empty book — so a session that force-closes the book
on a real −8% day would have waved fresh entries straight back in.

Pins:
- equity_state.get_alpaca_daily_pnl: broker equity − last_equity,
  None-preserving (missing field / non-positive / API failure → None).
- equity_state.tightened_daily_pnl: min(proxy, broker) — TIGHTENS ONLY.
  Broker more negative → broker (the 06-11 realized-blind case). Proxy more
  negative → proxy (the phantom-mark case keeps its existing severity —
  behavior is never loosened). Broker None → proxy unchanged.
- All four check_all_envelopes feeders route through tightened_daily_pnl;
  the circuit breaker feeds weekly_pnl and runs on an EMPTY book.
- check_all_envelopes itself fires the daily envelope with positions=[].
Scope guard: per-symbol loss envelope, #1040 cooldown, stop-loss — untouched.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py per convention.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services import equity_state  # noqa: E402


def _mock_alpaca(account: dict):
    client = MagicMock()
    client.get_account.return_value = account
    return client


# The actual 06-11 EOD account numbers.
ACCT_0611 = {"equity": "2075.42", "last_equity": "2263.85"}


class TestGetAlpacaDailyPnl(unittest.TestCase):
    def setUp(self):
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    def test_broker_true_day_pnl_0611_fixture(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca(ACCT_0611),
        ):
            self.assertAlmostEqual(
                equity_state.get_alpaca_daily_pnl("u1"), -188.43, places=2
            )

    def test_missing_last_equity_is_none_preserving(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca({"equity": "2075.42"}),
        ):
            self.assertIsNone(equity_state.get_alpaca_daily_pnl("u1"))

    def test_nonpositive_equity_is_none(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca({"equity": "0", "last_equity": "2263.85"}),
        ):
            self.assertIsNone(equity_state.get_alpaca_daily_pnl("u1"))

    def test_api_failure_is_none(self):
        broken = MagicMock()
        broken.get_account.side_effect = RuntimeError("api down")
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=broken,
        ):
            self.assertIsNone(equity_state.get_alpaca_daily_pnl("u1"))

    def test_client_unavailable_is_none(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            self.assertIsNone(equity_state.get_alpaca_daily_pnl("u1"))


class TestTightenedDailyPnl(unittest.TestCase):
    def setUp(self):
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    def test_broker_more_negative_wins_the_0611_case(self):
        """Proxy −97 (open-book mid marks) vs broker −188.43 → −188.43.
        This is the exact gap the 19:00Z session showed."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca(ACCT_0611),
        ):
            self.assertAlmostEqual(
                equity_state.tightened_daily_pnl("u1", -97.0), -188.43, places=2
            )

    def test_proxy_more_negative_wins_tightens_only(self):
        """The 16:30Z phantom-mark case: proxy −557 vs broker −80 → −557.
        Existing behavior is NEVER loosened; the broker value is not a
        relaxation valve."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca({"equity": "2183.85", "last_equity": "2263.85"}),
        ):
            self.assertAlmostEqual(
                equity_state.tightened_daily_pnl("u1", -557.0), -557.0, places=2
            )

    def test_broker_unavailable_falls_back_to_proxy(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            self.assertEqual(equity_state.tightened_daily_pnl("u1", -42.0), -42.0)

    def test_gap_logs_loud(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca(ACCT_0611),
        ):
            with self.assertLogs(
                "packages.quantum.services.equity_state", level="WARNING"
            ) as cm:
                equity_state.tightened_daily_pnl("u1", -97.0)
        self.assertTrue(any("realized-blind gap" in m for m in cm.output))


class _FakeSdkAccount:
    """Shape of alpaca-py's TradeAccount as the wrapper consumes it:
    attribute access, numeric fields as strings (the real API returns
    JSON strings). Mirrors only the fields get_account() reads."""

    def __init__(self, equity="2075.42", last_equity="2263.85"):
        self.id = "904837e3-0000-0000-0000-000000000000"
        self.status = "ACTIVE"
        self.equity = equity
        self.last_equity = last_equity
        self.cash = "500.00"
        self.buying_power = "1000.00"
        self.options_buying_power = "525.39"
        self.portfolio_value = equity
        self.pattern_day_trader = False
        self.daytrade_count = 0
        self.daytrading_buying_power = "0"


class TestWrapperPayloadShape(unittest.TestCase):
    """2026-06-12 regression: the original tests mocked get_account()
    as a dict CONTAINING last_equity — a shape the real wrapper never
    produced (AlpacaClient.get_account() returns a curated dict and the
    key was absent). CI green, production 100% 'unavailable'. These
    tests route through the REAL wrapper so the payload contract is
    pinned where it lives."""

    def setUp(self):
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    @staticmethod
    def _real_wrapper(sdk_account):
        """AlpacaClient with __init__ bypassed (no SDK/network), real
        get_account()/_call_with_retry code paths."""
        from packages.quantum.brokers.alpaca_client import AlpacaClient
        client = object.__new__(AlpacaClient)
        client.paper = True
        client._client = MagicMock()
        client._client.get_account.return_value = sdk_account
        return client

    def test_get_account_payload_contains_last_equity(self):
        payload = self._real_wrapper(_FakeSdkAccount()).get_account()
        self.assertIn("last_equity", payload)
        self.assertAlmostEqual(payload["last_equity"], 2263.85, places=2)
        self.assertAlmostEqual(payload["equity"], 2075.42, places=2)

    def test_get_account_last_equity_none_preserving(self):
        payload = self._real_wrapper(
            _FakeSdkAccount(last_equity=None)
        ).get_account()
        self.assertIn("last_equity", payload)
        self.assertIsNone(payload["last_equity"])

    def test_daily_pnl_through_real_wrapper_payload(self):
        """End-to-end pin: wrapper output → get_alpaca_daily_pnl.
        This exact composition is what was broken in production."""
        wrapper = self._real_wrapper(_FakeSdkAccount())
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=wrapper,
        ):
            self.assertAlmostEqual(
                equity_state.get_alpaca_daily_pnl("u1"), -188.43, places=2
            )

    def test_missing_field_logs_contract_violation_not_outage(self):
        """The silent-None path must name the missing field loudly —
        a wrapper-contract code bug is not a broker outage."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=_mock_alpaca({"equity": "2075.42"}),
        ):
            with self.assertLogs(
                "packages.quantum.services.equity_state", level="WARNING"
            ) as cm:
                self.assertIsNone(equity_state.get_alpaca_daily_pnl("u1"))
        self.assertTrue(
            any("missing 'last_equity'" in m for m in cm.output)
        )
        self.assertTrue(
            any("contract violation" in m for m in cm.output)
        )


class TestEmptyBookEnvelope(unittest.TestCase):
    def test_daily_envelope_fires_with_no_positions(self):
        """positions=[] must not silence the daily-loss envelope: a real
        −8.3% day breaches the −8% cap even after the book emptied."""
        from packages.quantum.risk.risk_envelope import (
            check_all_envelopes,
            EnvelopeConfig,
        )
        config = EnvelopeConfig.from_env()
        result = check_all_envelopes(
            positions=[],
            equity=2075.42,
            daily_pnl=-188.43,
            config=config,
        )
        daily = [v for v in result.violations if v.envelope == "loss_daily"]
        self.assertEqual(len(daily), 1)


class TestFeedersRouted(unittest.TestCase):
    """Source pins: all four production feeders run the brake; the circuit
    breaker feeds weekly and no longer skips on an empty book."""

    def _src(self, module_path):
        from pathlib import Path
        root = Path(__file__).parent.parent
        return (root / module_path).read_text(encoding="utf-8")

    def test_intraday_risk_monitor(self):
        src = self._src("jobs/handlers/intraday_risk_monitor.py")
        self.assertIn("tightened_daily_pnl(", src)

    def test_paper_mark_to_market(self):
        src = self._src("jobs/handlers/paper_mark_to_market.py")
        self.assertIn("tightened_daily_pnl(", src)
        # empty-book: equity fetched unconditionally at this site
        self.assertNotIn("if open_positions else None", src)

    def test_paper_autopilot_circuit_breaker(self):
        src = self._src("services/paper_autopilot_service.py")
        self.assertIn("tightened_daily_pnl(", src)
        self.assertIn("weekly_pnl=cb_weekly_pnl", src)
        # empty-book: the breaker must not gate equity fetch on positions
        self.assertNotIn("if cb_positions else None", src)

    def test_workflow_orchestrator_observe_site(self):
        src = self._src("services/workflow_orchestrator.py")
        self.assertIn("tightened_daily_pnl(", src)


if __name__ == "__main__":
    unittest.main()
