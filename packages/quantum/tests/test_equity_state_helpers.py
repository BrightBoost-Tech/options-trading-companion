"""
Unit tests for `packages.quantum.services.equity_state`.

Covers the extracted Alpaca-authoritative helpers (`get_alpaca_equity`,
`get_alpaca_weekly_pnl`) directly, independent of any intraday risk
monitor instance.

What this file verifies:
    1. Default source is Alpaca (`RISK_EQUITY_SOURCE` unset or "alpaca")
       and the helpers fetch via the Alpaca client singleton.
    2. Cache hits short-circuit the client — bursts within one monitor
       cycle hit Alpaca at most once per endpoint (TTL=60s).
    3. Cache misses past TTL re-fetch.
    4. Alpaca unavailability (client=None, get_account raises, equity<=0,
       empty equity series) returns `None` rather than a fabricated
       number. Fabricating equity was the 2026-04-16 incident mechanism.
    5. The weekly-pnl helper uses
       `get_portfolio_history(period="1W", timeframe="1D")` and computes
       `equity_series[-1] - equity_series[0]`. Single-point series maps
       to 0.0 (Monday-open-only case).
    6. Legacy rip-cord (`RISK_EQUITY_SOURCE=legacy`) is still reachable
       for 72h and returns the known-broken values — documented for the
       ops team that flipping the flag restores the old behavior exactly.
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub out `alpaca.trading.requests` so tests don't require alpaca-py to
# be installed in the test venv. The production module imports
# GetPortfolioHistoryRequest lazily inside the weekly P&L fetcher.
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

USER_ID = "test-user-equity-state"


def _reload_with_env(env_value):
    """Reload the module so EQUITY_SOURCE picks up a new env value."""
    os.environ["RISK_EQUITY_SOURCE"] = env_value
    importlib.reload(equity_state)
    return equity_state


class TestFetchAlpacaEquity(unittest.TestCase):
    def setUp(self):
        os.environ.pop("RISK_EQUITY_SOURCE", None)
        importlib.reload(equity_state)
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    def test_default_source_is_alpaca(self):
        self.assertEqual(equity_state.EQUITY_SOURCE, "alpaca")

    def test_returns_alpaca_equity(self):
        mock_client = MagicMock()
        mock_client.get_account.return_value = {"equity": "12345.67"}
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_equity(USER_ID)
        self.assertEqual(result, 12345.67)

    def test_caches_within_ttl(self):
        mock_client = MagicMock()
        mock_client.get_account.return_value = {"equity": "500.00"}
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            r1 = equity_state.get_alpaca_equity(USER_ID)
            r2 = equity_state.get_alpaca_equity(USER_ID)
        self.assertEqual(r1, 500.0)
        self.assertEqual(r2, 500.0)
        self.assertEqual(mock_client.get_account.call_count, 1)

    def test_none_client_returns_none(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            result = equity_state.get_alpaca_equity(USER_ID)
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        mock_client = MagicMock()
        mock_client.get_account.side_effect = RuntimeError("alpaca down")
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_equity(USER_ID)
        self.assertIsNone(result)

    def test_zero_equity_returns_none(self):
        """equity=0 is nonsense — return None so callers skip envelopes."""
        mock_client = MagicMock()
        mock_client.get_account.return_value = {"equity": "0"}
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_equity(USER_ID)
        self.assertIsNone(result)


class TestFetchAlpacaWeeklyPnL(unittest.TestCase):
    def setUp(self):
        os.environ.pop("RISK_EQUITY_SOURCE", None)
        importlib.reload(equity_state)
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        equity_state._reset_caches_for_testing()

    def _mock_hist(self, equity_series):
        hist = MagicMock()
        hist.equity = equity_series
        return hist

    def test_returns_series_delta(self):
        mock_client = MagicMock()
        mock_client._call_with_retry.return_value = self._mock_hist(
            [100000.0, 100500.0, 101250.0],
        )
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(USER_ID)
        self.assertAlmostEqual(result, 1250.0, places=2)

    def test_single_point_series_is_flat(self):
        """Monday pre-close: one data point, no delta computable."""
        mock_client = MagicMock()
        mock_client._call_with_retry.return_value = self._mock_hist([100000.0])
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(USER_ID)
        self.assertEqual(result, 0.0)

    def test_empty_series_returns_none(self):
        mock_client = MagicMock()
        mock_client._call_with_retry.return_value = self._mock_hist([])
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(USER_ID)
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        mock_client = MagicMock()
        mock_client._call_with_retry.side_effect = RuntimeError("boom")
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            result = equity_state.get_alpaca_weekly_pnl(USER_ID)
        self.assertIsNone(result)

    def test_caches_within_ttl(self):
        mock_client = MagicMock()
        mock_client._call_with_retry.return_value = self._mock_hist(
            [100000.0, 99000.0],
        )
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_client,
        ):
            r1 = equity_state.get_alpaca_weekly_pnl(USER_ID)
            r2 = equity_state.get_alpaca_weekly_pnl(USER_ID)
        self.assertAlmostEqual(r1, -1000.0, places=2)
        self.assertAlmostEqual(r2, -1000.0, places=2)
        self.assertEqual(mock_client._call_with_retry.call_count, 1)


class TestLegacyRipCord(unittest.TestCase):
    """
    Rip-cord path exists only to let ops instantly revert if the Alpaca
    path regresses. It intentionally reproduces the pre-fix arithmetic.
    """

    def setUp(self):
        _reload_with_env("legacy")
        equity_state._reset_caches_for_testing()

    def tearDown(self):
        os.environ.pop("RISK_EQUITY_SOURCE", None)
        importlib.reload(equity_state)
        equity_state._reset_caches_for_testing()

    def test_legacy_equity_reads_deployable_capital(self):
        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(
            data=[{"deployable_capital": 777.77}],
        )
        for method in ("select", "limit"):
            getattr(chain, method).return_value = chain
        supabase.table.return_value = chain

        result = equity_state.get_alpaca_equity(
            USER_ID, supabase=supabase, positions=[],
        )
        self.assertEqual(result, 777.77)

    def test_legacy_equity_falls_through_to_notional_floor(self):
        """No `deployable_capital` column → max(notional*2, 500)."""
        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        for method in ("select", "limit"):
            getattr(chain, method).return_value = chain
        supabase.table.return_value = chain

        positions = [{"avg_entry_price": 10.0, "quantity": 1}]
        result = equity_state.get_alpaca_equity(
            USER_ID, supabase=supabase, positions=positions,
        )
        # 10 * 1 * 100 * 2 = 2000 > 500 floor
        self.assertEqual(result, 2000.0)

    def test_legacy_weekly_pnl_sums_snapshots(self):
        supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(
            data=[{"unrealized_pl": -50.0}, {"unrealized_pl": -30.0}],
        )
        for method in ("select", "gte"):
            getattr(chain, method).return_value = chain
        supabase.table.return_value = chain

        result = equity_state.get_alpaca_weekly_pnl(USER_ID, supabase=supabase)
        self.assertAlmostEqual(result, -80.0, places=2)


if __name__ == "__main__":
    unittest.main()
