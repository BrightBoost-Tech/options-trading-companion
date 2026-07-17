"""Options-level entry preflight — ROUTE layer (2026-07-16).

Drives _stage_order_internal (the REAL production entrypoint the autopilot
calls) end-to-end with the failure injected at the DEEPEST callee (the
mocked alpaca client's account dict — the client/data boundary), asserting
the TOP-level outcome (typed rejection raised, NO paper_orders row, NO
broker submit, blocked_reason stamped) — the E8-3/E16-3/E19-2 lesson: a
green test on a helper is not a green closure on the route. The preflight
itself is NEVER mocked.

Route matrix:
- effective level 2 + OPEN 2-leg spread → typed rejection pre-insert,
  submit never called, blocked_reason stamped.
- effective level 3 (the healthy live shape) → proceeds past the preflight
  through insert to the broker-submit seam.
- missing effective level → typed unavailable rejection.
- CLOSE ticket (position_id set) → preflight skipped entirely (no account
  read), staging proceeds.
- LAZY scope: shadow_only routing and internal_paper execution mode never
  gain an account read.
"""

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.models import OptionLeg, TradeTicket  # noqa: E402
from packages.quantum.services.options_level_preflight import (  # noqa: E402
    EntryOptionsLevelInsufficient,
    EntryOptionsLevelUnavailable,
)

VALID_QUOTE = {"bid": 1.40, "ask": 1.60, "bid_price": 1.40,
               "ask_price": 1.60, "price": 1.50}


def _spread_ticket():
    """OPEN 2-leg vertical (selector-shaped, L3-requiring)."""
    return TradeTicket(
        symbol="QQQ",
        strategy_type="LONG_PUT_DEBIT_SPREAD",
        legs=[
            OptionLeg(symbol="O:QQQ260821P00640000", action="buy",
                      type="put", strike=640.0, expiry="2026-08-21"),
            OptionLeg(symbol="O:QQQ260821P00600000", action="sell",
                      type="put", strike=600.0, expiry="2026-08-21"),
        ],
        limit_price=1.50,
        quantity=1,
    )


def _portfolio(routing_mode="live_eligible"):
    return {
        "id": "port-1",
        "user_id": "user-1",
        "routing_mode": routing_mode,
        "cash_balance": 100000.0,
        "net_liq": 100000.0,
    }


def _account(effective, approved=3):
    acct = {
        "account_id": "acct-uuid",
        "status": "ACTIVE",
        "equity": 2093.74,
        "last_equity": 2093.74,
        "cash": 2093.74,
        "buying_power": 8374.96,
        "options_buying_power": 2093.74,
        "portfolio_value": 2093.74,
        "pattern_day_trader": False,
        "daytrade_count": 0,
        "daytrading_buying_power": 0.0,
        "paper": False,
        "options_approved_level": approved,
        "options_trading_level": effective,
    }
    return acct


class _FakeTable:
    def __init__(self, sb, name):
        self._sb = sb
        self._name = name
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._op == "insert":
            self._sb.inserts.append((self._name, self._payload))
            row = dict(self._payload)
            row.setdefault("id", f"{self._name}-row-1")
            return SimpleNamespace(data=[row])
        if self._op == "update":
            self._sb.updates.append((self._name, self._payload))
            return SimpleNamespace(data=[{"id": "updated"}])
        # selects
        if self._name == "paper_portfolios":
            data = (self._sb.portfolio if self._single
                    else [self._sb.portfolio])
        elif self._name == pe.TRADE_SUGGESTIONS_TABLE:
            data = (self._sb.suggestion if self._single
                    else [self._sb.suggestion])
        else:
            data = None if self._single else []
        return SimpleNamespace(data=data)


class FakeSupabase:
    """Recording fake at the DB boundary — inserts/updates observable."""

    def __init__(self, portfolio, suggestion=None):
        self.portfolio = portfolio
        self.suggestion = suggestion or {
            "id": "sugg-1", "strategy": "LONG_PUT_DEBIT_SPREAD",
        }
        self.inserts = []
        self.updates = []

    def table(self, name):
        return _FakeTable(self, name)

    # helpers -----------------------------------------------------------
    def inserted_tables(self):
        return [t for (t, _p) in self.inserts]

    def updates_for(self, table):
        return [p for (t, p) in self.updates if t == table]


