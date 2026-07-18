"""Typed multi-basis cost model — phase-2 foundation (Lane 3C).

Scenario coverage for the OBSERVE-ONLY typed model + reconciliation report:
1-contract vertical, multi-contract vertical, 1-contract condor, qty>1 condor
(the E2 legacy-basis divergence surfaces as a TYPED difference), malformed leg
count, missing bid/ask -> UNAVAILABLE propagation, fallback-source flagging,
fee/slippage unit conversions, and entry/exit symmetry.

Nothing here changes a threshold, rank, gate, or decision — the production
formulas are frozen baselines compared side-by-side.
"""

import json
import sys
import types
import unittest

# Stub alpaca-py so transitive imports resolve in the test venv (same
# convention as test_entry_roundtrip_cost_gate.py).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.analytics.cost_basis import (  # noqa: E402
    CostBasisKind,
    CostComponent,
    CostSide,
    CostSource,
    CostUnit,
    OPTION_MULTIPLIER,
    UNAVAILABLE,
    executable_side_cost,
    extract_ranker_costs,
    extract_realized_close_costs,
    extract_scanner_drag_cost,
    extract_stage_executable_cross,
    extract_tcm_estimate,
    reconcile_cost_bases,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def _vertical_legs(qty=1):
    return [
        {"occ_symbol": "O:TST260101C00100000", "action": "buy",
         "quantity": qty, "strike": 100.0},
        {"occ_symbol": "O:TST260101C00105000", "action": "sell",
         "quantity": qty, "strike": 105.0},
    ]


VERTICAL_QUOTES = {
    "O:TST260101C00100000": {"bid": 2.00, "ask": 2.10},  # cross 0.10
    "O:TST260101C00105000": {"bid": 1.00, "ask": 1.10},  # cross 0.10
}


def _condor_legs(qty=1):
    return [
        {"occ_symbol": "O:TST260101P00090000", "action": "buy",
         "quantity": qty, "strike": 90.0},
        {"occ_symbol": "O:TST260101P00095000", "action": "sell",
         "quantity": qty, "strike": 95.0},
        {"occ_symbol": "O:TST260101C00105000", "action": "sell",
         "quantity": qty, "strike": 105.0},
        {"occ_symbol": "O:TST260101C00110000", "action": "buy",
         "quantity": qty, "strike": 110.0},
    ]


CONDOR_QUOTES = {
    "O:TST260101P00090000": {"bid": 0.50, "ask": 0.60},
    "O:TST260101P00095000": {"bid": 0.90, "ask": 1.00},
    "O:TST260101C00105000": {"bid": 0.80, "ask": 0.90},
    "O:TST260101C00110000": {"bid": 0.40, "ask": 0.50},
}


def _suggestion(*, legs, contracts=1, ev=50.0):
    return {
        "ticker": "TST",
        "ev": ev,
        "order_json": {
            "contracts": contracts,
            "legs": [
                {"symbol": f"L{i}", "quantity": contracts}
                for i in range(legs)
            ],
        },
        "sizing_metadata": {
            "contracts": contracts,
            "max_loss_total": 500.0 * contracts,
        },
    }


class _Leg:
    def __init__(self, symbol, action="buy", quantity=1, strike=None):
        self.symbol = symbol
        self.action = action
        self.quantity = quantity
        self.strike = strike


class _Ticket:
    """Minimal ticket shape for the execution TCM (limit_price / quantity /
    order_type / legs[0].action)."""

    def __init__(self, *, limit_price, quantity, order_type="limit",
                 action="buy"):
        self.limit_price = limit_price
        self.quantity = quantity
        self.order_type = order_type
        self.legs = [_Leg("O:TST260101C00100000", action=action)]


# ── Typed-model invariants ──────────────────────────────────────────────────

