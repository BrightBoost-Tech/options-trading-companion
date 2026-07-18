"""Greek-cap ALERT-ONLY counterfactual — route-driven observe-only tests.

Owner items 9 + 11 (Lane E). The counterfactual answers "what WOULD a greek cap
do at a documented reference threshold?" WITHOUT arming any cap. These tests
drive the REAL ``check_all_envelopes`` end-to-end (never a helper in isolation)
and assert on its OUTPUT — the ``EnvelopeCheckResult.greek_cap_counterfactual``
jsonb surface and the caps-0 live behavior beside it.

Charter pinned here:
  - REFERENCE caps are DERIVED from existing EnvelopeConfig fields, not invented.
  - would_block compares against ``portfolio_greeks`` (the cap's real basis) and
    is CORROBORATED by the canonical signed aggregate (complete + sign-agree).
  - dark / partial / sign-mismatched greeks → typed UNAVAILABLE (would_block
    None), NEVER a fabricated 0 (H9).
  - caps default 0 → live behavior byte-identical (passed / violations unchanged);
    the counterfactual arms nothing and emits no warn/critical.
  - the flip-log dedups (one INFO line only when a row's would_block CHANGES).
"""

import unittest

from packages.quantum.risk.risk_envelope import (
    EnvelopeConfig,
    check_all_envelopes,
    check_greeks,
    compute_greek_cap_counterfactual,
    greek_cap_reference_rows,
    reset_greek_cf_state,
)
from packages.quantum.risk import risk_envelope

# Reuse the golden persisted-position factories (identical convention to prod).
from packages.quantum.tests.test_position_model import (
    _occ,
    _permissive_config,
    _persisted_debit_call_vertical,
    _persisted_iron_condor,
    _persisted_short_put_vertical,
)


# --- local greeked factories (distinct per-leg greeks so the net is nonzero) --
def _greeked_debit_vertical():
    """Debit call vertical, qty 3, with DISTINCT per-leg greeks.

    check_greeks(portfolio) and the canonical aggregate both net to:
      delta 60, gamma 1.5, vega 45, theta -6  (long leg − short leg).
    """
    pos = _persisted_debit_call_vertical(qty=3)
    pos["strategy"] = "debit_call_vertical"
    pos["legs"][0]["greeks"] = {   # buy 100C
        "delta": 0.60, "gamma": 0.02, "vega": 0.20, "theta": -0.05}
    pos["legs"][1]["greeks"] = {   # sell 105C
        "delta": 0.40, "gamma": 0.015, "vega": 0.05, "theta": -0.03}
    return pos


def _greeked_short_put_vertical():
    """Credit put vertical, qty -2, with distinct per-leg greeks."""
    pos = _persisted_short_put_vertical()
    pos["strategy"] = "credit_put_vertical"
    pos["legs"][0]["greeks"] = {   # sell 100P
        "delta": -0.45, "gamma": 0.03, "vega": 0.18, "theta": -0.04}
    pos["legs"][1]["greeks"] = {   # buy 95P
        "delta": -0.20, "gamma": 0.02, "vega": 0.10, "theta": -0.02}
    return pos


def _greeked_iron_condor():
    """Iron condor, qty -1, distinct per-leg greeks on all four legs."""
    pos = _persisted_iron_condor()
    pos["strategy"] = "iron_condor"
    vals = [
        {"delta": -0.30, "gamma": 0.02, "vega": 0.12, "theta": -0.03},  # sell P
        {"delta": -0.15, "gamma": 0.01, "vega": 0.08, "theta": -0.02},  # buy P
        {"delta": 0.25, "gamma": 0.02, "vega": 0.11, "theta": -0.03},   # sell C
        {"delta": 0.10, "gamma": 0.01, "vega": 0.07, "theta": -0.02},   # buy C
    ]
    for leg, g in zip(pos["legs"], vals):
        leg["greeks"] = dict(g)
    return pos


EQUITY = 10000.0
EQUITY_HI = 100000.0


