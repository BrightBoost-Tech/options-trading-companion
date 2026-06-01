"""Paper-shadow executor (Phase 1b core) — isolation + lifecycle + geometry.

Load-bearing: every executor order goes through ONE account-isolated
choke-point that can only reach the paper account; the own-fill lifecycle
reuses core functions; the geometry policy is correct. Flag OFF → the submit
path refuses. All unit-level, mocked broker.
"""

import os
import unittest
from pathlib import Path
from unittest import mock

from packages.quantum.services import paper_shadow_executor as ex
from packages.quantum.services import paper_shadow_isolation as iso

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, store=None, table=None):
        self._rows = list(rows)
        self._store = store
        self._table = table

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) == val], self._store, self._table)

    def limit(self, n):
        return _FakeQuery(self._rows[:n], self._store, self._table)

    def insert(self, payload):
        self._store[self._table] = self._store.get(self._table, []) + [payload]
        return _FakeQuery([payload], self._store, self._table)

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []), self._tables, name)


_PAPER_ENV = {"ALPACA_PAPER_API_KEY": "PK", "ALPACA_PAPER_SECRET_KEY": "SK"}


# ═════════════════════════════════════════════════════════════════════
# Account isolation — the choke-point can only reach the paper account
# ═════════════════════════════════════════════════════════════════════
class TestGuardedPaperSubmitIsolation(unittest.TestCase):
    def _fake_client(self, account):
        c = mock.MagicMock()
        c.get_account_number.return_value = account
        return c

    def test_refuses_when_flag_off(self):
        with mock.patch.dict(os.environ, {iso.FLAG_ENV: "0"}, clear=True):
            with self.assertRaises(ex.PaperShadowExecutorDisabled):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")

    def test_fails_closed_without_paper_creds(self):
        # Flag on, but no dedicated paper creds → build_paper_client fails closed.
        with mock.patch.dict(os.environ, {iso.FLAG_ENV: "1"}, clear=True):
            with self.assertRaises(iso.PaperShadowConfigError):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")

    def test_submits_via_dedicated_client_on_paper_account(self):
        fake_client = self._fake_client("PA3I8CYLXBOS")
        env = {iso.FLAG_ENV: "1", **_PAPER_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(ex, "build_paper_client", return_value=fake_client), \
             mock.patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track") as sat, \
             mock.patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                        side_effect=AssertionError("global live client must NOT be used")):
            sat.return_value = {"status": "submitted"}
            out = ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")
        sat.assert_called_once()
        # submit_and_track(client, supabase, order, user) — the dedicated client.
        self.assertIs(sat.call_args[0][0], fake_client)
        self.assertEqual(out["status"], "submitted")

    def test_aborts_on_live_account_no_order(self):
        fake_client = self._fake_client("211900084")  # LIVE
        env = {iso.FLAG_ENV: "1", **_PAPER_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(ex, "build_paper_client", return_value=fake_client), \
             mock.patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track") as sat:
            with self.assertRaises(iso.PaperShadowAccountMismatch):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")
        sat.assert_not_called()  # never submitted — no order to live


# ═════════════════════════════════════════════════════════════════════
# Own-fill lifecycle — reuse core (H13), never the live processor
# ═════════════════════════════════════════════════════════════════════
class TestOwnFillLifecycleReusesCore(unittest.TestCase):
    def test_commit_open_fill_reuses_repair_primitive(self):
        order = {"id": "o1", "user_id": "U"}
        portfolio = {"id": "port-shadow"}
        with mock.patch("packages.quantum.paper_endpoints._repair_filled_order_commit") as repair, \
             mock.patch("packages.quantum.services.analytics_service.AnalyticsService") as Analytics:
            repair.return_value = {"repaired": True, "position_id": "pos1"}
            out = ex.commit_open_fill(mock.MagicMock(), order, portfolio)
        repair.assert_called_once()
        args = repair.call_args[0]
        self.assertEqual(args[2], "U")        # user_id
        self.assertIs(args[3], order)         # the order
        self.assertIs(args[4], portfolio)     # the paper_shadow portfolio
        self.assertEqual(out["position_id"], "pos1")

    def test_reconcile_close_fill_reuses_core(self):
        with mock.patch("packages.quantum.brokers.alpaca_order_handler._close_position_on_fill") as close:
            ex.reconcile_close_fill(mock.MagicMock(), "pos1", {"id": "o2"}, {"filled_qty": 1})
        close.assert_called_once()
        self.assertEqual(close.call_args[0][1], "pos1")

    def test_live_processor_still_skips_paper_shadow(self):
        # The executor's own-fill design depends on the live processor skipping
        # paper_shadow (#1005). Regression guard that the filter is intact.
        s = (REPO_ROOT / "paper_endpoints.py").read_text(encoding="utf-8")
        self.assertIn('.neq("routing_mode", "paper_shadow")', s)


# ═════════════════════════════════════════════════════════════════════
# paper_shadow portfolio bootstrap
# ═════════════════════════════════════════════════════════════════════
class TestShadowPortfolioBootstrap(unittest.TestCase):
    def test_returns_existing_paper_shadow_portfolio(self):
        supa = _FakeSupabase({"paper_portfolios": [
            {"id": "p1", "user_id": "U", "routing_mode": "paper_shadow"},
            {"id": "p2", "user_id": "U", "routing_mode": "live_eligible"},
        ]})
        port = ex.get_or_create_shadow_portfolio(supa, "U")
        self.assertEqual(port["id"], "p1")

    def test_creates_paper_shadow_portfolio_when_absent(self):
        supa = _FakeSupabase({"paper_portfolios": [
            {"id": "p2", "user_id": "U", "routing_mode": "live_eligible"},
        ]})
        port = ex.get_or_create_shadow_portfolio(supa, "U")
        self.assertEqual(port["routing_mode"], "paper_shadow")
        self.assertEqual(port["cash_balance"], ex.SYNTHETIC_TIER_CAPITAL)


# ═════════════════════════════════════════════════════════════════════
# Canonical geometry exit policy (arm B) — pure
# ═════════════════════════════════════════════════════════════════════
class TestGeometryExitPolicy(unittest.TestCase):
    # debit CALL spread: buy 100C / sell 105C, net debit 2.0
    #   width=5, breakeven=102, R1_frac level = 100 + 0.8*5 = 104
    DEBIT_CALL = {"avg_entry_price": 2.0, "legs": [
        {"action": "buy", "type": "call", "strike": 100},
        {"action": "sell", "type": "call", "strike": 105},
    ]}

    def test_take_profit_when_spot_reaches_frac_level(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=104.5, dte=10)
        self.assertEqual(d, "take_profit")

    def test_hold_between_breakeven_and_profit_level(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=103.0, dte=10)
        self.assertEqual(d, "hold")

    def test_stop_on_breakeven_breach(self):
        d, reason = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=101.0, dte=10)
        self.assertEqual(d, "stop")
        self.assertIn("R2", reason)

    def test_na_for_non_debit_vertical(self):
        single_leg = {"avg_entry_price": 1.0, "legs": [{"action": "buy", "type": "call", "strike": 100}]}
        d, _ = ex.geometry_exit_decision(single_leg, underlying_spot=110.0, dte=10)
        self.assertEqual(d, "n/a")

    def test_na_when_spot_missing(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=None, dte=10)
        self.assertEqual(d, "n/a")


# ═════════════════════════════════════════════════════════════════════
# Flag default OFF
# ═════════════════════════════════════════════════════════════════════
class TestFlagDefaultOff(unittest.TestCase):
    def test_is_enabled_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ex.is_enabled())


if __name__ == "__main__":
    unittest.main()
