"""check_greeks null-safety + typed coverage — dormancy preserved (capacity lane).

CRASH THIS PINS (risk_envelope.check_greeks, pre-fix @ 72f689c0:271-275):

    greeks = leg.get("greeks") or pos.get("greeks") or {}
    d = float(greeks.get("delta", 0)) * abs(qty) * 100
    g = float(greeks.get("gamma", 0)) * abs(qty) * 100
    ...

``dict.get(key, 0)`` returns the DEFAULT only when the key is ABSENT. When a
greek key is PRESENT with an explicit ``None`` value, ``.get`` returns ``None``
and ``float(None)`` raises ``TypeError`` — the whole envelope evaluation
(``check_all_envelopes``: greeks → concentration → loss brake → stress) dies.

REACHABILITY:
  - BEFORE #1259 — UNREACHABLE. §8 double-dormancy: no persisted leg jsonb ever
    carried a ``greeks`` key and no position carried one, so ``greeks`` always
    resolved to ``{}`` via the ``or {}`` fallback; ``{}.get(k, 0)`` returns the
    default 0 and ``float(0)`` never raises.
  - AFTER #1259 (stage-time greek population) — legs carry, for the FIRST time,
    real non-empty greeks dicts (or ``greeks=None`` for typed-unavailable legs).
    A fully-``None`` block is still falsy and resolves to ``{}`` (safe), but the
    surface is now live: (a) the ``or``-chain silently fabricated a ZERO
    contribution for an unavailable leg (H9 violation — an unpriceable value
    must contribute nothing AND flag partial, never a silent 0); (b) any dict
    that ever carries an explicit-None / nonfinite value for a present key trips
    the TypeError with no guard.

FIX: a leg contributes to the portfolio sums only when ALL of
delta/gamma/vega/theta are present and finite; otherwise it contributes NOTHING
and is counted as uncovered. Coverage is reported on the result
(``greeks_coverage`` = {legs_total, legs_with_greeks, complete}). Caps are
untouched (every greek limit still defaults 0; the ``if limit > 0`` gate is
unchanged), so while dormant the (violations, greeks) output is unchanged for
every input that did not previously raise.

Tests inject at ORIGIN (positions + config) and assert at the TOP — the greeks
result and the crash-safety are driven through the production
``check_all_envelopes`` route, not just the isolated helper (repo doctrine:
drive the entrypoint, assert the output).
"""

import math
import sys
import types
import unittest

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.risk.risk_envelope import (  # noqa: E402
    check_greeks,
    check_all_envelopes,
    EnvelopeConfig,
)

EQUITY = 100_000.0
_FULL = {"delta": 0.5, "gamma": 0.01, "vega": 0.05, "theta": -0.02}
_ABSENT = object()  # sentinel: leg carries NO greeks key at all


def _pos(pos_id="NFLX-1", symbol="NFLX", quantity=2.0, leg_greeks=(None, None)):
    """A NORMALIZABLE defined-risk put debit spread (so _pos_risk succeeds and
    check_all_envelopes runs end-to-end); each leg is stamped with the greeks
    block from ``leg_greeks`` (a per-leg value: a dict, ``None``, or absent when
    the special sentinel ``_ABSENT`` is passed).
    """
    legs = [
        {"symbol": "NFLX260918P00100000", "action": "buy", "type": "put",
         "strike": 100.0, "expiry": "2026-09-18", "quantity": 2},
        {"symbol": "NFLX260918P00095000", "action": "sell", "type": "put",
         "strike": 95.0, "expiry": "2026-09-18", "quantity": 2},
    ]
    for leg, g in zip(legs, leg_greeks):
        if g is not _ABSENT:
            leg["greeks"] = g
    return {
        "id": pos_id, "symbol": symbol, "quantity": quantity,
        "avg_entry_price": 3.08, "unrealized_pl": 0.0,
        "legs": legs, "portfolio_id": "pf-1",
    }


def _isolating_config(**overrides) -> EnvelopeConfig:
    """Caps that let ONLY the greeks check speak: concentration/stress can't
    mask (or manufacture) the greeks assertion on a single-symbol book."""
    cfg = EnvelopeConfig()
    cfg.max_single_symbol_pct = 1.0
    cfg.max_sector_pct = 1.0
    cfg.max_same_expiry_pct = 1.0
    cfg.max_stress_loss_pct = 10.0
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _greeks_violations(result):
    return [v for v in result.violations if v.envelope.startswith("greeks_")]


# ---------------------------------------------------------------------------
# (d) Regression: the EXACT pre-fix crash shape, reproduced against the old
#     code-path logic, then proven safe through the production route.
# ---------------------------------------------------------------------------

def _old_leg_greek_term(greeks, key, qty):
    """VERBATIM pre-fix aggregation term (risk_envelope.check_greeks @ 72f689c0
    line 272): ``float(greeks.get(key, 0)) * abs(qty) * 100``. Reproduced here
    so the regression asserts the ORIGINAL crash, not a paraphrase."""
    return float(greeks.get(key, 0)) * abs(qty) * 100


