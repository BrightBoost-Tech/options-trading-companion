"""Stage-time leg greeks population — observe-only, typed, no caps.

The greeks exposure envelope is DOUBLE-dormant (CLAUDE.md §8): no persisted
leg jsonb has ever carried a `greeks` key. The ledgered fix path is
populate-at-stage THEN separately decide caps. These tests pin the POPULATE
side only:

- RAW per-contract greeks stored EXACTLY as the snapshot reports them
  (LegGreeks convention, risk/position_model.py:240-243) — UNSIGNED by leg
  direction. The sign/ratio/×multiplier scaling is applied DOWNSTREAM by
  risk.position_model.aggregate_greeks via signed_ratio. Asserted end-to-end
  through that real canonical consumer on a vertical AND a condor, and at
  quantity > 1 (per-contract greeks unchanged; aggregate scales).
- Dark / partial / nonfinite / feed-fallback-without-greeks → typed
  unavailable marker (greeks=None + greeks_status), NEVER placeholder zeros.
- A CLOSE (position_id set) is exempt — never populated.
- Fail-soft: a fetch that raises types the leg unavailable, never blocks.

The route-level wiring proof (population actually runs on the persisted
paper_orders.order_json.legs on every staging route) lives in
test_stage_time_greeks_route.py — this file exercises the value semantics.
"""

import sys
import types
import unittest

# Stub alpaca-py so paper_endpoints imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.risk.position_model import (  # noqa: E402
    normalize_position,
    aggregate_greeks,
    LegGreeks,
)

# Per-contract greeks EXACTLY as a chain snapshot reports them — a call delta
# is +, a put delta is −. Distinct deltas per strike so netting is meaningful.
LONG_CALL = "O:SPY260116C00500000"
SHORT_CALL = "O:SPY260116C00510000"
SP_SHORT_PUT = "O:QQQ260116P00400000"
SP_LONG_PUT = "O:QQQ260116P00390000"
IC_SHORT_CALL = "O:QQQ260116C00450000"
IC_LONG_CALL = "O:QQQ260116C00460000"


def _snap(delta, gamma=0.02, theta=-0.03, vega=0.10, source="alpaca"):
    return {
        "quote": {"bid": 1.0, "ask": 1.2, "mid": 1.1, "last": 1.1},
        "greeks": {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega},
        "source": source,
        "retrieved_ts": "2026-07-18T00:00:00",
    }


def _fetch(mapping):
    return lambda sym: mapping.get(sym)


class TestPopulateSemantics(unittest.TestCase):
    def test_populated_leg_carries_typed_block(self):
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({LONG_CALL: _snap(0.60)})
        )
        leg = legs[0]
        self.assertEqual(leg["greeks_status"], "populated_at_stage")
        self.assertEqual(leg["greeks_source"], "alpaca")
        self.assertEqual(leg["greeks_multiplier"], 100)
        self.assertEqual(leg["greeks_as_of"], "2026-07-18T00:00:00")
        self.assertEqual(
            leg["greeks"], {"delta": 0.60, "gamma": 0.02, "theta": -0.03, "vega": 0.10}
        )

    def test_short_leg_greeks_are_unsigned_raw(self):
        # The short leg must store the RAW per-contract delta (+0.45), NOT a
        # direction-negated value — the sign is applied downstream.
        legs = [{"symbol": SHORT_CALL, "action": "sell", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({SHORT_CALL: _snap(0.45)})
        )
        self.assertEqual(legs[0]["greeks"]["delta"], 0.45)

    def test_polygon_source_recorded(self):
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None,
            snapshot_fetch=_fetch({LONG_CALL: _snap(0.60, source="polygon")}),
        )
        self.assertEqual(legs[0]["greeks_status"], "populated_at_stage")
        self.assertEqual(legs[0]["greeks_source"], "polygon")

    def test_dark_snapshot_types_unavailable_never_zeros(self):
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({})  # None → dark
        )
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")

    def test_partial_greeks_types_unavailable(self):
        # theta missing → the WHOLE leg is unavailable (no partial persist).
        snap = _snap(0.60)
        del snap["greeks"]["theta"]
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({LONG_CALL: snap})
        )
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")
        # source still recorded when a snapshot came back but was greek-light.
        self.assertEqual(legs[0]["greeks_source"], "alpaca")

    def test_nonfinite_greek_types_unavailable(self):
        snap = _snap(float("nan"))
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({LONG_CALL: snap})
        )
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")

    def test_feed_fallback_without_greeks_types_unavailable(self):
        # A Polygon fallback snapshot that carries no greeks key at all.
        snap = {"quote": {"bid": 1.0, "ask": 1.2}, "source": "polygon"}
        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch({LONG_CALL: snap})
        )
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")

    def test_fetch_exception_is_failsoft_unavailable(self):
        def _boom(_sym):
            raise RuntimeError("truth layer down")

        legs = [{"symbol": LONG_CALL, "action": "buy", "quantity": 1}]
        # Must NOT raise — staging proceeds, leg typed unavailable.
        pe._populate_stage_leg_greeks(legs, position_id=None, snapshot_fetch=_boom)
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")

    def test_non_option_leg_types_unavailable(self):
        legs = [{"symbol": "SPY", "action": "buy", "quantity": 1}]  # equity, not OCC
        called = []
        pe._populate_stage_leg_greeks(
            legs, position_id=None,
            snapshot_fetch=lambda s: called.append(s),
        )
        self.assertEqual(called, [])  # no option snapshot fetched
        self.assertIsNone(legs[0]["greeks"])
        self.assertEqual(legs[0]["greeks_status"], "unavailable_at_stage")

    def test_close_order_is_exempt(self):
        legs = [{"symbol": LONG_CALL, "action": "sell", "quantity": 1}]
        pe._populate_stage_leg_greeks(
            legs, position_id="pos-1",
            snapshot_fetch=_fetch({LONG_CALL: _snap(0.60)}),
        )
        # No greeks key added at all on the exit path.
        self.assertNotIn("greeks", legs[0])
        self.assertNotIn("greeks_status", legs[0])


