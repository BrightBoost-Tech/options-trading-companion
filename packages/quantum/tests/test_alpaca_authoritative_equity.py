"""
Regression tests for commit 83872db: Alpaca-authoritative equity + weekly P&L.

Locks in the contract that intraday_risk_monitor NEVER fabricates an
equity denominator. Before 83872db, the monitor read a nonexistent
`go_live_progression.deployable_capital` column, silently fell through
to `max(notional * 2, 500)`, and produced an equity two orders of
magnitude below the real Alpaca equity. Combined with per-position MTM
mark-sum as a weekly P&L proxy, this produced a `loss_weekly = -190%`
reading on what was actually a ~-1% real week — triggering a portfolio-
wide false force-close.

The post-fix contract enforced here:
    - With `RISK_EQUITY_SOURCE=alpaca` (default), equity and weekly
      P&L come from `get_alpaca_client().get_account()` and
      `get_portfolio_history(1W, 1D)` respectively.
    - When Alpaca is unavailable, helpers return `None` — callers MUST
      treat this as "skip the envelope" rather than substitute local
      data. Substituting local data is the specific failure mode the
      fix was written against.

These tests intentionally exercise the extracted module (PR #5) rather
than reach into the monitor class, since the module is now the single
source of truth for this arithmetic.
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# See test_equity_state_helpers.py for rationale — stub alpaca-py so the
# production module's lazy `from alpaca.trading.requests import ...`
# resolves without the real package installed.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")


class _StubPortfolioHistoryRequest:
    def __init__(self, period=None, timeframe=None, **_):
        self.period = period
        self.timeframe = timeframe


_alpaca_trading_requests.GetPortfolioHistoryRequest = _StubPortfolioHistoryRequest
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.services import equity_state  # noqa: E402

USER_ID = "test-user-83872db"


class TestAlpacaAuthoritativeEquity(unittest.TestCase):
    """
    Regression for 83872db. Before this commit, equity estimation summed
    local data; after it, equity comes from Alpaca's account endpoint
    with an explicit None on failure.
    """

    def setUp(self):
        os.environ.pop("RISK_EQUITY_SOURCE", None)
        importlib.reload(equity_state)
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    def test_default_is_alpaca_not_legacy(self):
        """The rip-cord is opt-in. Default MUST be Alpaca."""
        self.assertEqual(equity_state.EQUITY_SOURCE, "alpaca")

    def test_equity_denominator_comes_from_alpaca_get_account(self):
        """
        Before 83872db: equity was derived from position notionals.
        After: equity comes from the Alpaca account endpoint directly.
        """
        mock_client = MagicMock()
        # Real Alpaca equity ≫ the notional-derived fallback the legacy
        # path would have produced.
        mock_client.get_account.return_value = {"equity": "95000.00"}

        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            # `positions` supplied to prove we IGNORE it on the Alpaca
            # path — the legacy path used it to compute a fallback.
            bogus_positions = [
                {"avg_entry_price": 1.0, "quantity": 1},
            ]
            result = equity_state.get_alpaca_equity(
                USER_ID, supabase=MagicMock(), positions=bogus_positions,
            )

        self.assertEqual(result, 95000.0)
        mock_client.get_account.assert_called_once()

    def test_none_on_alpaca_failure_not_fabricated_value(self):
        """
        The specific bug: fabricating a local equity produced
        `loss_weekly = -190%`. Fix: return None on failure, forcing the
        caller to SKIP the envelope rather than guess.
        """
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            result = equity_state.get_alpaca_equity(
                USER_ID, supabase=MagicMock(), positions=[],
            )
        self.assertIsNone(result)

    def test_weekly_pnl_uses_portfolio_history_not_snapshot_sum(self):
        """
        Before 83872db: weekly P&L was sum(paper_eod_snapshots.unrealized_pl
        WHERE date >= Monday) — which re-counted every MTM mark of every
        still-open (and even closed) position for every day of the week,
        producing wildly compounding errors.

        After: weekly_pnl = equity_series[-1] - equity_series[0] across
        the 1W/1D portfolio-history series. Monday's open equity vs.
        current equity. One number, ground truth, from Alpaca.
        """
        mock_client = MagicMock()
        hist = MagicMock()
        # Monday open = 100k, current = 98.75k → -1250 week.
        hist.equity = [100000.0, 99500.0, 98750.0]
        mock_client._call_with_retry.return_value = hist

        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(
                USER_ID, supabase=MagicMock(),
            )

        self.assertAlmostEqual(result, -1250.0, places=2)

        # The request object passed to Alpaca specifies 1W / 1D — lock
        # that shape so the weekly envelope always operates on the same
        # denominator the equity endpoint returns.
        called_args, _ = mock_client._call_with_retry.call_args
        req = called_args[1]
        self.assertEqual(getattr(req, "period", None), "1W")
        self.assertEqual(getattr(req, "timeframe", None), "1D")

    def test_weekly_pnl_none_on_empty_series(self):
        """
        No data → None. Caller MUST skip the weekly envelope; substituting
        a local sum would reproduce the -190% false reading.
        """
        mock_client = MagicMock()
        hist = MagicMock()
        hist.equity = []
        mock_client._call_with_retry.return_value = hist

        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(
                USER_ID, supabase=MagicMock(),
            )
        self.assertIsNone(result)


class TestIntradayMonitorUsesModule(unittest.TestCase):
    """
    The intraday monitor must delegate to the extracted module, not
    carry its own copies of the fetch/cache logic. If someone re-inlines
    the arithmetic into the monitor, we lose the single source of truth.
    """

    def test_monitor_delegates_equity_to_module(self):
        from packages.quantum.jobs.handlers import intraday_risk_monitor

        called_with = {}

        def fake_get_equity(user_id, supabase=None, positions=None):
            called_with["user_id"] = user_id
            called_with["supabase"] = supabase
            called_with["positions"] = positions
            return 12345.67

        monitor = intraday_risk_monitor.IntradayRiskMonitor.__new__(
            intraday_risk_monitor.IntradayRiskMonitor,
        )
        monitor.supabase = MagicMock()

        with patch.object(
            intraday_risk_monitor.equity_state,
            "get_alpaca_equity",
            side_effect=fake_get_equity,
        ):
            result = monitor._estimate_equity(USER_ID, [])

        self.assertEqual(result, 12345.67)
        self.assertEqual(called_with["user_id"], USER_ID)

    def test_monitor_delegates_weekly_pnl_to_module(self):
        from packages.quantum.jobs.handlers import intraday_risk_monitor

        monitor = intraday_risk_monitor.IntradayRiskMonitor.__new__(
            intraday_risk_monitor.IntradayRiskMonitor,
        )
        monitor.supabase = MagicMock()

        with patch.object(
            intraday_risk_monitor.equity_state,
            "get_alpaca_weekly_pnl",
            return_value=-42.0,
        ) as mock_fn:
            result = monitor._compute_weekly_pnl(USER_ID, daily_pnl=-10.0)

        self.assertEqual(result, -42.0)
        mock_fn.assert_called_once_with(USER_ID, supabase=monitor.supabase)


if __name__ == "__main__":
    unittest.main()