class TestPreFixCrashRegression(unittest.TestCase):
    def test_old_logic_raises_on_present_none_greek(self):
        # A present-but-None greek key is exactly what #1259's typed-unavailable
        # path (and any partial feed) could surface. The DEFAULT in .get(k, 0)
        # does NOT fire (the key exists) → float(None) → TypeError. This is the
        # pre-fix crash, pinned.
        malformed = {"delta": None, "gamma": 0.01, "vega": 0.05, "theta": -0.02}
        with self.assertRaises(TypeError):
            _old_leg_greek_term(malformed, "delta", 2.0)

    def test_new_route_does_not_raise_on_present_none_greek(self):
        # Same malformed leg, driven through the PRODUCTION entrypoint. Post-fix:
        # no raise; the malformed leg contributes nothing and is uncovered.
        malformed = {"delta": None, "gamma": 0.01, "vega": 0.05, "theta": -0.02}
        result = check_all_envelopes(
            positions=[_pos(leg_greeks=(malformed, None))],
            equity=EQUITY, config=_isolating_config(),
        )
        self.assertEqual(result.portfolio_greeks["delta"], 0.0)
        self.assertEqual(result.greeks_coverage["legs_total"], 2)
        self.assertEqual(result.greeks_coverage["legs_with_greeks"], 0)
        self.assertFalse(result.greeks_coverage["complete"])


# ---------------------------------------------------------------------------
# (a) None / missing / nonfinite greeks → no raise, typed coverage, zero
#     greeks-violations while caps are 0.
# ---------------------------------------------------------------------------

class TestNullSafety(unittest.TestCase):
    def _route(self, leg_greeks, **cfg):
        return check_all_envelopes(
            positions=[_pos(leg_greeks=leg_greeks)],
            equity=EQUITY, config=_isolating_config(**cfg),
        )

    def test_greeks_none_both_legs(self):
        # #1259 writes greeks=None for a typed-unavailable leg.
        r = self._route((None, None))
        self.assertEqual(r.portfolio_greeks,
                         {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0})
        self.assertEqual(r.greeks_coverage,
                         {"legs_total": 2, "legs_with_greeks": 0, "complete": False})
        self.assertEqual(_greeks_violations(r), [])

    def test_greeks_key_absent(self):
        # §8 pre-#1259 production shape: no greeks key at all.
        r = self._route((_ABSENT, _ABSENT))
        self.assertEqual(r.portfolio_greeks["delta"], 0.0)
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 0)
        self.assertEqual(_greeks_violations(r), [])

    def test_partial_dict_missing_keys(self):
        # A dict with only delta present — the other three ABSENT. Pre-fix this
        # SILENTLY fabricated 0 for gamma/vega/theta AND summed the partial
        # delta; post-fix the whole leg is uncovered, contributing nothing.
        r = self._route(({"delta": 0.5}, None))
        self.assertEqual(r.portfolio_greeks["delta"], 0.0)
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 0)
        self.assertEqual(_greeks_violations(r), [])

    def test_present_none_value(self):
        r = self._route(({"delta": 0.5, "gamma": None, "vega": 0.05, "theta": -0.02}, None))
        self.assertEqual(r.portfolio_greeks["gamma"], 0.0)
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 0)
        self.assertEqual(_greeks_violations(r), [])

    def test_nonfinite_values_nan_and_inf(self):
        nan_leg = {"delta": float("nan"), "gamma": 0.01, "vega": 0.05, "theta": -0.02}
        inf_leg = {"delta": 0.5, "gamma": 0.01, "vega": float("inf"), "theta": -0.02}
        r = self._route((nan_leg, inf_leg))
        # Neither leg contributes; nothing nonfinite leaks into the aggregate.
        for k, val in r.portfolio_greeks.items():
            self.assertTrue(math.isfinite(val), k)
            self.assertEqual(val, 0.0, k)
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 0)
        self.assertEqual(_greeks_violations(r), [])

    def test_string_and_bool_greeks_rejected(self):
        # bool is a python int subclass — float(True) == 1.0 would fabricate a
        # phantom exposure; the guard rejects it. A non-numeric string too.
        bad = {"delta": True, "gamma": "n/a", "vega": 0.05, "theta": -0.02}
        r = self._route((bad, None))
        self.assertEqual(r.portfolio_greeks["delta"], 0.0)
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 0)
        self.assertEqual(_greeks_violations(r), [])

    def test_mixed_book_one_covered_one_dark(self):
        # One complete finite leg + one dark leg → aggregate is PARTIAL and says
        # so; the covered leg still contributes its real value.
        r = self._route((dict(_FULL), None))
        self.assertEqual(r.greeks_coverage,
                         {"legs_total": 2, "legs_with_greeks": 1, "complete": False})
        self.assertEqual(r.portfolio_greeks["delta"], 0.5 * 2 * 100)  # covered leg only

    def test_empty_book_coverage_is_trivially_complete(self):
        r = check_all_envelopes(positions=[], equity=EQUITY, config=_isolating_config())
        self.assertEqual(r.greeks_coverage,
                         {"legs_total": 0, "legs_with_greeks": 0, "complete": True})
        self.assertEqual(_greeks_violations(r), [])