class TestCostComponentInvariants(unittest.TestCase):
    def test_available_requires_amount(self):
        with self.assertRaises(ValueError):
            CostComponent(
                name="x", source=CostSource.TCM, side=CostSide.ENTRY,
                basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
                amount_usd=None,
            )

    def test_unavailable_rejects_amount(self):
        with self.assertRaises(ValueError):
            CostComponent(
                name="x", source=CostSource.TCM, side=CostSide.ENTRY,
                basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
                amount_usd=1.0, available=False, unavailable_reason="r",
            )

    def test_unavailable_requires_reason(self):
        with self.assertRaises(ValueError):
            CostComponent(
                name="x", source=CostSource.TCM, side=CostSide.ENTRY,
                basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
                amount_usd=None, available=False,
            )

    def test_missing_input_is_typed_unavailable_never_zero(self):
        c = CostComponent.make_unavailable(
            "x", CostSource.TCM, CostSide.ENTRY, CostBasisKind.ESTIMATED,
            CostUnit.TOTAL, "input_missing",
        )
        self.assertFalse(c.available)
        self.assertIsNone(c.amount_usd)
        self.assertNotEqual(c.amount_usd, 0.0)
        self.assertEqual(c.unavailable_reason, "input_missing")


class TestUnitConversions(unittest.TestCase):
    """Fee/slippage unit conversions: per_structure_contract <-> total via
    quantity; per_leg is a typed refusal; missing quantity is a typed
    UNAVAILABLE, never a fabricated scale."""

    def _comp(self, unit, amount, qty):
        return CostComponent(
            name="fees", source=CostSource.RANKER_MODEL,
            side=CostSide.ROUND_TRIP, basis=CostBasisKind.ESTIMATED,
            unit=unit, amount_usd=amount, quantity=qty,
        )

    def test_per_structure_contract_to_total(self):
        c = self._comp(CostUnit.PER_STRUCTURE_CONTRACT, 2.60, 3)
        conv = c.in_unit(CostUnit.TOTAL)
        self.assertTrue(conv.available)
        self.assertAlmostEqual(conv.amount_usd, 7.80)
        self.assertEqual(conv.unit, CostUnit.TOTAL)

    def test_total_to_per_structure_contract(self):
        c = self._comp(CostUnit.TOTAL, 15.60, 3)
        conv = c.in_unit(CostUnit.PER_STRUCTURE_CONTRACT)
        self.assertTrue(conv.available)
        self.assertAlmostEqual(conv.amount_usd, 5.20)

    def test_same_unit_is_identity(self):
        c = self._comp(CostUnit.TOTAL, 15.60, 3)
        self.assertIs(c.in_unit(CostUnit.TOTAL), c)

    def test_per_leg_conversion_refused(self):
        c = self._comp(CostUnit.PER_LEG, 10.0, 3)
        conv = c.in_unit(CostUnit.TOTAL)
        self.assertFalse(conv.available)
        self.assertEqual(conv.unavailable_reason, "per_leg_not_convertible")

    def test_missing_quantity_is_typed_unavailable(self):
        c = self._comp(CostUnit.TOTAL, 15.60, None)
        conv = c.in_unit(CostUnit.PER_STRUCTURE_CONTRACT)
        self.assertFalse(conv.available)
        self.assertEqual(
            conv.unavailable_reason, "quantity_missing_for_unit_conversion"
        )

    def test_unavailable_propagates_through_conversion(self):
        c = CostComponent.make_unavailable(
            "x", CostSource.TCM, CostSide.ENTRY, CostBasisKind.ESTIMATED,
            CostUnit.TOTAL, "leg_quote_incomplete", quantity=3,
        )
        conv = c.in_unit(CostUnit.PER_STRUCTURE_CONTRACT)
        self.assertFalse(conv.available)
        self.assertEqual(conv.unavailable_reason, "leg_quote_incomplete")


# ── Entry/exit symmetry ─────────────────────────────────────────────────────

