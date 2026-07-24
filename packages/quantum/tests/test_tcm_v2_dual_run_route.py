"""TCM v2 dual-run — ROUTE-DRIVEN wiring proof + byte-identity pin.

Doctrine (CLAUDE.md §9): the wiring proof drives the REAL production entrypoint
``paper_endpoints._stage_order_internal`` end-to-end across all four routes
(internal_paper, dry-run, shadow_blocked, broker-live) and asserts on the
PERSISTED ``paper_orders.tcm`` — never a reimplementation or a source-string
assertion.

Two things are pinned:
  1. BYTE-IDENTITY (route-level): the persisted ``tcm`` dict MINUS the new
     ``tcm_v2_proposal`` sibling equals ``TransactionCostModel.estimate(ticket,
     quote)`` computed independently — i.e. the dual-run adds ONE key and leaves
     every frozen-model key untouched. The frozen model output is unchanged.
  2. ROUTING-AWARE COMMISSION: broker routes (dry-run, live) propose $0
     commission; internal/shadow routes propose the synthetic estimate. The
     stamp lands BEFORE the exec-mode branch so every route persists it.

The harness mirrors ``test_stage_seam_spot_iv_capture`` (a fake supabase that
captures the inserted row + a truth-layer stub) so we exercise the same route
the live executor calls.
"""

import contextlib
import sys
import types
import unittest
from unittest import mock

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.models import TradeTicket, OptionLeg  # noqa: E402
from packages.quantum.brokers import execution_router as er  # noqa: E402
from packages.quantum.execution.transaction_cost_model import (  # noqa: E402
    TransactionCostModel,
)
from packages.quantum.services import tcm_v2_proposal as v2  # noqa: E402
import packages.quantum.brokers.alpaca_order_handler as aoh  # noqa: E402
import packages.quantum.brokers.alpaca_client as alpaca_client_mod  # noqa: E402
import packages.quantum.execution.marketable_entry as marketable_mod  # noqa: E402

LONG_CALL = "O:SPY260116C00500000"
SHORT_CALL = "O:SPY260116C00510000"


# ── fake supabase + truth stub (captures the inserted paper_orders row) ──────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, db):
        self.table = table
        self.db = db
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def execute(self):
        if self._op == "insert" and self.table == "paper_orders":
            row = dict(self._payload)
            row["id"] = "order-test-1"
            self.db.order_inserts.append(row)
            return _Resp([row])
        if self._op == "update":
            self.db.updates.append((self.table, self._payload))
            return _Resp([{}])
        if self.table == "paper_portfolios":
            return _Resp(self.db.portfolio)
        return _Resp(None)


class _FakeSupabase:
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.order_inserts = []
        self.updates = []

    def table(self, name):
        return _Query(name, self)


class _TruthStub:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot_many(self, symbols):
        sym = symbols[0]
        snap = self._snaps.get(sym)
        return {sym: snap} if snap is not None else {}


def _snap(bid=1.0, ask=1.2):
    return {"quote": {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "last": (bid + ask) / 2},
            "source": "alpaca", "retrieved_ts": "2026-07-18T00:00:00"}


def _ticket():
    return TradeTicket(
        strategy_type=None,
        symbol="SPY",
        legs=[
            OptionLeg(symbol=LONG_CALL, action="buy", type="call",
                      strike=500.0, expiry="2026-01-16", quantity=1),
            OptionLeg(symbol=SHORT_CALL, action="sell", type="call",
                      strike=510.0, expiry="2026-01-16", quantity=1),
        ],
        order_type="limit",
        limit_price=1.50,
        quantity=1,
    )


def _drive(route, combo_quote=None):
    """Run _stage_order_internal on the given route; return the inserted row.
    ``combo_quote`` is what _fetch_quote_with_retry returns (None → the frozen
    TCM missing-quote fallback path)."""
    live_routed = route != "shadow"
    fake = _FakeSupabase({"id": "port-1",
                          "routing_mode": "live_eligible" if live_routed
                          else "shadow_only"})
    truth = _TruthStub({LONG_CALL: _snap(), SHORT_CALL: _snap()})
    fake_truth_module = types.SimpleNamespace(
        MarketDataTruthLayer=lambda *a, **k: truth
    )

    env = {}
    exec_mode = er.ExecutionMode.INTERNAL_PAPER
    should_submit = False
    if route == "dry_run":
        exec_mode = er.ExecutionMode.ALPACA_PAPER
        env["ALPACA_DRY_RUN"] = "1"
    elif route == "shadow":
        exec_mode = er.ExecutionMode.ALPACA_PAPER
    elif route == "live":
        exec_mode = er.ExecutionMode.ALPACA_LIVE
        should_submit = True

    with contextlib.ExitStack() as ctx:
        ctx.enter_context(mock.patch.dict(
            sys.modules,
            {"packages.quantum.services.market_data_truth_layer": fake_truth_module},
        ))
        ctx.enter_context(mock.patch.object(pe, "PolygonService", lambda *a, **k: object()))
        ctx.enter_context(mock.patch.object(pe, "_fetch_quote_with_retry", lambda poly, s: combo_quote))
        ctx.enter_context(mock.patch.object(pe, "emit_trade_event", lambda *a, **k: None))
        ctx.enter_context(mock.patch.object(pe, "_apply_options_level_preflight", lambda *a, **k: None))
        ctx.enter_context(mock.patch.object(er, "get_execution_mode", lambda: exec_mode))
        # Signature mirror: should_submit_to_broker(portfolio_id, supabase, order=None)
        # — the entry site threads order=order_row for the single-leg veto (PR #1292).
        ctx.enter_context(mock.patch.object(er, "should_submit_to_broker", lambda pid, sb, order=None: should_submit))
        ctx.enter_context(mock.patch.object(pe, "_process_orders_for_user", lambda *a, **k: None))
        ctx.enter_context(mock.patch.dict("os.environ", env, clear=False))
        ctx.enter_context(mock.patch.object(aoh, "build_alpaca_order_request", lambda row: {}))
        ctx.enter_context(mock.patch.object(aoh, "submit_and_track", lambda *a, **k: None, create=True))
        ctx.enter_context(mock.patch.object(alpaca_client_mod, "get_alpaca_client", lambda: object(), create=True))
        ctx.enter_context(mock.patch.object(marketable_mod, "maybe_apply_marketable_entry",
                                            lambda supabase, order_row, user_id: order_row, create=True))

        analytics = mock.MagicMock()
        order_id = pe._stage_order_internal(
            fake, analytics, "user-1", _ticket(), portfolio_id_arg="port-1",
        )
        assert order_id == "order-test-1"
        assert len(fake.order_inserts) == 1
        return fake.order_inserts[0], fake