class TestReferenceCapDerivation(unittest.TestCase):
    """The reference caps INVERT existing EnvelopeConfig fields — not invented."""

    def test_rows_derived_from_config_fields(self):
        config = EnvelopeConfig()  # defaults: loss 0.03/0.05/0.10, stress 0.05/0.50
        rows = {r["name"]: r for r in greek_cap_reference_rows(EQUITY, config)}
        self.assertEqual(set(rows), {"tight", "medium", "loose"})

        tight = rows["tight"]
        self.assertEqual(tight["budget_fraction_source"], "max_per_symbol_loss_pct")
        self.assertAlmostEqual(tight["budget_fraction"], 0.03)
        self.assertAlmostEqual(tight["loss_budget_dollars"], 300.0)
        # delta = L/spy_move; gamma = L/spy_move^2; vega = L/(vix_move*100); theta = L
        self.assertAlmostEqual(tight["caps"]["delta"], 6000.0)    # 300 / 0.05
        self.assertAlmostEqual(tight["caps"]["gamma"], 120000.0)  # 300 / 0.0025
        self.assertAlmostEqual(tight["caps"]["vega"], 6.0)        # 300 / 50
        self.assertAlmostEqual(tight["caps"]["theta"], 300.0)     # 300

        self.assertEqual(rows["medium"]["budget_fraction_source"], "max_daily_loss_pct")
        self.assertAlmostEqual(rows["medium"]["caps"]["vega"], 10.0)   # 500 / 50
        self.assertEqual(rows["loose"]["budget_fraction_source"], "max_weekly_loss_pct")
        self.assertAlmostEqual(rows["loose"]["caps"]["vega"], 20.0)    # 1000 / 50

    def test_nonpositive_caps_are_none_not_zero(self):
        # A zero stress move / loss fraction yields NO usable reference (mirrors
        # check_greeks' `limit > 0` gate) — None, never a 0 that could "block".
        config = EnvelopeConfig(stress_spy_down_pct=0.0)
        rows = {r["name"]: r for r in greek_cap_reference_rows(EQUITY, config)}
        self.assertIsNone(rows["tight"]["caps"]["delta"])
        self.assertIsNone(rows["tight"]["caps"]["gamma"])
        self.assertIsNotNone(rows["tight"]["caps"]["vega"])  # vix move unaffected