class TestEntryExitSymmetry(unittest.TestCase):
    def test_stage_cross_symmetric_halves(self):
        bd = extract_stage_executable_cross(
            legs=_vertical_legs(1), leg_quotes=VERTICAL_QUOTES, quantity=1,
        )
        entry = executable_side_cost(bd, CostSide.ENTRY)
        exit_ = executable_side_cost(bd, CostSide.EXIT)
        total = bd.component("round_trip_total")
        self.assertTrue(entry.available and exit_.available)
        self.assertEqual(entry.amount_usd, exit_.amount_usd)
        self.assertAlmostEqual(
            entry.amount_usd + exit_.amount_usd, total.amount_usd
        )
        self.assertEqual(entry.side, CostSide.ENTRY)
        self.assertEqual(exit_.side, CostSide.EXIT)

    def test_symmetry_unavailable_propagates(self):
        quotes = dict(VERTICAL_QUOTES)
        quotes["O:TST260101C00105000"] = {"bid": 1.00, "ask": None}
        bd = extract_stage_executable_cross(
            legs=_vertical_legs(1), leg_quotes=quotes, quantity=1,
        )
        entry = executable_side_cost(bd, CostSide.ENTRY)
        self.assertFalse(entry.available)
        self.assertEqual(entry.unavailable_reason, "leg_quote_incomplete")


# ── Scenario reconciliations ────────────────────────────────────────────────

def _recon(*, legs, quotes, qty, ev, leg_count, calibrated_ev=None,
           tcm_quote="present"):
    scanner = extract_scanner_drag_cost(
        drag_map={}, symbol="TST", combo_width_share=0.10,
        num_legs=leg_count, quantity=qty,
    )
    ranker = extract_ranker_costs(
        _suggestion(legs=leg_count, contracts=qty, ev=ev), quantity=qty,
    )
    stage = extract_stage_executable_cross(
        legs=legs, leg_quotes=quotes, quantity=qty,
    )
    quote = (
        {"bid_price": 1.00, "ask_price": 1.20} if tcm_quote == "present"
        else None
    )
    tcm = extract_tcm_estimate(
        ticket=_Ticket(limit_price=1.10, quantity=qty), quote=quote,
    )
    return reconcile_cost_bases(
        quantity=qty, gross_ev=ev, calibrated_ev=calibrated_ev,
        scanner=scanner, ranker=ranker, stage=stage, tcm=tcm,
    )


class TestOneContractVertical(unittest.TestCase):
    def test_all_bases_normalized_and_qty_delta_zero(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2,
        )
        for key in ("scanner_estimate", "ranker_model",
                    "stage_executable_cross", "tcm"):
            self.assertIn(key, recon.normalized)
            self.assertNotEqual(
                recon.normalized[key]["total_usd"], UNAVAILABLE
            )
        # qty=1: TOTAL == PER_STRUCTURE_CONTRACT -> zero scaling delta, no
        # legacy-basis flag.
        d = recon.delta("quantity_scaling_stage_total_vs_per_contract")
        self.assertTrue(d.available)
        self.assertAlmostEqual(d.amount_usd, 0.0)
        self.assertNotIn("legacy_gate_basis_divergent_qty_gt_1", recon.flags)
        # stage cross for the vertical: (0.10 + 0.10) x 100 = $20/contract.
        self.assertAlmostEqual(
            recon.normalized["stage_executable_cross"]["total_usd"], 20.0
        )
        # Observe-only artifact is a plain serializable dict.
        json.dumps(recon.as_dict())

    def test_fee_and_slippage_deltas_available(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2,
        )
        fee = recon.delta("fee_model_ranker_round_trip_vs_tcm_one_way")
        self.assertTrue(fee.available)
        # ranker 0.65*1*2legs*2 = 2.60 vs tcm one-way 0.65*1 = 0.65
        self.assertAlmostEqual(fee.amount_usd, 2.60 - 0.65)
        slip = recon.delta("slippage_executable_cross_vs_ranker_proxy")
        self.assertTrue(slip.available)
        # cross $20 vs 5%-of-EV floor $2.50 -> proxy understates by $17.50
        self.assertAlmostEqual(slip.amount_usd, 20.0 - 2.5)