class TestByteIdentity(unittest.TestCase):
    """The frozen model's outputs are byte-identical: the persisted tcm minus
    the new sibling equals a fresh TransactionCostModel.estimate()."""

    def _assert_byte_identical(self, route, combo_quote):
        row, _ = _drive(route, combo_quote=combo_quote)
        persisted = row["tcm"]
        self.assertIn("tcm_v2_proposal", persisted)
        frozen_keys = {k: v for k, v in persisted.items() if k != "tcm_v2_proposal"}
        expected = TransactionCostModel.estimate(_ticket(), combo_quote)
        self.assertEqual(frozen_keys, expected)

    def test_byte_identical_missing_quote_all_routes(self):
        for route in ("internal", "dry_run", "shadow", "live"):
            with self.subTest(route=route):
                self._assert_byte_identical(route, combo_quote=None)

    def test_byte_identical_present_quote_all_routes(self):
        q = {"bid": 1.40, "ask": 1.60, "bid_price": 1.40, "ask_price": 1.60}
        for route in ("internal", "dry_run", "shadow", "live"):
            with self.subTest(route=route):
                self._assert_byte_identical(route, combo_quote=q)


class TestRoutingAwareStamp(unittest.TestCase):
    """The dual-run sibling lands on every route with routing-aware commission."""

    def test_internal_route_synthetic_commission(self):
        row, _ = _drive("internal", combo_quote=None)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertEqual(prop["routing"], v2.ROUTING_INTERNAL)
        self.assertEqual(prop["source"], v2.COMMISSION_SOURCE_SYNTHETIC)
        # internal proposed == current synthetic fee → no over-charge
        self.assertEqual(prop["proposed_model"]["commission_usd"]["usd"],
                         row["tcm"]["fees_usd"])
        self.assertEqual(prop["delta"]["commission_usd"], 0.0)
        self.assertEqual(prop["entry_or_close"], "entry")
        self.assertEqual(prop["leg_count"], 2)

    def test_dry_run_route_broker_zero_commission(self):
        row, _ = _drive("dry_run", combo_quote=None)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertEqual(prop["routing"], v2.ROUTING_BROKER)
        self.assertEqual(prop["proposed_model"]["commission_usd"]["usd"], 0.0)
        self.assertEqual(prop["source"], v2.COMMISSION_SOURCE_BROKER)
        # frozen fee 0.65 over-charged → delta −0.65
        self.assertAlmostEqual(prop["delta"]["commission_usd"], -0.65, places=6)
        self.assertTrue(prop["context"]["dry_run"])

    def test_shadow_route_synthetic_commission(self):
        row, fake = _drive("shadow", combo_quote=None)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertEqual(prop["routing"], v2.ROUTING_SHADOW)
        self.assertEqual(prop["source"], v2.COMMISSION_SOURCE_SYNTHETIC)
        # confirm we really took the shadow_blocked branch
        self.assertTrue(
            any(u[1].get("execution_mode") == "shadow_blocked" for u in fake.updates)
        )

    def test_live_route_broker_zero_commission(self):
        row, _ = _drive("live", combo_quote=None)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertEqual(prop["routing"], v2.ROUTING_BROKER)
        self.assertEqual(prop["proposed_model"]["commission_usd"]["usd"], 0.0)
        self.assertAlmostEqual(prop["delta"]["commission_usd"], -0.65, places=6)

    def test_missing_quote_spread_slippage_typed_unavailable(self):
        # combo quote None → frozen model used_fallback → proposed spread/slippage
        # typed unavailable (H9), commission still evidenced.
        row, _ = _drive("live", combo_quote=None)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertTrue(prop["context"]["missing_quote"])
        pm = prop["proposed_model"]
        self.assertFalse(pm["spread_cost_usd"]["available"])
        self.assertFalse(pm["slippage_usd"]["available"])
        self.assertTrue(pm["commission_usd"]["available"])

    def test_present_quote_carries_spread_slippage(self):
        q = {"bid": 1.40, "ask": 1.60, "bid_price": 1.40, "ask_price": 1.60}
        row, _ = _drive("live", combo_quote=q)
        prop = row["tcm"]["tcm_v2_proposal"]
        self.assertFalse(prop["context"]["missing_quote"])
        pm = prop["proposed_model"]
        self.assertTrue(pm["spread_cost_usd"]["available"])
        # carried verbatim from the frozen model
        self.assertEqual(pm["spread_cost_usd"]["usd"],
                         row["tcm"]["expected_spread_cost_usd"])


if __name__ == "__main__":
    unittest.main()