class TestSignConventionThroughCanonicalConsumer(unittest.TestCase):
    """The strongest assertion: run the persisted (UNSIGNED) leg greeks + the
    preserved leg action through the REAL payoff/stress consumer
    (risk.position_model.aggregate_greeks) and assert the SIGNED netting. A
    wrongly-negated short leg would net differently — this catches an invented
    convention."""

    @staticmethod
    def _aggregate(legs, signed_quantity):
        pos = {"quantity": signed_quantity, "avg_entry_price": 1.50, "legs": legs}
        gbs = {
            l["symbol"]: LegGreeks(**l["greeks"]) for l in legs if l.get("greeks")
        }
        cp = normalize_position(pos, greeks_by_symbol=gbs)
        return aggregate_greeks(cp)

    def test_vertical_nets_signed_delta(self):
        legs = [
            {"symbol": LONG_CALL, "action": "buy", "quantity": 1},
            {"symbol": SHORT_CALL, "action": "sell", "quantity": 1},
        ]
        pe._populate_stage_leg_greeks(
            legs, position_id=None,
            snapshot_fetch=_fetch({LONG_CALL: _snap(0.60), SHORT_CALL: _snap(0.45)}),
        )
        exp = self._aggregate(legs, signed_quantity=1)
        # (long 0.60 − short 0.45) × 1 × 100 = +15
        self.assertAlmostEqual(exp.delta_dollars_per_underlying_point, 15.0)
        self.assertTrue(exp.complete)

    def test_vertical_quantity_scales_but_per_contract_greeks_do_not(self):
        legs = [
            {"symbol": LONG_CALL, "action": "buy", "quantity": 3},
            {"symbol": SHORT_CALL, "action": "sell", "quantity": 3},
        ]
        pe._populate_stage_leg_greeks(
            legs, position_id=None,
            snapshot_fetch=_fetch({LONG_CALL: _snap(0.60), SHORT_CALL: _snap(0.45)}),
        )
        # Per-contract greeks unchanged by quantity.
        self.assertEqual(legs[0]["greeks"]["delta"], 0.60)
        self.assertEqual(legs[1]["greeks"]["delta"], 0.45)
        exp = self._aggregate(legs, signed_quantity=3)
        # (0.60 − 0.45) × 3 × 100 = +45
        self.assertAlmostEqual(exp.delta_dollars_per_underlying_point, 45.0)

    def test_condor_nets_delta_neutral(self):
        # Balanced iron condor → net delta ≈ 0. Puts store − deltas, calls +.
        legs = [
            {"symbol": SP_SHORT_PUT, "action": "sell", "quantity": 1},
            {"symbol": SP_LONG_PUT, "action": "buy", "quantity": 1},
            {"symbol": IC_SHORT_CALL, "action": "sell", "quantity": 1},
            {"symbol": IC_LONG_CALL, "action": "buy", "quantity": 1},
        ]
        snaps = {
            SP_SHORT_PUT: _snap(-0.30),
            SP_LONG_PUT: _snap(-0.20),
            IC_SHORT_CALL: _snap(0.30),
            IC_LONG_CALL: _snap(0.20),
        }
        pe._populate_stage_leg_greeks(
            legs, position_id=None, snapshot_fetch=_fetch(snaps)
        )
        # Puts keep their NEGATIVE raw delta (unsigned by direction).
        self.assertEqual(legs[0]["greeks"]["delta"], -0.30)
        # quantity < 0 == credit structure (iron condor opened for credit).
        exp = self._aggregate(legs, signed_quantity=-1)
        self.assertTrue(exp.complete)
        # +30 (short put) −20 (long put) −30 (short call) +20 (long call) = 0
        self.assertLess(abs(exp.delta_dollars_per_underlying_point), 1e-9)

    def test_incomplete_when_one_leg_dark(self):
        legs = [
            {"symbol": LONG_CALL, "action": "buy", "quantity": 1},
            {"symbol": SHORT_CALL, "action": "sell", "quantity": 1},
        ]
        # Short leg dark → typed unavailable → excluded from greeks_by_symbol.
        pe._populate_stage_leg_greeks(
            legs, position_id=None,
            snapshot_fetch=_fetch({LONG_CALL: _snap(0.60)}),  # SHORT_CALL absent
        )
        self.assertEqual(legs[1]["greeks_status"], "unavailable_at_stage")
        exp = self._aggregate(legs, signed_quantity=1)
        # A missing leg greek must yield None + complete=False (H9), never a
        # fabricated partial total.
        self.assertFalse(exp.complete)
        self.assertIsNone(exp.delta_dollars_per_underlying_point)


if __name__ == "__main__":
    unittest.main()