# ---------------------------------------------------------------------------
# (b) Real greeks + caps STILL 0 → no greeks-violation (dormancy preserved),
#     and (proof) the aggregate is byte-identical to the pre-fix aggregation
#     for the two shapes that actually occur (all-greekless, all-complete).
# ---------------------------------------------------------------------------

class TestDormancyPreserved(unittest.TestCase):
    def test_real_greeks_no_cap_no_violation(self):
        r = check_all_envelopes(
            positions=[_pos(leg_greeks=(dict(_FULL), dict(_FULL)))],
            equity=EQUITY, config=_isolating_config(),  # all greek caps default 0
        )
        self.assertEqual(_greeks_violations(r), [])
        self.assertEqual(r.greeks_coverage["legs_with_greeks"], 2)
        self.assertTrue(r.greeks_coverage["complete"])

    def test_aggregate_byte_identical_to_old_logic_complete_book(self):
        # Prove the NEW sum equals the OLD sum for a complete finite book (the
        # post-#1259 real shape): identical, so portfolio_greeks is unchanged.
        legs_g = (dict(_FULL), dict(_FULL))
        pos = _pos(quantity=3.0, leg_greeks=legs_g)
        config = _default_all_caps_zero()

        _, new_greeks = check_greeks([pos], config)

        expected = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        for g in legs_g:  # replicate the pre-fix per-leg aggregation exactly
            for key in expected:
                expected[key] += _old_leg_greek_term(g, key, 3.0)
        self.assertEqual(new_greeks, expected)

    def test_aggregate_byte_identical_to_old_logic_greekless_book(self):
        # Pre-#1259 real shape: every leg greek-less → both aggregations are 0.0.
        pos = _pos(leg_greeks=(_ABSENT, _ABSENT))
        _, new_greeks = check_greeks([pos], _default_all_caps_zero())
        self.assertEqual(new_greeks,
                         {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0})

    def test_caps_zero_never_violates_across_shape_battery(self):
        # The binding dormancy invariant: with EVERY greek cap 0, NO input shape
        # produces a greeks violation and NONE raises.
        shapes = [
            (None, None), (_ABSENT, _ABSENT), (dict(_FULL), dict(_FULL)),
            ({"delta": 0.5}, None),
            ({"delta": None, "gamma": 0.01, "vega": 0.05, "theta": -0.02}, None),
            ({"delta": float("nan"), "gamma": 0.01, "vega": 0.05, "theta": -0.02}, dict(_FULL)),
        ]
        for shape in shapes:
            violations, _ = check_greeks([_pos(leg_greeks=shape)], _default_all_caps_zero())
            self.assertEqual(violations, [], shape)


def _default_all_caps_zero() -> EnvelopeConfig:
    cfg = EnvelopeConfig()  # max_portfolio_{delta,gamma,vega,theta} default 0.0
    assert cfg.max_portfolio_delta == 0.0
    assert cfg.max_portfolio_gamma == 0.0
    assert cfg.max_portfolio_vega == 0.0
    assert cfg.max_portfolio_theta == 0.0
    return cfg


# ---------------------------------------------------------------------------
# (c) Real greeks + a NONZERO cap → the greeks violation fires correctly
#     (proving the check works once eventually armed), via the production route.
# ---------------------------------------------------------------------------

class TestArmedCapFires(unittest.TestCase):
    def test_delta_cap_violation_through_check_all_envelopes(self):
        # Two complete legs, delta 0.5 each, quantity 2 → aggregate delta
        # 0.5*2*100 * 2 legs = 200. Arm the cap at 100 → violation.
        result = check_all_envelopes(
            positions=[_pos(quantity=2.0, leg_greeks=(dict(_FULL), dict(_FULL)))],
            equity=EQUITY,
            config=_isolating_config(max_portfolio_delta=100.0),
        )
        delta_v = [v for v in result.violations if v.envelope == "greeks_delta"]
        self.assertEqual(len(delta_v), 1)
        self.assertEqual(delta_v[0].actual, 200.0)
        self.assertEqual(delta_v[0].limit, 100.0)
        # The armed cap must read a COMPLETE aggregate, not a partial one.
        self.assertTrue(result.greeks_coverage["complete"])

    def test_armed_cap_does_not_fire_on_dark_leg_that_would_underflow(self):
        # A dark leg contributes nothing, so an armed cap sees only the covered
        # exposure — it can never fire on a fabricated 0 nor be fooled by a
        # phantom sum. Single covered leg delta = 0.5*2*100 = 100, cap 150 → no
        # fire; coverage flags the aggregate partial.
        result = check_all_envelopes(
            positions=[_pos(quantity=2.0, leg_greeks=(dict(_FULL), None))],
            equity=EQUITY,
            config=_isolating_config(max_portfolio_delta=150.0),
        )
        self.assertEqual(
            [v for v in result.violations if v.envelope == "greeks_delta"], [])
        self.assertFalse(result.greeks_coverage["complete"])


if __name__ == "__main__":
    unittest.main()
