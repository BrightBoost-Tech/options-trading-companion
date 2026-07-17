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

import contextlib
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
from packages.quantum.services import options_level_preflight as olp  # noqa: E402
from packages.quantum.services.options_level_preflight import (  # noqa: E402
    ACCOUNT_LEVEL_TTL_SECONDS,
    EntryOptionsLevelInsufficient,
    EntryOptionsLevelUnavailable,
    reset_account_cache,
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


def _condor_ticket():
    """OPEN 4-leg iron condor — the max-leg-count structure the selector
    emits; pins that the account read is per-STAGE-CALL, never per-leg."""
    return TradeTicket(
        symbol="QQQ",
        strategy_type="IRON_CONDOR",
        legs=[
            OptionLeg(symbol="O:QQQ260821P00600000", action="buy",
                      type="put", strike=600.0, expiry="2026-08-21"),
            OptionLeg(symbol="O:QQQ260821P00620000", action="sell",
                      type="put", strike=620.0, expiry="2026-08-21"),
            OptionLeg(symbol="O:QQQ260821C00700000", action="sell",
                      type="call", strike=700.0, expiry="2026-08-21"),
            OptionLeg(symbol="O:QQQ260821C00720000", action="buy",
                      type="call", strike=720.0, expiry="2026-08-21"),
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

    def setUp(self):
        # The 60s account-read cache is process-global (keyed per client
        # identity) — start every test cold.
        reset_account_cache()

    def tearDown(self):
        reset_account_cache()

    def _stage(self, *, effective_level, approved_level=3,
               execution_mode="alpaca_paper", routing_mode="live_eligible",
               position_id=None, submit_to_broker=True, account_dict=None,
               suggestion_id="sugg-1", client=None, ticket=None,
               dry_run=False, real_submit=False):
        """Drive the REAL _stage_order_internal once.

        client: pass a previous outcome's client to REUSE it across stage
        calls (the TTL-cache tests) — its get_account is left untouched.
        real_submit: do NOT mock submit_and_track — run the real retry
        loop (sleep/alerts stubbed); the caller programs
        client.submit_option_order.
        """
        sb = FakeSupabase(_portfolio(routing_mode))
        if client is not None:
            fake_client = client
        else:
            fake_client = MagicMock()
            fake_client.paper = True
            fake_client.get_account.return_value = (
                account_dict if account_dict is not None
                else _account(effective_level, approved_level)
            )
        submit_mock = MagicMock(return_value={"status": "submitted"})

        env = {
            "EXECUTION_MODE": execution_mode,
            "ALPACA_DRY_RUN": "1" if dry_run else "0",
        }
        outcome = {"sb": sb, "client": fake_client, "submit": submit_mock,
                   "order_id": None, "raised": None}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env))
            stack.enter_context(
                patch.object(pe, "PolygonService", MagicMock()))
            stack.enter_context(
                patch.object(pe, "_fetch_quote_with_retry",
                             lambda poly, sym, **k: dict(VALID_QUOTE)))
            stack.enter_context(
                patch.object(pe, "_make_entry_quote_fetch_fn",
                             lambda poly: (lambda sym: dict(VALID_QUOTE))))
            stack.enter_context(
                patch.object(pe, "_process_orders_for_user",
                             MagicMock(return_value={"processed": 0})))
            stack.enter_context(
                patch("packages.quantum.brokers.alpaca_client."
                      "get_alpaca_client", return_value=fake_client))
            stack.enter_context(
                patch("packages.quantum.execution.marketable_entry."
                      "maybe_apply_marketable_entry",
                      lambda supabase, row, user_id: row))
            if real_submit:
                # Real submit_and_track retry loop; only its side effects
                # (backoff sleeps, alert egress) are stubbed.
                from packages.quantum.brokers import (
                    alpaca_order_handler as _handler,
                )
                stack.enter_context(patch.object(_handler.time, "sleep"))
                stack.enter_context(
                    patch("packages.quantum.observability.alerts.alert"))
                stack.enter_context(
                    patch("packages.quantum.observability.alerts."
                          "_get_admin_supabase",
                          return_value=MagicMock()))
            else:
                stack.enter_context(
                    patch("packages.quantum.brokers.alpaca_order_handler."
                          "submit_and_track", submit_mock))
            try:
                outcome["order_id"] = pe._stage_order_internal(
                    sb, None, "user-1",
                    ticket if ticket is not None else _spread_ticket(),
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

    def test_close_route_works_with_missing_level(self):
        """The close route must survive an account with NO readable level
        (effective=None) — a permission outage must never trap an existing
        position. Zero account reads, staging proceeds."""
        out = self._stage(effective_level=None, approved_level=None,
                          position_id="pos-1", submit_to_broker=False)
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

    def test_dry_run_never_reads_account(self):
        """ALPACA_DRY_RUN=1 never submits — the preflight adds no broker
        call there (even on an account that would reject)."""
        out = self._stage(effective_level=2, dry_run=True)
        self.assertIsNone(out["raised"], repr(out["raised"]))
        out["client"].get_account.assert_not_called()
        self.assertIn("paper_orders", out["sb"].inserted_tables())
        out["submit"].assert_not_called()


class TestRouteAccountReadScope(_RouteHarness):
    """Exactly ONE account read per submitting stage call — never per-leg,
    never per-retry — and the 60s TTL cache shares that read across
    candidates in one executor cycle."""

    def test_four_leg_condor_single_account_read_not_per_leg(self):
        """4 legs, each with its own entry-quote validation fetch — still
        exactly ONE get_account (the read is per stage call, not per
        leg)."""
        out = self._stage(effective_level=3, ticket=_condor_ticket())
        self.assertIsNone(out["raised"], repr(out["raised"]))
        self.assertEqual(out["client"].get_account.call_count, 1)
        out["submit"].assert_called_once()

    def test_second_stage_within_ttl_reuses_single_read(self):
        """Two live candidates in one executor cycle (same client, inside
        the 60s TTL): the second stage call performs ZERO additional
        get_account calls (the equity_state 60s pattern)."""
        first = self._stage(effective_level=3)
        self.assertIsNone(first["raised"], repr(first["raised"]))
        self.assertEqual(first["client"].get_account.call_count, 1)
        second = self._stage(effective_level=3, client=first["client"])
        self.assertIsNone(second["raised"], repr(second["raised"]))
        self.assertEqual(second["client"].get_account.call_count, 1)
        # Both calls really staged + submitted.
        self.assertIn("paper_orders", second["sb"].inserted_tables())
        second["submit"].assert_called_once()

    def test_ttl_expiry_rereads_account(self):
        """Past the 60s TTL the cache must NOT serve the stale read — the
        next stage call re-reads the broker (NOT a process-lifetime
        permission cache). Clock injected via monkeypatched
        time.monotonic."""
        class _Clock:
            t = 1000.0

            def __call__(self):
                return _Clock.t

        clock = _Clock()
        with patch.object(olp.time, "monotonic", clock):
            first = self._stage(effective_level=3)
            self.assertEqual(first["client"].get_account.call_count, 1)
            _Clock.t += ACCOUNT_LEVEL_TTL_SECONDS + 1.0
            second = self._stage(effective_level=3, client=first["client"])
            self.assertIsNone(second["raised"], repr(second["raised"]))
            self.assertEqual(second["client"].get_account.call_count, 2)

    def test_read_failure_fails_closed_and_is_never_cached(self):
        """A failed account read rejects the entry (fail CLOSED) and must
        not poison the cache: the next stage call re-reads and, once the
        broker recovers, proceeds."""
        broken = MagicMock()
        broken.paper = True
        broken.get_account.side_effect = RuntimeError("broker 500")
        out = self._stage(effective_level=3, client=broken)
        self.assertIsInstance(out["raised"], EntryOptionsLevelUnavailable)
        self.assertNotIn("paper_orders", out["sb"].inserted_tables())
        out["submit"].assert_not_called()
        self.assertEqual(broken.get_account.call_count, 1)
        # Broker recovers — same client, new stage call: RE-reads (the
        # failure was never cached) and stages clean.
        broken.get_account.side_effect = None
        broken.get_account.return_value = _account(3)
        again = self._stage(effective_level=3, client=broken)
        self.assertIsNone(again["raised"], repr(again["raised"]))
        self.assertEqual(broken.get_account.call_count, 2)
        again["submit"].assert_called_once()

    def test_submit_retries_never_reread_account(self):
        """Drive the REAL submit_and_track retry loop (transient error →
        MAX_SUBMIT_ATTEMPTS submits): the account read stays exactly ONE —
        never per-retry."""
        from packages.quantum.brokers.alpaca_order_handler import (
            MAX_SUBMIT_ATTEMPTS,
        )
        client = MagicMock()
        client.paper = True
        client.get_account.return_value = _account(3)
        client.submit_option_order.side_effect = Exception(
            "connection reset by peer"
        )
        out = self._stage(effective_level=3, client=client,
                          real_submit=True)
        # Submit failures are swallowed at the stage seam (order stays
        # staged for retry) — the stage call itself succeeds.
        self.assertIsNone(out["raised"], repr(out["raised"]))
        # The REAL retry loop actually ran all attempts...
        self.assertEqual(client.submit_option_order.call_count,
                         MAX_SUBMIT_ATTEMPTS)
        # ...and never triggered another account read.
        self.assertEqual(client.get_account.call_count, 1)


class TestRouteNoTradeVerdicts(_RouteHarness):
    """HOLD/CASH are no-trade verdicts, not option structures: the wiring
    resolves them via strategy_identity and returns BEFORE any account
    read — never treated as submitted structures. (They cannot legally
    reach _stage_order_internal as a full ticket — no legs to validate —
    so this pins the wrapper seam the route calls.)"""

    def test_hold_cash_no_account_read_no_reject(self):
        for verdict in ("HOLD", "CASH", "hold", "cash"):
            with self.subTest(strategy=verdict):
                client = MagicMock()
                client.get_account.return_value = _account(0)  # worst case
                sb = FakeSupabase(_portfolio("live_eligible"))
                ticket = SimpleNamespace(strategy_type=verdict)
                with patch.dict(os.environ, {
                        "EXECUTION_MODE": "alpaca_paper",
                        "ALPACA_DRY_RUN": "0"}), \
                        patch("packages.quantum.brokers.alpaca_client."
                              "get_alpaca_client", return_value=client):
                    # Must not raise — and must never read the account.
                    pe._apply_options_level_preflight(
                        sb, ticket, None, _portfolio("live_eligible"),
                        suggestion_id="sugg-1", submit_to_broker=True,
                    )
                client.get_account.assert_not_called()
                # No blocked_reason stamp — this is not a rejection.
                self.assertEqual(
                    sb.updates_for(pe.TRADE_SUGGESTIONS_TABLE), [])


if __name__ == "__main__":
    unittest.main()
