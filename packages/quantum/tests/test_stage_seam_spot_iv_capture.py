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
        # No scan carrier at all → unchanged legacy behavior.
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

    def test_close_is_exempt_even_with_scan_spot(self):
        oj = {"legs": []}
        pe._populate_stage_entry_spot(
            oj, position_id="pos-1", scan_spot=_scan_spot_marker())
        self.assertNotIn("entry_underlying_spot", oj)

    # ── ⑤ scan-time POPULATE upgrade ────────────────────────────────────────
    def test_finite_positive_scan_spot_populates_marker(self):
        oj = {"legs": []}
        pe._populate_stage_entry_spot(
            oj, position_id=None,
            scan_spot=_scan_spot_marker(value=512.34,
                                        as_of="2026-07-18T12:00:00+00:00"))
        spot = oj["entry_underlying_spot"]
        self.assertEqual(spot["value"], 512.34)
        self.assertEqual(spot["source"], "scan_time")
        self.assertEqual(spot["as_of"], "2026-07-18T12:00:00+00:00")
        self.assertEqual(spot["as_of_source"], "provider_quote_ts")
        self.assertEqual(spot["status"], "populated_at_stage")
        # a populated marker never carries an unavailability reason.
        self.assertNotIn("reason", spot)

    def test_nonpositive_or_nonfinite_scan_value_types_unavailable(self):
        for bad in (0.0, -1.0, float("nan"), float("inf"), None):
            with self.subTest(bad=bad):
                oj = {"legs": []}
                pe._populate_stage_entry_spot(
                    oj, position_id=None, scan_spot=_scan_spot_marker(value=bad))
                spot = oj["entry_underlying_spot"]
                self.assertIsNone(spot["value"])              # never fabricated
                self.assertEqual(spot["status"], "unavailable_at_stage")
                # a carrier arrived but its value was unusable → precise reason.
                self.assertEqual(spot["reason"], "scan_spot_nonpositive")

    def test_never_downgrades_a_higher_authority_populated_marker(self):
        # A FUTURE same-fetch source already populated the marker; our lower-
        # authority scan_time populate must NOT replace it.
        oj = {"legs": [], "entry_underlying_spot": {
            "value": 500.0, "source": "same_fetch_equity_snapshot",
            "as_of": "2026-07-18T12:30:00+00:00", "status": "populated_at_stage"}}
        pe._populate_stage_entry_spot(
            oj, position_id=None, scan_spot=_scan_spot_marker(value=512.34))
        spot = oj["entry_underlying_spot"]
        self.assertEqual(spot["value"], 500.0)               # untouched
        self.assertEqual(spot["source"], "same_fetch_equity_snapshot")

    def test_replaces_a_prior_scan_time_or_unavailable_marker(self):
        # Same-or-lower authority markers (scan_time / unavailable) are ours to
        # (re)write — idempotent, never a downgrade.
        oj = {"legs": [], "entry_underlying_spot": {
            "value": None, "source": None, "as_of": None,
            "status": "unavailable_at_stage", "reason": "no_same_fetch_spot_source"}}
        pe._populate_stage_entry_spot(
            oj, position_id=None, scan_spot=_scan_spot_marker(value=512.34))
        self.assertEqual(oj["entry_underlying_spot"]["value"], 512.34)
        self.assertEqual(oj["entry_underlying_spot"]["source"], "scan_time")


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
        # ⑤ the stage seam re-fetches the suggestion (single()); serve it so the
        # scan-time spot on its order_json rides into _populate_stage_entry_spot.
        if self.table == "trade_suggestions" and self._op == "select":
            return _Resp(self.db.suggestion)
        return _Resp(None)


class _FakeSupabase:
    def __init__(self, portfolio, suggestion=None):
        self.portfolio = portfolio
        self.suggestion = suggestion
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


def _scan_spot_marker(value=512.34, as_of="2026-07-18T12:00:00+00:00"):
    """The shape build_scan_spot_capture stamps onto candidate/order_json."""
    return {"value": value, "source": "scanner_underlying_quote_mid",
            "as_of": as_of, "as_of_source": "provider_quote_ts"}