class TestRouteWouldBlock(unittest.TestCase):
    """End-to-end through check_all_envelopes: the CF fields are correct."""

    def setUp(self):
        reset_greek_cf_state()

    def test_debit_vertical_blocks_on_vega_available_and_corroborated(self):
        pos = _greeked_debit_vertical()
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual

        self.assertTrue(cf["available"])
        self.assertEqual(cf["basis"], "portfolio_greeks")
        self.assertTrue(cf["coverage"]["greeks_coverage_complete"])
        self.assertTrue(cf["coverage"]["canonical_complete"])
        self.assertEqual(cf["book"]["n_positions"], 1)
        self.assertIn("debit_call_vertical", cf["book"]["strategies"])

        # per-greek exposures match the signed net (delta 60, vega 45, theta -6)
        self.assertAlmostEqual(cf["greeks"]["delta"]["exposure"], 60.0)
        self.assertAlmostEqual(cf["greeks"]["vega"]["exposure"], 45.0)
        self.assertAlmostEqual(cf["greeks"]["theta"]["exposure"], -6.0)
        self.assertAlmostEqual(cf["greeks"]["delta"]["canonical"], 60.0)

        rows = {r["name"]: r for r in cf["reference_rows"]}
        # vega 45 exceeds vega caps (6/10/20) on ALL three rows; delta never does.
        for name in ("tight", "medium", "loose"):
            self.assertTrue(rows[name]["would_block"], name)
            blocking = [b["greek"] for b in rows[name]["blocking"]]
            self.assertEqual(blocking, ["vega"], name)
            self.assertFalse(rows[name]["per_greek"]["delta"]["would_block"], name)
        # headroom sign: tight delta has room (6000 − 60), tight vega is over (6 − 45)
        self.assertAlmostEqual(rows["tight"]["per_greek"]["delta"]["headroom"], 5940.0)
        self.assertAlmostEqual(rows["tight"]["per_greek"]["vega"]["headroom"], -39.0)

    def test_same_book_higher_equity_does_not_block(self):
        pos = _greeked_debit_vertical()
        result = check_all_envelopes([pos], equity=EQUITY_HI, config=_permissive_config())
        cf = result.greek_cap_counterfactual
        self.assertTrue(cf["available"])
        for r in cf["reference_rows"]:
            self.assertFalse(r["would_block"], r["name"])
            self.assertEqual(r["blocking"], [])

    def test_credit_vertical_route_available(self):
        pos = _greeked_short_put_vertical()
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual
        self.assertTrue(cf["available"])
        self.assertTrue(cf["coverage"]["canonical_complete"])
        # short put vertical: delta net −0.45 −(−0.20) legs → check net −50 ($/pt)
        # sign agreement holds (both aggregates negative) → available, not sign_mismatch
        self.assertTrue(cf["greeks"]["delta"]["available"])
        self.assertIsNone(cf["greeks"]["delta"]["reason"])

    def test_condor_route_available_all_four_greeks(self):
        pos = _greeked_iron_condor()
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual
        self.assertTrue(cf["available"])
        self.assertTrue(cf["coverage"]["greeks_coverage_complete"])
        self.assertTrue(cf["coverage"]["canonical_complete"])
        for g in ("delta", "gamma", "vega", "theta"):
            self.assertTrue(cf["greeks"][g]["available"], g)

    def test_mixed_book_route(self):
        book = [_greeked_debit_vertical(), _greeked_iron_condor()]
        result = check_all_envelopes(book, equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual
        self.assertTrue(cf["available"])
        self.assertEqual(cf["book"]["n_positions"], 2)
        self.assertEqual(
            cf["book"]["strategies"], ["debit_call_vertical", "iron_condor"])
        self.assertTrue(cf["coverage"]["greeks_coverage_complete"])


class TestTypedUnavailableNeverZero(unittest.TestCase):
    """H9: dark / partial / sign-mismatched greeks → None, never a fabricated 0."""

    def setUp(self):
        reset_greek_cf_state()

    def test_dark_greeks_typed_unavailable(self):
        # Production default today: legs carry NO greeks (§8 double-dormancy).
        pos = _persisted_short_put_vertical()  # no greeks
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual

        self.assertTrue(cf["available"])  # the surface computed; the GREEKS are not
        self.assertFalse(cf["coverage"]["greeks_coverage_complete"])
        self.assertFalse(cf["coverage"]["canonical_complete"])
        for g in ("delta", "gamma", "vega", "theta"):
            self.assertFalse(cf["greeks"][g]["available"], g)
            self.assertIsNone(cf["greeks"][g]["exposure"], g)  # NOT 0.0
            self.assertEqual(
                cf["greeks"][g]["reason"], "greeks_coverage_incomplete", g)
        for r in cf["reference_rows"]:
            self.assertIsNone(r["would_block"], r["name"])  # typed unavailable
            self.assertIsNone(r["per_greek"]["vega"]["exposure"], r["name"])
            self.assertEqual(
                sorted(r["unavailable_greeks"]),
                ["delta", "gamma", "theta", "vega"], r["name"])

    def test_partial_greeks_typed_unavailable(self):
        # 3 of 4 legs greeked → whole-book coverage incomplete → typed unavailable.
        pos = _greeked_iron_condor()
        pos["legs"][3]["greeks"] = None  # one leg dark
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        cf = result.greek_cap_counterfactual
        self.assertFalse(cf["coverage"]["greeks_coverage_complete"])
        self.assertEqual(cf["coverage"]["legs_total"], 4)
        self.assertEqual(cf["coverage"]["legs_with_greeks"], 3)
        for r in cf["reference_rows"]:
            self.assertIsNone(r["would_block"], r["name"])

    def test_sign_mismatch_typed_unavailable(self):
        # Direct call: the cap basis (portfolio) and the honest canonical aggregate
        # disagree on delta's direction → typed UNAVAILABLE, never a would_block.
        cf = compute_greek_cap_counterfactual(
            portfolio_greeks={"delta": 100.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0},
            greeks_coverage={"complete": True, "legs_total": 2, "legs_with_greeks": 2},
            canonical_greeks={"delta": -50.0, "gamma": 0.0, "vega": 0.0,
                              "theta": 0.0, "complete": True},
            positions=[],
            equity=EQUITY,
            config=_permissive_config(),
        )
        self.assertFalse(cf["greeks"]["delta"]["available"])
        self.assertEqual(cf["greeks"]["delta"]["reason"], "sign_mismatch")
        for r in cf["reference_rows"]:
            self.assertIn("delta", r["unavailable_greeks"])
            self.assertIsNone(r["per_greek"]["delta"]["would_block"])
            # the other greeks are a genuine 0 exposure (available), so the row
            # resolves would_block False (not None) — one available greek suffices.
            self.assertFalse(r["would_block"], r["name"])

    def test_nonpositive_equity_typed_unavailable(self):
        cf = compute_greek_cap_counterfactual(
            portfolio_greeks={"delta": 60.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0},
            greeks_coverage={"complete": True, "legs_total": 2, "legs_with_greeks": 2},
            canonical_greeks={"delta": 60.0, "gamma": 0.0, "vega": 0.0,
                              "theta": 0.0, "complete": True},
            positions=[],
            equity=0.0,
            config=_permissive_config(),
        )
        self.assertFalse(cf["available"])
        self.assertEqual(cf["reason"], "nonpositive_equity")
        self.assertEqual(cf["reference_rows"], [])


class TestCapsZeroLiveBehaviorByteIdentical(unittest.TestCase):
    """The counterfactual arms NOTHING: caps default 0, no greek violation, and
    the observe-only field never perturbs passed / violations / sizing."""

    def setUp(self):
        reset_greek_cf_state()

    def test_blocking_counterfactual_emits_no_violation(self):
        pos = _greeked_debit_vertical()  # CF would_block True on vega (all rows)
        config = _permissive_config()
        result = check_all_envelopes([pos], equity=EQUITY, config=config)

        # The CF says "would block" — but the LIVE path is untouched:
        self.assertTrue(result.greek_cap_counterfactual["reference_rows"][0]["would_block"])
        self.assertTrue(result.passed)
        self.assertEqual(result.violations, [])           # nothing emitted at all
        self.assertEqual(
            [v for v in result.violations if v.envelope.startswith("greeks_")], [])
        self.assertAlmostEqual(result.sizing_multiplier, 1.0)

    def test_portfolio_greeks_and_caps_unchanged(self):
        pos = _greeked_debit_vertical()
        config = _permissive_config()
        result = check_all_envelopes([pos], equity=EQUITY, config=config)
        # portfolio_greeks is exactly check_greeks' output — the CF read it, never
        # wrote it; and check_greeks still emits zero violations at caps 0.
        direct_violations, direct_greeks = check_greeks([pos], config)
        self.assertEqual(direct_violations, [])
        self.assertEqual(result.portfolio_greeks, direct_greeks)

    def test_result_json_serializable_with_new_field(self):
        import json
        pos = _greeked_debit_vertical()
        result = check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        as_dict = result.to_dict()
        self.assertIn("greek_cap_counterfactual", as_dict)
        json.dumps(as_dict)  # must not raise


class TestFlipLoggingDedup(unittest.TestCase):
    """One INFO flip-line only when a row's would_block CHANGES for a scope."""

    def setUp(self):
        reset_greek_cf_state()

    def _cf_lines(self, cm):
        return [r for r in cm.output if "[GREEK_CAP_CF]" in r]

    def test_flip_logs_only_on_state_change(self):
        pos = _greeked_debit_vertical()
        cfg = _permissive_config()

        # 1) first observation at HIGH equity → all rows False → baseline flip logs
        with self.assertLogs(risk_envelope.logger, level="INFO") as cm1:
            check_all_envelopes([pos], equity=EQUITY_HI, config=cfg,
                                observe_scope="s")
        self.assertEqual(len(self._cf_lines(cm1)), 1)

        # 2) identical repeat → NO would_block change → no CF flip line
        with self.assertLogs(risk_envelope.logger, level="INFO") as cm2:
            check_all_envelopes([pos], equity=EQUITY_HI, config=cfg,
                                observe_scope="s")
        self.assertEqual(self._cf_lines(cm2), [])

        # 3) LOW equity → vega now blocks → state flips → one CF line again
        with self.assertLogs(risk_envelope.logger, level="INFO") as cm3:
            check_all_envelopes([pos], equity=EQUITY, config=cfg,
                                observe_scope="s")
        self.assertEqual(len(self._cf_lines(cm3)), 1)

    def test_no_scope_never_logs_flip(self):
        pos = _greeked_debit_vertical()
        with self.assertLogs(risk_envelope.logger, level="INFO") as cm:
            check_all_envelopes([pos], equity=EQUITY, config=_permissive_config())
        # observe_scope defaults None → the field is populated but nothing flip-logs
        self.assertEqual([r for r in cm.output if "[GREEK_CAP_CF]" in r], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