class TestMultiContractVertical(unittest.TestCase):
    def test_qty_scaling_delta_positive(self):
        recon = _recon(
            legs=_vertical_legs(3), quotes=VERTICAL_QUOTES, qty=3,
            ev=50.0, leg_count=2,
        )
        d = recon.delta("quantity_scaling_stage_total_vs_per_contract")
        self.assertTrue(d.available)
        # total 3 x $20 = $60; per-contract $20 -> delta $40
        self.assertAlmostEqual(d.amount_usd, 40.0)
        self.assertIn("legacy_gate_basis_divergent_qty_gt_1", recon.flags)


class TestOneContractCondor(unittest.TestCase):
    def test_condor_bases(self):
        recon = _recon(
            legs=_condor_legs(1), quotes=CONDOR_QUOTES, qty=1,
            ev=60.0, leg_count=4,
        )
        # 4 legs x 0.10 cross x 100 = $40 round trip
        self.assertAlmostEqual(
            recon.normalized["stage_executable_cross"]["total_usd"], 40.0
        )
        # ranker fees: 0.65*1*4*2 = 5.20 (+ slippage floor 3.0) = 8.20
        self.assertAlmostEqual(
            recon.normalized["ranker_model"]["total_usd"], 8.20
        )
        d = recon.delta("quantity_scaling_stage_total_vs_per_contract")
        self.assertAlmostEqual(d.amount_usd, 0.0)


class TestQtyGt1CondorE2Divergence(unittest.TestCase):
    """The E2 legacy-basis divergence MUST surface as a typed difference:
    the legacy live gate charges per-structure gross_ev against the
    qty-scaled TOTAL cross; the fixed basis charges the per-contract cross."""

    def test_typed_legacy_vs_fixed_nets(self):
        qty, ev = 4, 55.0
        recon = _recon(
            legs=_condor_legs(qty), quotes=CONDOR_QUOTES, qty=qty,
            ev=ev, leg_count=4,
        )
        d = recon.delta("quantity_scaling_stage_total_vs_per_contract")
        self.assertTrue(d.available)
        # total 4 x $40 = $160; per-contract $40 -> delta $120
        self.assertAlmostEqual(d.amount_usd, 120.0)
        self.assertIn("legacy_gate_basis_divergent_qty_gt_1", recon.flags)
        # The typed nets reproduce both gate bases side-by-side:
        self.assertAlmostEqual(d.detail["legacy_net"], ev - 160.0)  # reject
        self.assertAlmostEqual(d.detail["fixed_net"], ev - 40.0)    # allow
        # ...and they sit on opposite sides of the $15 floor — the exact
        # decision divergence the flag wrinkle gates (typed, observe-only).
        self.assertLess(d.detail["legacy_net"], 15.0)
        self.assertGreaterEqual(d.detail["fixed_net"], 15.0)


class TestMalformedLegCount(unittest.TestCase):
    def test_empty_legs_is_typed_unavailable(self):
        s = _suggestion(legs=2, contracts=1)
        s["order_json"]["legs"] = []
        bd = extract_ranker_costs(s)
        fees = bd.component("round_trip_fees")
        self.assertFalse(fees.available)
        self.assertIn(
            "ranking_cost_leg_count_unavailable", fees.unavailable_reason
        )
        self.assertFalse(bd.available)  # primary fees_plus_slippage too

    def test_malformed_legs_propagate_to_recon_delta(self):
        s = _suggestion(legs=2, contracts=1)
        s["order_json"]["legs"] = [1, 2]  # non-dict legs
        ranker = extract_ranker_costs(s)
        recon = reconcile_cost_bases(quantity=1, gross_ev=50.0, ranker=ranker)
        fee = recon.delta("fee_model_ranker_round_trip_vs_tcm_one_way")
        self.assertFalse(fee.available)
        self.assertIsNone(fee.amount_usd)  # typed unavailable, never zero

    def test_invalid_contracts_is_typed_unavailable(self):
        # NOTE: production coerces contracts=0 to 1 (`or 1`,
        # canonical_ranker.py:42) — only a NEGATIVE count raises.
        s = _suggestion(legs=2, contracts=1)
        s["sizing_metadata"]["contracts"] = -1
        bd = extract_ranker_costs(s, quantity=1)
        fees = bd.component("round_trip_fees")
        self.assertFalse(fees.available)
        self.assertIn(
            "ranking_cost_contracts_invalid", fees.unavailable_reason
        )