def _suggestion_with_scan_spot(scan_spot):
    """A persisted suggestion whose order_json carries the ⑤ scan-time spot —
    the honest carrier the stage seam reads off the re-fetched suggestion."""
    return {"id": "sug-1", "trace_id": "tr-1", "strategy": None,
            "window": None, "regime": None, "model_version": None,
            "features_hash": None,
            "order_json": {"underlying": "SPY", "legs": [],
                           "scan_underlying_spot": scan_spot}}


def _drive(route, snaps, suggestion=None, suggestion_id=None):
    """Run _stage_order_internal on the given route; return (order_json, fake).
    ``suggestion``/``suggestion_id`` exercise the ⑤ scan-time carrier read."""
    live_routed = route != "shadow"
    fake = _FakeSupabase({"id": "port-1",
                          "routing_mode": "live_eligible" if live_routed
                          else "shadow_only"},
                         suggestion=suggestion)
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
            suggestion_id_override=suggestion_id,
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


class TestStageRoutesPopulateScanTimeSpot(unittest.TestCase):
    """The ⑤ upgrade end-to-end: a suggestion whose order_json carries the
    scanner's scan-time spot rides into _stage_order_internal and the persisted
    order_json's entry_underlying_spot is POPULATED (source='scan_time') on ALL
    four routes — population sits before the exec-mode branch."""

    def _snaps(self):
        return {LONG_CALL: _snap(iv=0.2045, delta=0.60),
                SHORT_CALL: _snap(iv=0.1830, delta=0.45)}

    def _assert_populated(self, oj):
        spot = oj["entry_underlying_spot"]
        self.assertEqual(spot["value"], 512.34)
        self.assertEqual(spot["source"], "scan_time")
        self.assertEqual(spot["status"], "populated_at_stage")
        self.assertEqual(spot["as_of"], "2026-07-18T12:00:00+00:00")
        # IV/greeks co-capture is unaffected by the spot upgrade.
        self.assertEqual(oj["legs"][0]["iv"], 0.2045)

    def _drive_populated(self, route):
        return _drive(
            route, self._snaps(),
            suggestion=_suggestion_with_scan_spot(_scan_spot_marker()),
            suggestion_id="sug-1",
        )

    def test_internal_paper_route(self):
        oj, _ = self._drive_populated("internal")
        self._assert_populated(oj)

    def test_dry_run_route(self):
        oj, _ = self._drive_populated("dry_run")
        self._assert_populated(oj)

    def test_shadow_route(self):
        oj, fake = self._drive_populated("shadow")
        self._assert_populated(oj)
        self.assertTrue(
            any(u[1].get("execution_mode") == "shadow_blocked" for u in fake.updates)
        )

    def test_broker_live_route(self):
        oj, _ = self._drive_populated("live")
        self._assert_populated(oj)

    def test_carrier_present_but_nonpositive_value_types_unavailable(self):
        # A suggestion carries the marker but with a bad value → typed
        # unavailable with the precise reason; staging still succeeds.
        oj, _ = _drive(
            "internal", self._snaps(),
            suggestion=_suggestion_with_scan_spot(_scan_spot_marker(value=0.0)),
            suggestion_id="sug-1",
        )
        spot = oj["entry_underlying_spot"]
        self.assertIsNone(spot["value"])
        self.assertEqual(spot["status"], "unavailable_at_stage")
        self.assertEqual(spot["reason"], "scan_spot_nonpositive")

    def test_suggestion_without_scan_spot_stays_typed_unavailable(self):
        # A suggestion whose order_json has no scan_underlying_spot → the no-
        # carrier reason (byte-identical to the pre-⑤ behavior).
        oj, _ = _drive(
            "internal", self._snaps(),
            suggestion=_suggestion_with_scan_spot(None),
            suggestion_id="sug-1",
        )
        spot = oj["entry_underlying_spot"]
        self.assertIsNone(spot["value"])
        self.assertEqual(spot["reason"], "no_same_fetch_spot_source")


if __name__ == "__main__":
    unittest.main()
