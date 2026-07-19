"""Route-level wiring proof for stage-time leg greeks population.

Doctrine (CLAUDE.md §9): a wiring test must EXECUTE the production route and
assert the OUTPUT — not reference a helper. Here we drive the real production
staging entrypoint ``paper_endpoints._stage_order_internal`` end-to-end, inject
the greek source at its DEEPEST callee (the truth-layer ``snapshot_many``), and
assert the greeks landed on the PERSISTED ``paper_orders.order_json.legs`` (the
same jsonb the fill copies verbatim into ``paper_positions.legs``).

Covers all three staging routes the task names — internal_paper, dry-run, and
shadow (shadow_blocked) — because population is placed BEFORE the exec-mode
branch, so every route persists identical legs. A live-routed order takes the
same pre-branch path; the shadow route additionally proves a shadow portfolio
never diverges. A per-leg MIX (valid quote + greeks vs valid quote + NO greeks)
proves a dark-greeks leg still STAGES (never rejected) with a typed marker.
"""

import contextlib
import sys
import types
import unittest
from unittest import mock

for _m in ("alpaca", "alpaca.trading", "alpaca.trading.requests"):
    sys.modules.setdefault(_m, types.ModuleType(_m))

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.models import TradeTicket, OptionLeg  # noqa: E402
from packages.quantum.brokers import execution_router as er  # noqa: E402

LONG_CALL = "O:SPY260116C00500000"
SHORT_CALL = "O:SPY260116C00510000"


# ── Fake Supabase: only the calls _stage_order_internal makes on the open path
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
    """snapshot_many keyed by requested symbol, returning per-symbol snaps."""

    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot_many(self, symbols):
        sym = symbols[0]
        snap = self._snaps.get(sym)
        return {sym: snap} if snap is not None else {}


def _snap(delta=None, source="alpaca"):
    snap = {
        "quote": {"bid": 1.0, "ask": 1.2, "mid": 1.1, "last": 1.1},
        "source": source,
        "retrieved_ts": "2026-07-18T00:00:00",
    }
    if delta is not None:
        snap["greeks"] = {"delta": delta, "gamma": 0.02, "theta": -0.03, "vega": 0.10}
    return snap


def _ticket():
    return TradeTicket(
        strategy_type=None,  # skip strict leg-count check
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


def _drive(route, snaps):
    """Run _stage_order_internal on the given route; return the captured
    persisted order_json (dict)."""
    fake = _FakeSupabase({"id": "port-1",
                          "routing_mode": "shadow_only" if route == "shadow"
                          else "live_eligible"})
    truth = _TruthStub(snaps)
    fake_truth_module = types.SimpleNamespace(
        MarketDataTruthLayer=lambda *a, **k: truth
    )

    env = {}
    exec_mode = er.ExecutionMode.INTERNAL_PAPER
    if route == "dry_run":
        exec_mode = er.ExecutionMode.ALPACA_PAPER
        env["ALPACA_DRY_RUN"] = "1"
    elif route == "shadow":
        exec_mode = er.ExecutionMode.ALPACA_PAPER

    with contextlib.ExitStack() as ctx:
        ctx.enter_context(mock.patch.dict(
            sys.modules,
            {"packages.quantum.services.market_data_truth_layer": fake_truth_module},
        ))
        ctx.enter_context(mock.patch.object(pe, "PolygonService", lambda *a, **k: object()))
        ctx.enter_context(mock.patch.object(pe, "_fetch_quote_with_retry", lambda poly, s: None))
        ctx.enter_context(mock.patch.object(pe, "emit_trade_event", lambda *a, **k: None))
        ctx.enter_context(mock.patch.object(er, "get_execution_mode", lambda: exec_mode))
        # Signature mirror: should_submit_to_broker(portfolio_id, supabase, order=None)
        # — the entry site threads order=order_row for the single-leg veto (PR #1292).
        ctx.enter_context(mock.patch.object(er, "should_submit_to_broker", lambda pid, sb, order=None: False))
        ctx.enter_context(mock.patch.object(pe, "_process_orders_for_user", lambda *a, **k: None))
        ctx.enter_context(mock.patch.dict("os.environ", env, clear=False))
        # keep the alpaca handler import in the dry-run branch cheap
        import packages.quantum.brokers.alpaca_order_handler as aoh
        ctx.enter_context(mock.patch.object(aoh, "build_alpaca_order_request", lambda row: {}))

        analytics = mock.MagicMock()
        order_id = pe._stage_order_internal(
            fake, analytics, "user-1", _ticket(), portfolio_id_arg="port-1",
        )
        assert order_id == "order-test-1"
        assert len(fake.order_inserts) == 1
        return fake.order_inserts[0]["order_json"], fake


class TestStageRoutesPopulateGreeks(unittest.TestCase):
    def _both_populated_snaps(self):
        return {LONG_CALL: _snap(0.60), SHORT_CALL: _snap(0.45)}

    def _assert_both_populated(self, order_json):
        legs = order_json["legs"]
        self.assertEqual(len(legs), 2)
        self.assertEqual(legs[0]["greeks_status"], "populated_at_stage")
        self.assertEqual(legs[0]["greeks"]["delta"], 0.60)
        self.assertEqual(legs[0]["greeks_source"], "alpaca")
        self.assertEqual(legs[0]["greeks_multiplier"], 100)
        # short leg stored UNSIGNED (raw +0.45); sign applied downstream
        self.assertEqual(legs[1]["greeks_status"], "populated_at_stage")
        self.assertEqual(legs[1]["greeks"]["delta"], 0.45)

    def test_internal_paper_route_persists_greeks(self):
        order_json, _ = _drive("internal", self._both_populated_snaps())
        self._assert_both_populated(order_json)

    def test_dry_run_route_persists_greeks(self):
        order_json, _ = _drive("dry_run", self._both_populated_snaps())
        self._assert_both_populated(order_json)

    def test_shadow_route_persists_greeks(self):
        order_json, fake = _drive("shadow", self._both_populated_snaps())
        self._assert_both_populated(order_json)
        # confirm we exercised the shadow_blocked branch, not a live submit
        self.assertTrue(
            any(u[1].get("execution_mode") == "shadow_blocked" for u in fake.updates)
        )

    def test_dark_greeks_leg_still_stages_with_typed_marker(self):
        # LONG_CALL: valid quote + greeks; SHORT_CALL: valid quote, NO greeks
        # (Polygon feed-fallback). Staging must SUCCEED (no rejection) and the
        # greek-light leg is typed unavailable — never a fabricated zero.
        snaps = {LONG_CALL: _snap(0.60), SHORT_CALL: _snap(delta=None, source="polygon")}
        order_json, _ = _drive("internal", snaps)
        legs = order_json["legs"]
        self.assertEqual(legs[0]["greeks_status"], "populated_at_stage")
        self.assertEqual(legs[1]["greeks_status"], "unavailable_at_stage")
        self.assertIsNone(legs[1]["greeks"])
        self.assertEqual(legs[1]["greeks_source"], "polygon")


if __name__ == "__main__":
    unittest.main()
