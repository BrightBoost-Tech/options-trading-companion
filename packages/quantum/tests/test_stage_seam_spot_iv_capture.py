"""⑤ Stage-seam entry-spot + per-leg IV capture — observe-only, typed.

Extends the #1259 greeks populate at the SAME seam: the option snapshot the
stage already fetched (cache-coherent, zero extra provider call) also carries
the leg's implied volatility (truth-layer ``iv`` key). We stamp it onto each
leg jsonb, decided INDEPENDENTLY of greeks completeness, and stamp a stage-level
``entry_underlying_spot`` marker onto the order_json — so the #1260 challenger
study (which abstained INSUFFICIENT_EVIDENCE for want of per-leg IV + entry
spot) can score a FUTURE outcome.

Doctrine (CLAUDE.md §9): the wiring proof drives the real production entrypoint
``paper_endpoints._stage_order_internal`` end-to-end, injects the snapshot at
its DEEPEST callee (the truth-layer ``snapshot_many``), and asserts the fields
landed on the PERSISTED ``paper_orders.order_json`` (legs + top-level key — the
same jsonb the fill copies verbatim into ``paper_positions.legs`` via the
key-preserving coercer). Four routes — internal_paper, dry-run, shadow_blocked,
broker-live — because population sits BEFORE the exec-mode branch, so every
route persists identical inputs.

H9: a dark / non-positive / feed-fallback-without-IV leg types the IV
unavailable (never a fabricated default), and entry spot — which has NO honest
same-fetch source at this seam — is typed unavailable WITH a reason, never
fabricated. Staging NEVER rejects on either.
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
# Pre-import the real broker/exec modules ONCE so the live submit branch's
# lazy `from … import …` resolves against them; we patch ATTRIBUTES (never
# replace the modules in sys.modules — that would break alpaca_order_handler's
# own top-level imports).
import packages.quantum.brokers.alpaca_order_handler as aoh  # noqa: E402
import packages.quantum.brokers.alpaca_client as alpaca_client_mod  # noqa: E402
import packages.quantum.execution.marketable_entry as marketable_mod  # noqa: E402

LONG_CALL = "O:SPY260116C00500000"
SHORT_CALL = "O:SPY260116C00510000"


# ── unit: per-leg IV application semantics ──────────────────────────────────
def _snap(iv=0.2045, delta=0.60, source="alpaca", with_greeks=True):
    snap = {
        "quote": {"bid": 1.0, "ask": 1.2, "mid": 1.1, "last": 1.1},
        "source": source,
        "retrieved_ts": "2026-07-18T00:00:00",
        "iv": iv,
    }
    if with_greeks and delta is not None:
        snap["greeks"] = {"delta": delta, "gamma": 0.02, "theta": -0.03, "vega": 0.10}
    return snap


class TestApplyLegIv(unittest.TestCase):
    def test_populated_iv_block(self):
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, _snap(iv=0.2045))
        self.assertEqual(leg["iv"], 0.2045)
        self.assertEqual(leg["iv_status"], "populated_at_stage")
        self.assertEqual(leg["iv_source"], "alpaca")
        self.assertEqual(leg["iv_as_of"], "2026-07-18T00:00:00")

    def test_iv_independent_of_greeks_completeness(self):
        # greeks missing theta → greeks unavailable, but IV still populates.
        snap = _snap(iv=0.31)
        del snap["greeks"]["theta"]
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, snap)
        self.assertIsNone(leg["greeks"])
        self.assertEqual(leg["greeks_status"], "unavailable_at_stage")
        self.assertEqual(leg["iv"], 0.31)              # IV survives
        self.assertEqual(leg["iv_status"], "populated_at_stage")

    def test_greeks_populate_without_iv(self):
        # Valid greeks but no IV in the snapshot → greeks populate, IV unavailable.
        snap = _snap(iv=None)
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, snap)
        self.assertEqual(leg["greeks_status"], "populated_at_stage")
        self.assertIsNone(leg["iv"])
        self.assertEqual(leg["iv_status"], "unavailable_at_stage")
        self.assertEqual(leg["iv_source"], "alpaca")   # source still recorded

    def test_nonpositive_iv_typed_unavailable_never_stored(self):
        for bad in (0.0, -0.10):
            leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
            pe._apply_leg_greeks(leg, _snap(iv=bad))
            self.assertIsNone(leg["iv"])
            self.assertEqual(leg["iv_status"], "unavailable_at_stage")

    def test_nonfinite_iv_typed_unavailable(self):
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, _snap(iv=float("nan")))
        self.assertIsNone(leg["iv"])
        self.assertEqual(leg["iv_status"], "unavailable_at_stage")

    def test_dark_snapshot_types_iv_unavailable(self):
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, None)
        self.assertIsNone(leg["iv"])
        self.assertEqual(leg["iv_status"], "unavailable_at_stage")

    def test_high_iv_stored_raw_not_reinterpreted(self):
        # An implausibly-high (percent-not-decimal) IV is stored RAW; the >3.0
        # percent-guard abstention is the DOWNSTREAM challenger's call, not the
        # capture's — capture stays honest, never rescales/reinterprets.
        leg = {"symbol": LONG_CALL, "action": "buy", "quantity": 1}
        pe._apply_leg_greeks(leg, _snap(iv=45.0))
        self.assertEqual(leg["iv"], 45.0)
        self.assertEqual(leg["iv_status"], "populated_at_stage")


class TestPopulateEntrySpot(unittest.TestCase):
    def test_open_stamps_typed_unavailable_marker(self):
        oj = {"legs": []}
        pe._populate_stage_entry_spot(oj, position_id=None)
        spot = oj["entry_underlying_spot"]
        self.assertIsNone(spot["value"])
        self.assertIsNone(spot["source"])
        self.assertIsNone(spot["as_of"])
        self.assertEqual(spot["status"], "unavailable_at_stage")
        self.assertEqual(spot["reason"], "no_same_fetch_spot_source")

    def test_close_is_exempt_no_key(self):
        oj = {"legs": []}
        pe._populate_stage_entry_spot(oj, position_id="pos-1")
        self.assertNotIn("entry_underlying_spot", oj)


# ── route wiring: fake supabase + truth stub ────────────────────────────────
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


def _drive(route, snaps):
    """Run _stage_order_internal on the given route; return (order_json, fake)."""
    live_routed = route != "shadow"
    fake = _FakeSupabase({"id": "port-1",
                          "routing_mode": "live_eligible" if live_routed
                          else "shadow_only"})
    truth = _TruthStub(snaps)
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
        ctx.enter_context(mock.patch.object(pe, "_fetch_quote_with_retry", lambda poly, s: None))
        ctx.enter_context(mock.patch.object(pe, "emit_trade_event", lambda *a, **k: None))
        # Preflight is an unrelated gate; no-op so the live route reaches the
        # populate + insert (internal/dry/shadow skip it internally anyway).
        ctx.enter_context(mock.patch.object(pe, "_apply_options_level_preflight", lambda *a, **k: None))
        ctx.enter_context(mock.patch.object(er, "get_execution_mode", lambda: exec_mode))
        ctx.enter_context(mock.patch.object(er, "should_submit_to_broker", lambda pid, sb: should_submit))
        ctx.enter_context(mock.patch.object(pe, "_process_orders_for_user", lambda *a, **k: None))
        ctx.enter_context(mock.patch.dict("os.environ", env, clear=False))
        # Patch ATTRIBUTES on the real (pre-imported) modules so the live submit
        # branch never touches a network / broker.
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
        return fake.order_inserts[0]["order_json"], fake


class TestStageRoutesPersistIvAndSpot(unittest.TestCase):
    def _snaps(self):
        return {LONG_CALL: _snap(iv=0.2045, delta=0.60),
                SHORT_CALL: _snap(iv=0.1830, delta=0.45)}

    def _assert_iv_and_spot(self, order_json):
        legs = order_json["legs"]
        self.assertEqual(len(legs), 2)
        # per-leg IV populated on both legs (raw decimals, per-leg distinct)
        self.assertEqual(legs[0]["iv_status"], "populated_at_stage")
        self.assertEqual(legs[0]["iv"], 0.2045)
        self.assertEqual(legs[0]["iv_source"], "alpaca")
        self.assertEqual(legs[1]["iv_status"], "populated_at_stage")
        self.assertEqual(legs[1]["iv"], 0.1830)
        # greeks still populated too (co-captured, #1259 unbroken)
        self.assertEqual(legs[0]["greeks"]["delta"], 0.60)
        # stage-level entry spot marker: typed unavailable with reason
        spot = order_json["entry_underlying_spot"]
        self.assertIsNone(spot["value"])
        self.assertEqual(spot["status"], "unavailable_at_stage")
        self.assertEqual(spot["reason"], "no_same_fetch_spot_source")

    def test_internal_paper_route(self):
        oj, _ = _drive("internal", self._snaps())
        self._assert_iv_and_spot(oj)

    def test_dry_run_route(self):
        oj, _ = _drive("dry_run", self._snaps())
        self._assert_iv_and_spot(oj)

    def test_shadow_route(self):
        oj, fake = _drive("shadow", self._snaps())
        self._assert_iv_and_spot(oj)
        # confirm we exercised the shadow_blocked branch (not a live submit)
        self.assertTrue(
            any(u[1].get("execution_mode") == "shadow_blocked" for u in fake.updates)
        )

    def test_broker_live_route(self):
        oj, _ = _drive("live", self._snaps())
        self._assert_iv_and_spot(oj)

    def test_dark_iv_leg_still_stages_with_typed_marker(self):
        # LONG_CALL: valid IV; SHORT_CALL: snapshot without IV (feed fallback).
        # Staging must SUCCEED and the IV-less leg is typed unavailable.
        snaps = {LONG_CALL: _snap(iv=0.2045, delta=0.60),
                 SHORT_CALL: _snap(iv=None, delta=None, source="polygon")}
        oj, _ = _drive("internal", snaps)
        legs = oj["legs"]
        self.assertEqual(legs[0]["iv_status"], "populated_at_stage")
        self.assertEqual(legs[1]["iv_status"], "unavailable_at_stage")
        self.assertIsNone(legs[1]["iv"])
        self.assertEqual(legs[1]["iv_source"], "polygon")
        # spot still captured (unavailable) — staging never blocked
        self.assertEqual(oj["entry_underlying_spot"]["status"], "unavailable_at_stage")


if __name__ == "__main__":
    unittest.main()
