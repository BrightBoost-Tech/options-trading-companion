"""Entry round-trip cost gate — pre-broker-submit rejection (SOFI 2026-06-30).

The first live trade (a SOFI call debit spread) was admitted on EV +$30.63 but
its EXECUTABLE round-trip cost (~$135 of bid/ask cross) made it
underwater-on-executable from entry; it force-closed at a 100%-spread-cost loss.
The ranker's pre-stage cost gate used a 5%-of-EV slippage PROXY
(canonical_ranker._estimate_slippage) — far too loose — and waved SOFI through.

This gate charges the REAL executable cross (Σ per-leg (ask−bid) × contracts ×
100), priced on the SAME executable basis the exit corroboration uses
(exit_mark_corroboration.executable_roundtrip_cost → compute_corroboration — one
model both ends, zero refetch), against the suggestion's gross EV, and REJECTS
pre-broker-submit when honest_ev_after_cost = gross_EV − round_trip is below
MIN_EDGE_AFTER_COSTS ($15). OPEN orders only.

Pins:
1. SOFI 06-30 fixture → REJECT + blocked_reason='ev_below_roundtrip_cost'.
2. Tight-spread + real edge → PASSES (anti-over-reject).
3. UNIFICATION — the entry round-trip's executable basis == the exit's
   executable_close_estimate basis (same long→bid/short→ask numbers both ends).
4. Flag OFF → legacy (no round-trip reject; the SOFI fixture would stage).
5. Flag parser default-ON, test-pinned both ways.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.paper_endpoints import (  # noqa: E402
    _apply_entry_roundtrip_gate,
    _entry_roundtrip_cost_gate_enabled,
    EntryRoundtripCostExceedsEV,
)
from packages.quantum.analytics.exit_mark_corroboration import (  # noqa: E402
    executable_roundtrip_cost,
    executable_close_estimate,
)

FLAG = "ENTRY_ROUNDTRIP_COST_GATE_ENABLED"

# ── SOFI 2026-06-30 fixture ─────────────────────────────────────────────────
SOFI_LONG = "O:SOFI260807C00017000"   # bid/ask 1.93/2.16, cross 0.23
SOFI_SHORT = "O:SOFI260807C00020500"  # bid/ask 0.67/0.71, cross 0.04
SOFI_EV = 30.628
SOFI_QTY = 5
# round-trip = (0.23 + 0.04) × 5 × 100 = $135 → net ≈ 30.628 − 135 = −104.37
SOFI_QUOTES = {
    SOFI_LONG: {"bid": 1.93, "ask": 2.16},
    SOFI_SHORT: {"bid": 0.67, "ask": 0.71},
}


def _ticket(*, expected_value, legs, quantity):
    """legs: list of (occ, action, qty) tuples."""
    leg_objs = [
        types.SimpleNamespace(symbol=occ, action=action, quantity=qty, strike=None)
        for (occ, action, qty) in legs
    ]
    return types.SimpleNamespace(
        expected_value=expected_value, legs=leg_objs, quantity=quantity,
    )


def _sofi_ticket(expected_value=SOFI_EV):
    return _ticket(
        expected_value=expected_value,
        legs=[(SOFI_LONG, "buy", SOFI_QTY), (SOFI_SHORT, "sell", SOFI_QTY)],
        quantity=SOFI_QTY,
    )


class _FakeQuery:
    def __init__(self, parent):
        self.parent = parent

    def update(self, row):
        self.parent.updates.append(row)
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=[{"id": "row-1"}])


class _FakeSupabase:
    def __init__(self):
        self.updates = []

    def table(self, name):
        return _FakeQuery(self)


class _GateTestBase(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(FLAG)
        os.environ.pop(FLAG, None)  # default ON

    def tearDown(self):
        os.environ.pop(FLAG, None)
        if self._saved is not None:
            os.environ[FLAG] = self._saved


# ── 1. SOFI 06-30 → REJECT ──────────────────────────────────────────────────

class TestSofiReject(_GateTestBase):
    def test_pure_roundtrip_cost_is_135(self):
        rt = executable_roundtrip_cost(
            legs=[
                {"occ_symbol": SOFI_LONG, "action": "buy", "quantity": SOFI_QTY},
                {"occ_symbol": SOFI_SHORT, "action": "sell", "quantity": SOFI_QTY},
            ],
            leg_quotes=SOFI_QUOTES,
            quantity=SOFI_QTY,
        )
        self.assertTrue(rt["quote_complete"])
        self.assertAlmostEqual(rt["round_trip"], 135.0, places=4)

    def test_rejects_and_stamps_blocked_reason(self):
        sb = _FakeSupabase()
        with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
            _apply_entry_roundtrip_gate(
                sb, _sofi_ticket(), position_id=None,
                entry_leg_quotes=SOFI_QUOTES, suggestion_id="sofi-sid",
            )
        exc = ctx.exception
        # honest_ev_after_cost is WELL below the $15 floor (don't hard-pin $).
        self.assertLess(exc.net, 15.0)
        self.assertAlmostEqual(exc.round_trip, 135.0, places=4)
        self.assertAlmostEqual(exc.gross_ev, SOFI_EV, places=4)
        # blocked_reason stamped with the numbers (mirrors _stamp_blocked_reason)
        self.assertEqual(len(sb.updates), 1)
        self.assertEqual(sb.updates[0]["blocked_reason"], "ev_below_roundtrip_cost")
        self.assertIn("round_trip", sb.updates[0]["blocked_detail"])


# ── 2. Tight spread + real edge → PASSES (anti-over-reject) ─────────────────

class TestTightSpreadPasses(_GateTestBase):
    def test_does_not_reject_legitimate_trade(self):
        # A few-cent total cross with a healthy EV must survive the gate.
        long_occ = "O:XYZ260807C00050000"   # bid/ask 2.00/2.02, cross 0.02
        short_occ = "O:XYZ260807C00055000"  # bid/ask 1.00/1.01, cross 0.01
        quotes = {
            long_occ: {"bid": 2.00, "ask": 2.02},
            short_occ: {"bid": 1.00, "ask": 1.01},
        }
        # round-trip = (0.02 + 0.01) × 1 × 100 = $3 → net = 25 − 3 = $22 ≥ $15
        ticket = _ticket(
            expected_value=25.0,
            legs=[(long_occ, "buy", 1), (short_occ, "sell", 1)],
            quantity=1,
        )
        sb = _FakeSupabase()
        # Must NOT raise, and must NOT stamp a block.
        _apply_entry_roundtrip_gate(
            sb, ticket, position_id=None, entry_leg_quotes=quotes,
            suggestion_id="xyz-sid",
        )
        self.assertEqual(sb.updates, [])


# ── 3. UNIFICATION — one model both ends ────────────────────────────────────

class TestUnification(_GateTestBase):
    def test_entry_basis_equals_exit_basis(self):
        legs = [
            {"occ_symbol": SOFI_LONG, "action": "buy", "quantity": SOFI_QTY, "strike": 17.0},
            {"occ_symbol": SOFI_SHORT, "action": "sell", "quantity": SOFI_QTY, "strike": 20.5},
        ]
        # Entry side: round-trip cost reuses compute_corroboration's legs_quotes.
        entry = executable_roundtrip_cost(
            legs=legs, leg_quotes=SOFI_QUOTES, quantity=SOFI_QTY,
        )
        # Exit side: the achievable-close estimate over the SAME quotes.
        def _snapshot_fn(occs):
            return {occ: {"quote": SOFI_QUOTES.get(occ, {})} for occ in occs}

        exit_est = executable_close_estimate(
            {"legs": legs, "quantity": SOFI_QTY, "avg_entry_price": 1.49},
            snapshot_fn=_snapshot_fn,
        )

        def _basis(legs_quotes):
            return [
                (lq["occ"], lq["position_side"], lq["executable_side"], lq["executable_price"])
                for lq in legs_quotes
            ]

        # Identical long→bid / short→ask per-leg executable numbers both ends.
        self.assertEqual(_basis(entry["legs_quotes"]), _basis(exit_est["legs_quotes"]))
        # Long → sell at BID 1.93; short → buy at ASK 0.71.
        self.assertEqual(
            _basis(entry["legs_quotes"]),
            [
                (SOFI_LONG, "long", "bid", 1.93),
                (SOFI_SHORT, "short", "ask", 0.71),
            ],
        )


# ── 4. Flag OFF → legacy (no round-trip reject) ─────────────────────────────

class TestFlagOffLegacy(_GateTestBase):
    def test_sofi_would_stage_when_disabled(self):
        for off in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {FLAG: off}):
                sb = _FakeSupabase()
                # No raise → the SOFI fixture would proceed to stage (legacy).
                _apply_entry_roundtrip_gate(
                    sb, _sofi_ticket(), position_id=None,
                    entry_leg_quotes=SOFI_QUOTES, suggestion_id="sofi-sid",
                )
                self.assertEqual(sb.updates, [], off)


# ── 5. Flag parser — default-ON, test-pinned both ways ──────────────────────

class TestFlagParser(_GateTestBase):
    def test_default_on_when_unset_or_empty(self):
        os.environ.pop(FLAG, None)
        self.assertTrue(_entry_roundtrip_cost_gate_enabled())
        for v in ("", "   "):
            with patch.dict(os.environ, {FLAG: v}):
                self.assertTrue(_entry_roundtrip_cost_gate_enabled(), repr(v))

    def test_on_for_truthy_and_anything_non_falsy(self):
        for v in ("1", "true", "yes", "on", "anything"):
            with patch.dict(os.environ, {FLAG: v}):
                self.assertTrue(_entry_roundtrip_cost_gate_enabled(), v)

    def test_off_only_for_explicit_falsy(self):
        for v in ("0", "false", "no", "off", " OFF "):
            with patch.dict(os.environ, {FLAG: v}):
                self.assertFalse(_entry_roundtrip_cost_gate_enabled(), v)


# ── 6. Guard rails — exempt / skip paths (no raise) ─────────────────────────

class TestExemptPaths(_GateTestBase):
    def test_close_order_is_exempt(self):
        sb = _FakeSupabase()
        _apply_entry_roundtrip_gate(
            sb, _sofi_ticket(), position_id="pos-123",  # CLOSE
            entry_leg_quotes=SOFI_QUOTES, suggestion_id="sofi-sid",
        )
        self.assertEqual(sb.updates, [])

    def test_no_ev_skips(self):
        sb = _FakeSupabase()
        _apply_entry_roundtrip_gate(
            sb, _sofi_ticket(expected_value=None), position_id=None,
            entry_leg_quotes=SOFI_QUOTES, suggestion_id="sofi-sid",
        )
        self.assertEqual(sb.updates, [])

    def test_empty_quotes_skips(self):
        sb = _FakeSupabase()
        _apply_entry_roundtrip_gate(
            sb, _sofi_ticket(), position_id=None,
            entry_leg_quotes={}, suggestion_id="sofi-sid",
        )
        self.assertEqual(sb.updates, [])

    def test_incomplete_executable_quote_allows(self):
        # One leg dark (bid 0) → round-trip indeterminate → allow (no fabricate).
        quotes = {
            SOFI_LONG: {"bid": 1.93, "ask": 2.16},
            SOFI_SHORT: {"bid": 0.0, "ask": 0.0},
        }
        sb = _FakeSupabase()
        _apply_entry_roundtrip_gate(
            sb, _sofi_ticket(), position_id=None,
            entry_leg_quotes=quotes, suggestion_id="sofi-sid",
        )
        self.assertEqual(sb.updates, [])


if __name__ == "__main__":
    unittest.main()