class _RouteHarness(unittest.TestCase):
    """Shared patch scaffolding: everything stubbed at the client/data
    boundary; the preflight, gates, and _stage_order_internal itself run
    REAL."""

    def _stage(self, *, effective_level, approved_level=3,
               execution_mode="alpaca_paper", routing_mode="live_eligible",
               position_id=None, submit_to_broker=True, account_dict=None,
               suggestion_id="sugg-1"):
        sb = FakeSupabase(_portfolio(routing_mode))
        fake_client = MagicMock()
        fake_client.paper = True
        fake_client.get_account.return_value = (
            account_dict if account_dict is not None
            else _account(effective_level, approved_level)
        )
        submit_mock = MagicMock(return_value={"status": "submitted"})

        env = {
            "EXECUTION_MODE": execution_mode,
            "ALPACA_DRY_RUN": "0",
        }
        outcome = {"sb": sb, "client": fake_client, "submit": submit_mock,
                   "order_id": None, "raised": None}
        with patch.dict(os.environ, env), \
                patch.object(pe, "PolygonService", MagicMock()), \
                patch.object(pe, "_fetch_quote_with_retry",
                             lambda poly, sym, **k: dict(VALID_QUOTE)), \
                patch.object(pe, "_make_entry_quote_fetch_fn",
                             lambda poly: (lambda sym: dict(VALID_QUOTE))), \
                patch.object(pe, "_process_orders_for_user",
                             MagicMock(return_value={"processed": 0})), \
                patch("packages.quantum.brokers.alpaca_client."
                      "get_alpaca_client", return_value=fake_client), \
                patch("packages.quantum.brokers.alpaca_order_handler."
                      "submit_and_track", submit_mock), \
                patch("packages.quantum.execution.marketable_entry."
                      "maybe_apply_marketable_entry",
                      lambda supabase, row, user_id: row):
            try:
                outcome["order_id"] = pe._stage_order_internal(
                    sb, None, "user-1", _spread_ticket(),
                    portfolio_id_arg="port-1",
                    position_id=position_id,
                    suggestion_id_override=suggestion_id,
                    submit_to_broker=submit_to_broker,
                )
            except Exception as e:  # captured for assertions
                outcome["raised"] = e
        return outcome


class TestRouteLevelInsufficient(_RouteHarness):
    def test_level_2_open_spread_rejected_pre_insert_no_submit(self):
        out = self._stage(effective_level=2)
        self.assertIsInstance(out["raised"], EntryOptionsLevelInsufficient)
        # No order row was ever inserted (clean pre-insert reject).
        self.assertNotIn("paper_orders", out["sb"].inserted_tables())
        # No broker submit was attempted.
        out["submit"].assert_not_called()
        # The account read happened (the preflight actually ran).
        self.assertEqual(out["client"].get_account.call_count, 1)

    def test_level_2_reject_stamps_blocked_reason(self):
        out = self._stage(effective_level=2)
        stamps = out["sb"].updates_for(pe.TRADE_SUGGESTIONS_TABLE)
        self.assertTrue(stamps, "blocked_reason stamp missing")
        self.assertEqual(
            stamps[-1]["blocked_reason"], "entry_options_level_insufficient"
        )
        self.assertIn("required_level=3", stamps[-1]["blocked_detail"])

    def test_missing_effective_level_rejects_typed_unavailable(self):
        out = self._stage(effective_level=None)
        self.assertIsInstance(out["raised"], EntryOptionsLevelUnavailable)
        self.assertNotIn("paper_orders", out["sb"].inserted_tables())
        out["submit"].assert_not_called()
        stamps = out["sb"].updates_for(pe.TRADE_SUGGESTIONS_TABLE)
        self.assertTrue(stamps)
        self.assertEqual(
            stamps[-1]["blocked_reason"], "entry_options_level_unavailable"
        )


class TestRouteLevelHealthy(_RouteHarness):
    def test_level_3_proceeds_past_preflight_to_submit(self):
        """The healthy live shape (approved=3/effective=3): the preflight
        runs (one account read), allows, and staging continues all the way
        to the broker-submit seam."""
        out = self._stage(effective_level=3)
        self.assertIsNone(out["raised"], repr(out["raised"]))
        self.assertIn("paper_orders", out["sb"].inserted_tables())
        self.assertEqual(out["client"].get_account.call_count, 1)
        out["submit"].assert_called_once()
        # No blocked_reason was stamped.
        self.assertEqual(out["sb"].updates_for(pe.TRADE_SUGGESTIONS_TABLE),
                         [])
        self.assertIsNotNone(out["order_id"])

    def test_level_2_alpaca_live_mode_also_rejects(self):
        """The gate binds in alpaca_live exactly as in alpaca_paper."""
        out = self._stage(effective_level=2, execution_mode="alpaca_live")
        self.assertIsInstance(out["raised"], EntryOptionsLevelInsufficient)
        out["submit"].assert_not_called()


class TestRouteCloseExempt(_RouteHarness):
    def test_close_ticket_skips_preflight_entirely(self):
        """position_id set (a CLOSE) — the preflight must never run: no
        account read even on an account that would reject, and staging
        proceeds (mirrors the production close path, which stages with
        submit_to_broker=False — the single-submitter rule)."""
        out = self._stage(effective_level=2, position_id="pos-1",
                          submit_to_broker=False)
        self.assertIsNone(out["raised"], repr(out["raised"]))
        out["client"].get_account.assert_not_called()
        self.assertIn("paper_orders", out["sb"].inserted_tables())
        self.assertIsNotNone(out["order_id"])


class TestRouteLazyScope(_RouteHarness):
    """The account read exists ONLY where a broker submit would happen —
    internal_paper / shadow-routed staging gains no broker call."""

    def test_shadow_routing_never_reads_account(self):
        out = self._stage(effective_level=2, routing_mode="shadow_only")
        self.assertIsNone(out["raised"], repr(out["raised"]))
        out["client"].get_account.assert_not_called()
        # Staged (then shadow_blocked by the routing gate) — not rejected.
        self.assertIn("paper_orders", out["sb"].inserted_tables())
        out["submit"].assert_not_called()

    def test_internal_paper_never_reads_account(self):
        out = self._stage(effective_level=2,
                          execution_mode="internal_paper")
        self.assertIsNone(out["raised"], repr(out["raised"]))
        out["client"].get_account.assert_not_called()
        self.assertIn("paper_orders", out["sb"].inserted_tables())
        out["submit"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
