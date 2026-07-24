"""Gate qty-scaling fix — OPTION A (2026-07-09): shadow decisions fixed,
LIVE path observe-only.

The entry round-trip gate compared gross_ev (per-STRUCTURE, unscaled) against
round_trip (qty-SCALED). At qty>1 this false-rejected economic trades — proven
against history: the 07-07 aggressive qty-4 candidate (gross_ev 42.45, sized
round_trip 28 → old net +14.45 REJECT; per-contract +35.45 PASS) was a real
LIVE-champion false-reject. Option A fixes the arithmetic for SHADOW cohorts
now, keeps the LIVE decision UNCHANGED (observe-only) behind
GATE_QTY_FIX_LIVE_ENABLED (default OFF), and logs what the fix WOULD decide.

THE SAFETY PROPERTY (pinned): this PR changes ZERO live decisions.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.paper_endpoints import (  # noqa: E402
    _apply_entry_roundtrip_gate,
    _gate_qty_fix_live_enabled,
    EntryRoundtripCostExceedsEV,
)
from packages.quantum.analytics.exit_mark_corroboration import (  # noqa: E402
    executable_roundtrip_cost,
)

GATE_FLAG = "ENTRY_ROUNDTRIP_COST_GATE_ENABLED"
LIVE_FLAG = "GATE_QTY_FIX_LIVE_ENABLED"

# A 4-leg condor with a uniform per-leg cross of 0.0175 → per-contract
# round_trip = 4 × 0.0175 × 100 = $7.00. gross_ev 42.45 (the 07-07 candidate).
_LEGS_0707 = [
    ("O:QQQ260821P00640000", "buy", None),
    ("O:QQQ260821P00645000", "sell", None),
    ("O:QQQ260821C00765000", "sell", None),
    ("O:QQQ260821C00770000", "buy", None),
]
_QUOTES_0707 = {
    "O:QQQ260821P00640000": {"bid": 1.00, "ask": 1.0175},
    "O:QQQ260821P00645000": {"bid": 1.00, "ask": 1.0175},
    "O:QQQ260821C00765000": {"bid": 1.00, "ask": 1.0175},
    "O:QQQ260821C00770000": {"bid": 1.00, "ask": 1.0175},
}


def _ticket(*, expected_value, quantity, legs=_LEGS_0707):
    leg_objs = [
        types.SimpleNamespace(symbol=occ, action=a, quantity=quantity, strike=None)
        for (occ, a, _q) in legs
    ]
    return types.SimpleNamespace(
        expected_value=expected_value, legs=leg_objs, quantity=quantity,
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


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (GATE_FLAG, LIVE_FLAG)}
        os.environ.pop(GATE_FLAG, None)   # gate default ON
        os.environ.pop(LIVE_FLAG, None)   # live-fix default OFF (observe-only)

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


class TestPerContractReturn(_Base):
    def test_round_trip_per_contract_equals_sized_at_qty1(self):
        rt = executable_roundtrip_cost(
            legs=[{"occ_symbol": o, "action": a, "quantity": 1} for (o, a, _) in _LEGS_0707],
            leg_quotes=_QUOTES_0707, quantity=1,
        )
        self.assertAlmostEqual(rt["round_trip"], 7.0, places=4)
        self.assertAlmostEqual(rt["round_trip_per_contract"], 7.0, places=4)

    def test_round_trip_per_contract_is_sized_over_qty(self):
        rt = executable_roundtrip_cost(
            legs=[{"occ_symbol": o, "action": a, "quantity": 4} for (o, a, _) in _LEGS_0707],
            leg_quotes=_QUOTES_0707, quantity=4,
        )
        self.assertAlmostEqual(rt["round_trip"], 28.0, places=4)       # sized
        self.assertAlmostEqual(rt["round_trip_per_contract"], 7.0, places=4)


class TestQty1Invariant(_Base):
    def test_qty1_decision_identical_either_way(self):
        # 07-08-style qty-1: gross_ev 41.22, round_trip 39 → net +2.22 reject.
        # Make a per-contract round_trip of 39 at qty 1.
        quotes = {o: {"bid": 1.00, "ask": 1.0975} for (o, _a, _q) in _LEGS_0707}
        # 4 legs × 0.0975 × 100 = 39.0
        t = _ticket(expected_value=41.22, quantity=1)
        sb = _FakeSupabase()
        with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
            _apply_entry_roundtrip_gate(
                sb, t, None, quotes, suggestion_id="q1", is_shadow=False,
            )
        # applied == legacy == per-contract (identical at qty1); reject at +2.22
        self.assertAlmostEqual(ctx.exception.net, 2.22, places=2)
        self.assertAlmostEqual(ctx.exception.round_trip, 39.0, places=2)


class TestLiveObserveOnly(_Base):
    def test_0707_live_decision_stays_reject_but_logs_would_pass(self):
        """THE OBSERVE-ONLY PIN: the 07-07 qty-4 live candidate — old_net
        +14.45 (< $15) stays REJECT on the live path, AND the
        [GATE_QTY_SCALED_SHADOW] trail fires saying new_decision=allow."""
        t = _ticket(expected_value=42.45, quantity=4)
        sb = _FakeSupabase()
        with self.assertLogs("packages.quantum.paper_endpoints", "WARNING") as cm:
            with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
                _apply_entry_roundtrip_gate(
                    sb, t, None, _QUOTES_0707, suggestion_id="live0707",
                    is_shadow=False,
                )
        # DECISION unchanged: applied = legacy net +14.45 → reject.
        self.assertAlmostEqual(ctx.exception.net, 14.45, places=2)
        self.assertAlmostEqual(ctx.exception.round_trip, 28.0, places=2)  # sized
        blob = "\n".join(cm.output)
        self.assertIn("[GATE_QTY_SCALED_SHADOW]", blob)
        self.assertIn("old_decision=reject", blob)
        self.assertIn("new_decision=allow", blob)

    def test_0707_live_flag_on_applies_fix_and_passes(self):
        """Option-B preview: with GATE_QTY_FIX_LIVE_ENABLED=1 the same live
        candidate PASSES (per-contract +35.45 ≥ $15)."""
        t = _ticket(expected_value=42.45, quantity=4)
        sb = _FakeSupabase()
        with patch.dict(os.environ, {LIVE_FLAG: "1"}):
            _apply_entry_roundtrip_gate(
                sb, t, None, _QUOTES_0707, suggestion_id="live0707on",
                is_shadow=False,
            )  # no raise → allowed
        self.assertEqual(sb.updates, [])


class TestShadowFixed(_Base):
    def test_shadow_qty7_false_reject_now_passes(self):
        """The 19:02Z neutral qty-7 twin: sized round_trip 154 → per-contract
        22 → net 42.14 − 22 = +20.14 ≥ $15 → PASS (was −111.86 reject)."""
        # per-leg cross 0.055 → per-contract 4×5.5 = 22; ×7 sized = 154.
        quotes = {o: {"bid": 1.00, "ask": 1.055} for (o, _a, _q) in _LEGS_0707}
        t = _ticket(expected_value=42.14, quantity=7)
        sb = _FakeSupabase()
        _apply_entry_roundtrip_gate(
            sb, t, None, quotes, suggestion_id="shadow1902", is_shadow=True,
        )  # no raise → the SHADOW decision changed to allow
        self.assertEqual(sb.updates, [])

    def test_shadow_correct_reject_preserved(self):
        """A genuinely uneconomic qty-7 shadow (per-contract net < $15) still
        rejects — the fix does not blanket-pass."""
        # per-leg cross 0.10 → per-contract 40; net 42.14 − 40 = +2.14 < 15.
        quotes = {o: {"bid": 1.00, "ask": 1.10} for (o, _a, _q) in _LEGS_0707}
        t = _ticket(expected_value=42.14, quantity=7)
        sb = _FakeSupabase()
        with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
            _apply_entry_roundtrip_gate(
                sb, t, None, quotes, suggestion_id="shadowbad", is_shadow=True,
            )
        self.assertAlmostEqual(ctx.exception.net, 2.14, places=2)  # per-contract
        self.assertAlmostEqual(ctx.exception.round_trip, 40.0, places=2)


class TestPostCalibrationX05(_Base):
    def test_halved_ev_gates_sensibly_both_cohorts(self):
        """gross_ev halved by ×0.5 calibration; the fix only rescales COST, so
        it stays basis-correct. 07-07 structure at halved EV 21.22:
        per-contract net 21.22 − 7 = +14.22 < 15 → reject even fixed."""
        t = _ticket(expected_value=21.22, quantity=4)
        sb = _FakeSupabase()
        # shadow: fixed decision, per-contract net +14.22 < 15 → reject.
        with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
            _apply_entry_roundtrip_gate(
                sb, t, None, _QUOTES_0707, suggestion_id="x05s", is_shadow=True,
            )
        self.assertAlmostEqual(ctx.exception.net, 14.22, places=2)


class TestFlagParser(_Base):
    def test_live_fix_default_off(self):
        os.environ.pop(LIVE_FLAG, None)
        self.assertFalse(_gate_qty_fix_live_enabled())
        for v in ("", "   ", "0", "false", "no", "off", "anything"):
            with patch.dict(os.environ, {LIVE_FLAG: v}):
                self.assertFalse(_gate_qty_fix_live_enabled(), repr(v))

    def test_live_fix_explicit_opt_in(self):
        for v in ("1", "true", "yes", "on", " ON "):
            with patch.dict(os.environ, {LIVE_FLAG: v}):
                self.assertTrue(_gate_qty_fix_live_enabled(), v)


if __name__ == "__main__":
    unittest.main()