class TestMissingBidAskPropagation(unittest.TestCase):
    def test_one_dark_leg_makes_totals_unavailable(self):
        quotes = dict(CONDOR_QUOTES)
        quotes["O:TST260101C00110000"] = {"bid": None, "ask": None}
        bd = extract_stage_executable_cross(
            legs=_condor_legs(1), leg_quotes=quotes, quantity=1,
        )
        for name in ("round_trip_total", "round_trip_per_contract"):
            c = bd.component(name)
            self.assertFalse(c.available, name)
            self.assertEqual(c.unavailable_reason, "leg_quote_incomplete")
            self.assertIsNone(c.amount_usd)
        dark = bd.component("leg_cross:O:TST260101C00110000")
        self.assertFalse(dark.available)
        self.assertIn("leg_quote_missing", dark.unavailable_reason)
        # Priced legs keep their typed per-leg values (informational).
        lit = bd.component("leg_cross:O:TST260101P00090000")
        self.assertTrue(lit.available)
        self.assertAlmostEqual(lit.amount_usd, 10.0)

    def test_unavailable_propagates_into_recon(self):
        quotes = dict(VERTICAL_QUOTES)
        quotes["O:TST260101C00100000"] = {"bid": 2.00}  # ask missing
        stage = extract_stage_executable_cross(
            legs=_vertical_legs(1), leg_quotes=quotes, quantity=1,
        )
        recon = reconcile_cost_bases(quantity=1, gross_ev=50.0, stage=stage)
        self.assertEqual(
            recon.normalized["stage_executable_cross"]["total_usd"],
            UNAVAILABLE,
        )
        for name in (
            "slippage_executable_cross_vs_ranker_proxy",
            "quantity_scaling_stage_total_vs_per_contract",
            "scanner_modeled_vs_stage_executable_per_contract",
        ):
            d = recon.delta(name)
            self.assertFalse(d.available, name)
            self.assertIsNone(d.amount_usd)

    def test_scanner_missing_inputs_unavailable(self):
        bd = extract_scanner_drag_cost(
            drag_map={}, symbol="TST", combo_width_share=None, num_legs=2,
        )
        self.assertFalse(bd.available)
        self.assertIn(
            "combo_width_share",
            bd.primary_component.unavailable_reason,
        )


class TestFallbackSourceFlagging(unittest.TestCase):
    def test_tcm_fabricated_quote_flagged(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2, tcm_quote="missing",
        )
        self.assertIn("tcm_quote_fallback_fabricated", recon.flags)

    def test_tcm_real_quote_not_flagged(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2, tcm_quote="present",
        )
        self.assertNotIn("tcm_quote_fallback_fabricated", recon.flags)

    def test_ranker_ev_floor_slippage_flagged(self):
        # No tcm/sizing slippage on the suggestion -> 5%-of-EV floor branch.
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2,
        )
        self.assertIn("ranker_slippage_five_pct_ev_floor_proxy", recon.flags)

    def test_ranker_tcm_slippage_not_floor_flagged(self):
        s = _suggestion(legs=2, contracts=1, ev=50.0)
        s["tcm"] = {"expected_slippage": 12.5}
        ranker = extract_ranker_costs(s, quantity=1)
        recon = reconcile_cost_bases(quantity=1, gross_ev=50.0, ranker=ranker)
        self.assertNotIn(
            "ranker_slippage_five_pct_ev_floor_proxy", recon.flags
        )
        slip = ranker.component("expected_slippage")
        self.assertEqual(
            slip.provenance.source_detail, "branch=tcm_expected_slippage"
        )


class TestEvBasisFlag(unittest.TestCase):
    def test_calibrated_vs_raw_diverge(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2, calibrated_ev=25.0,
        )
        self.assertEqual(recon.ev_basis.flag, "calibrated_and_raw_diverge")
        self.assertAlmostEqual(recon.ev_basis.delta, -25.0)
        self.assertIn(
            "ranker_ev_calibrated_vs_stage_gate_gross_ev", recon.flags
        )

    def test_raw_only(self):
        recon = _recon(
            legs=_vertical_legs(1), quotes=VERTICAL_QUOTES, qty=1,
            ev=50.0, leg_count=2,
        )
        self.assertEqual(recon.ev_basis.flag, "raw_only")

    def test_unknown_when_no_ev(self):
        recon = reconcile_cost_bases(quantity=1)
        self.assertEqual(recon.ev_basis.flag, "unknown")


class TestRealizedBasis(unittest.TestCase):
    SOFI_ORDER_JSON = {
        "close_fill_gap_cross": 1.31,
        "close_fill_gap_mid": 1.525,
    }

    def test_realized_components_and_gap(self):
        rc = extract_realized_close_costs(
            order_json=self.SOFI_ORDER_JSON, broker_fill=-1.36, quantity=1,
        )
        self.assertAlmostEqual(
            rc.breakdown.component("realized_fill_mark").amount_usd, 136.0
        )
        self.assertAlmostEqual(
            rc.breakdown.component("stage_cross_mark").amount_usd, 131.0
        )
        self.assertAlmostEqual(
            rc.breakdown.component("trigger_mid_mark").amount_usd, 152.5
        )
        self.assertAlmostEqual(rc.gap_fraction, (1.36 - 1.31) / (1.525 - 1.31))
        slip = rc.breakdown.component("realized_slippage_vs_mid")
        self.assertAlmostEqual(
            slip.amount_usd, (1.525 - 1.36) * OPTION_MULTIPLIER
        )

    def test_missing_stamp_typed_unavailable_and_flagged(self):
        rc = extract_realized_close_costs(
            order_json={}, broker_fill=-1.36, quantity=1,
        )
        cross = rc.breakdown.component("stage_cross_mark")
        self.assertFalse(cross.available)
        self.assertIn("order_json_stamp_missing", cross.unavailable_reason)
        self.assertIsNone(rc.gap_fraction)
        recon = reconcile_cost_bases(quantity=1, realized=rc)
        self.assertIn("realized_stamp_missing", recon.flags)
        self.assertIsNone(
            recon.delta("realized_fill_vs_stage_cross_mark").amount_usd
        )

    def test_missing_broker_fill_typed_unavailable(self):
        rc = extract_realized_close_costs(
            order_json=self.SOFI_ORDER_JSON, broker_fill=None, quantity=1,
        )
        fill = rc.breakdown.component("realized_fill_mark")
        self.assertFalse(fill.available)
        self.assertEqual(fill.unavailable_reason, "broker_fill_missing")
        self.assertIsNone(rc.gap_fraction)

    def test_gap_fraction_rides_the_recon_artifact(self):
        rc = extract_realized_close_costs(
            order_json=self.SOFI_ORDER_JSON, broker_fill=-1.36, quantity=1,
        )
        recon = reconcile_cost_bases(quantity=1, realized=rc)
        self.assertAlmostEqual(
            recon.normalized["realized"]["gap_fraction"],
            (1.36 - 1.31) / (1.525 - 1.31),
        )


if __name__ == "__main__":
    unittest.main()
