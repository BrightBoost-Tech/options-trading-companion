"""Parity locks: each cost_basis extractor == its production formula.

Every test drives the REAL production function on the same inputs and asserts
BYTE-EQUALITY against the extractor's typed output, plus hand-computed
constants pinning the frozen formula itself — so silent drift in a production
cost formula breaks this build in BOTH directions (extractor vs production,
production vs the traced constant).

The E2 legacy-basis parity drives the REAL stage gate
(paper_endpoints._apply_entry_roundtrip_gate) end-to-end and asserts the
typed reconciliation reproduces the gate's own legacy/fixed nets exactly.
"""

import copy
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so transitive imports resolve in the test venv (same
# convention as test_entry_roundtrip_cost_gate.py).
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()


# ── De-poison guard ─────────────────────────────────────────────────────────
# Other test files (the test_weekly_report_win_rate class) replace whole
# production modules in sys.modules with MagicMocks at THEIR import and can
# leak them; pytest imports every test module during collection, so the leak
# lands here regardless of which file is collected first. Two exposures, two
# invocations of the same guard:
#   1. AT THIS MODULE'S IMPORT (below, before the production imports): a
#      poisoner collected BEFORE this file would otherwise bind mocks into
#      this module's direct production references.
#   2. IN EVERY TEST's setUp (_RealModulesTestCase): the extractors under
#      test import production modules LAZILY by design (pinned by
#      test_cost_basis_import_lock's inertness lock), so they resolve
#      through sys.modules at CALL time — a poisoner collected AFTER this
#      file (the 2026-07-17 CI failure: float(MagicMock()) == 1.0 read as a
#      parity value, 5 tests red at full-suite order, green single-file)
#      poisons the run phase even though this module imported real objects.
# Never rely on module-load-clean state.

def _depoison_sys_modules() -> None:
    for _name, _mod in list(sys.modules.items()):
        if not _name.startswith("packages.quantum"):
            continue
        if not isinstance(_mod, MagicMock):
            continue
        _parent, _, _child = _name.rpartition(".")
        _real = (
            getattr(sys.modules.get(_parent), _child, None) if _parent else None
        )
        if isinstance(_real, types.ModuleType) and not isinstance(
            _real, MagicMock
        ):
            # The parent package still holds the real submodule object —
            # reinstall it without re-executing the module.
            sys.modules[_name] = _real
        else:
            # No surviving real object: force a clean re-import at the next
            # resolution.
            del sys.modules[_name]


_depoison_sys_modules()

from packages.quantum.analytics.canonical_ranker import (  # noqa: E402
    _estimate_slippage,
    _ranking_round_trip_fees,
)
from packages.quantum.analytics.cost_basis import (  # noqa: E402
    CostSide,
    CostUnit,
    extract_legacy_tcm_estimate,
    extract_ranker_costs,
    extract_realized_close_costs,
    extract_scanner_drag_cost,
    extract_scanner_unified_final_cost,
    extract_stage_executable_cross,
    extract_tcm_estimate,
    reconcile_cost_bases,
)
from packages.quantum.analytics.exit_mark_corroboration import (  # noqa: E402
    executable_roundtrip_cost,
)
from packages.quantum.analytics.scoring import (  # noqa: E402
    calculate_unified_score,
)
from packages.quantum.execution.transaction_cost_model import (  # noqa: E402
    TransactionCostModel as ExecutionTCM,
)
from packages.quantum.models import OptionLeg, TradeTicket  # noqa: E402
from packages.quantum.options_scanner import (  # noqa: E402
    _determine_execution_cost,
)
from packages.quantum.services.close_fill_gap import (  # noqa: E402
    broker_fill_to_mark_basis,
    compute_gap_fraction,
    read_stamp,
)
from packages.quantum.services.transaction_cost_model import (  # noqa: E402
    TransactionCostModel as LegacyTCM,
)


class _RealModulesTestCase(unittest.TestCase):
    """Base for every parity case: de-poison sys.modules per-test."""

    def setUp(self):
        super().setUp()
        _depoison_sys_modules()


# ── Basis 1a: scanner _determine_execution_cost ─────────────────────────────

class TestScannerDragParity(_RealModulesTestCase):
    def test_proxy_formula_pinned_and_byte_equal(self):
        # Frozen formula: (combo_width_share*0.25 + num_legs*0.0065) * 100
        # = (0.10*0.25 + 2*0.0065) * 100 = (0.025 + 0.013) * 100 = 3.80
        real = _determine_execution_cost(
            drag_map={}, symbol="TST", combo_width_share=0.10, num_legs=2,
            is_limit=True,
        )
        bd = extract_scanner_drag_cost(
            drag_map={}, symbol="TST", combo_width_share=0.10, num_legs=2,
            is_limit=True,
        )
        self.assertEqual(
            bd.primary_component.amount_usd, real["expected_execution_cost"]
        )
        self.assertAlmostEqual(bd.primary_component.amount_usd, 3.80)
        self.assertIn(
            "source_used=proxy", bd.primary_component.provenance.source_detail
        )

    def test_market_take_frac_pinned(self):
        # Market orders: take_frac 0.50 -> (0.05 + 0.013) * 100 = 6.30
        real = _determine_execution_cost(
            drag_map={}, symbol="TST", combo_width_share=0.10, num_legs=2,
            is_limit=False,
        )
        bd = extract_scanner_drag_cost(
            drag_map={}, symbol="TST", combo_width_share=0.10, num_legs=2,
            is_limit=False,
        )
        self.assertEqual(
            bd.primary_component.amount_usd, real["expected_execution_cost"]
        )
        self.assertAlmostEqual(bd.primary_component.amount_usd, 6.30)

    def test_history_wins_when_larger(self):
        drag = {"TST": {"avg_drag": 10.0, "n": 5}}
        real = _determine_execution_cost(
            drag_map=drag, symbol="TST", combo_width_share=0.10, num_legs=2,
            is_limit=True,
        )
        bd = extract_scanner_drag_cost(
            drag_map=drag, symbol="TST", combo_width_share=0.10, num_legs=2,
        )
        self.assertEqual(bd.primary_component.amount_usd, 10.0)
        self.assertEqual(
            bd.primary_component.amount_usd, real["expected_execution_cost"]
        )
        self.assertIn(
            "source_used=history",
            bd.primary_component.provenance.source_detail,
        )

    def test_proxy_wins_over_smaller_history(self):
        drag = {"TST": {"avg_drag": 1.0, "n": 5}}
        bd = extract_scanner_drag_cost(
            drag_map=drag, symbol="TST", combo_width_share=0.10, num_legs=2,
        )
        self.assertAlmostEqual(bd.primary_component.amount_usd, 3.80)
        self.assertIn(
            "source_used=proxy", bd.primary_component.provenance.source_detail
        )


# ── Basis 1b: the scanner's SECOND max() layer (scoring.py:114) ─────────────

class TestScannerUnifiedFinalParity(_RealModulesTestCase):
    TRADE = {
        "ev": 50.0, "suggested_entry": 1.00, "bid_ask_spread": 0.0,
        "strategy": "bull_call_spread", "max_loss": 200.0,
        "gamma": 0.0, "vega": 0.0, "iv_rank": 50, "type": "debit",
    }

    def test_inner_half_width_proxy_pinned_and_byte_equal(self):
        # Inner proxy (scoring.py:100): (entry*spread_pct*0.5 + legs*0.0065)
        # * 100 = (1.00*0.10*0.5 + 2*0.0065)*100 = 6.30 — note the 0.5 take
        # fraction vs _determine_execution_cost's 0.25 for the SAME candidate.
        real = calculate_unified_score(
            trade=dict(self.TRADE), regime_snapshot={"state": "normal"},
            market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=3.80, num_legs=2, entry_cost=1.00,
        )
        bd = extract_scanner_unified_final_cost(
            trade=self.TRADE, market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=3.80, num_legs=2, entry_cost=1.00,
        )
        self.assertEqual(
            bd.primary_component.amount_usd, real.execution_cost_dollars
        )
        self.assertAlmostEqual(bd.primary_component.amount_usd, 6.30)

    def test_drag_estimate_wins_when_larger(self):
        bd = extract_scanner_unified_final_cost(
            trade=self.TRADE, market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=9.99, num_legs=2, entry_cost=1.00,
        )
        self.assertAlmostEqual(bd.primary_component.amount_usd, 9.99)

    def test_layer_1a_vs_1b_divergence_is_real(self):
        """The two scanner layers DISAGREE on the same candidate (0.25 vs 0.5
        take fraction) — the max() hides it in production; here it is typed."""
        drag = extract_scanner_drag_cost(
            drag_map={}, symbol="TST", combo_width_share=0.10, num_legs=2,
        )
        final = extract_scanner_unified_final_cost(
            trade=self.TRADE, market_data={"bid_ask_spread_pct": 0.10},
            execution_drag_estimate=drag.primary_component.amount_usd,
            num_legs=2, entry_cost=1.00,
        )
        self.assertAlmostEqual(drag.primary_component.amount_usd, 3.80)
        self.assertAlmostEqual(final.primary_component.amount_usd, 6.30)
        self.assertGreater(
            final.primary_component.amount_usd,
            drag.primary_component.amount_usd,
        )


# ── Basis 2: canonical ranker fees + slippage ───────────────────────────────

def _suggestion(*, legs, contracts=1, ev=100.0, tcm=None, sizing_extra=None):
    s = {
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
    if tcm is not None:
        s["tcm"] = tcm
    if sizing_extra:
        s["sizing_metadata"].update(sizing_extra)
    return s


class TestRankerParity(_RealModulesTestCase):
    def test_fees_byte_equal_and_pinned(self):
        for legs, contracts, expected in (
            (2, 1, 2.60), (4, 1, 5.20), (4, 3, 15.60), (2, 5, 13.00),
        ):
            s = _suggestion(legs=legs, contracts=contracts)
            real = _ranking_round_trip_fees(copy.deepcopy(s))
            bd = extract_ranker_costs(s)
            fees = bd.component("round_trip_fees")
            self.assertEqual(fees.amount_usd, real)
            self.assertAlmostEqual(fees.amount_usd, expected)

    def test_extractor_never_mutates_caller(self):
        s = _suggestion(legs=2, contracts=1)
        extract_ranker_costs(s)
        self.assertNotIn("ranking_costs", s)  # production WOULD stamp this

    def test_slippage_branches_byte_equal(self):
        cases = (
            (_suggestion(legs=2, tcm={"expected_slippage": 12.5}),
             "branch=tcm_expected_slippage", 12.5),
            (_suggestion(legs=2,
                         sizing_extra={"expected_slippage": 7.25}),
             "branch=sizing_expected_slippage", 7.25),
            (_suggestion(legs=2, ev=100.0),
             "branch=five_pct_of_ev_floor", 5.0),
            (_suggestion(legs=2, ev=0.0),
             "branch=zero_no_ev", 0.0),
        )
        for s, branch, expected in cases:
            real = _estimate_slippage(copy.deepcopy(s))
            bd = extract_ranker_costs(s)
            slip = bd.component("expected_slippage")
            self.assertEqual(slip.amount_usd, real, branch)
            self.assertAlmostEqual(slip.amount_usd, expected, msg=branch)
            self.assertEqual(slip.provenance.source_detail, branch)

    def test_primary_is_fees_plus_slippage(self):
        s = _suggestion(legs=2, contracts=1, ev=100.0)
        bd = extract_ranker_costs(s)
        self.assertAlmostEqual(
            bd.primary_component.amount_usd, 2.60 + 5.0
        )


# ── Basis 3: stage executable cross (SOFI 06-30 fixture) ────────────────────

SOFI_LONG = "O:SOFI260807C00017000"   # bid/ask 1.93/2.16, cross 0.23
SOFI_SHORT = "O:SOFI260807C00020500"  # bid/ask 0.67/0.71, cross 0.04
SOFI_QUOTES = {
    SOFI_LONG: {"bid": 1.93, "ask": 2.16},
    SOFI_SHORT: {"bid": 0.67, "ask": 0.71},
}
SOFI_QTY = 5


def _sofi_legs(qty=SOFI_QTY):
    return [
        {"occ_symbol": SOFI_LONG, "action": "buy", "quantity": qty,
         "strike": 17.0},
        {"occ_symbol": SOFI_SHORT, "action": "sell", "quantity": qty,
         "strike": 20.5},
    ]


class TestStageCrossParity(_RealModulesTestCase):
    def test_sofi_fixture_byte_equal(self):
        real = executable_roundtrip_cost(
            legs=_sofi_legs(), leg_quotes=SOFI_QUOTES, quantity=SOFI_QTY,
        )
        bd = extract_stage_executable_cross(
            legs=_sofi_legs(), leg_quotes=SOFI_QUOTES, quantity=SOFI_QTY,
        )
        self.assertEqual(
            bd.component("round_trip_total").amount_usd, real["round_trip"]
        )
        self.assertEqual(
            bd.component("round_trip_per_contract").amount_usd,
            real["round_trip_per_contract"],
        )
        # Pinned: (0.23 + 0.04) x 5 x 100 = $135 total, $27/contract.
        self.assertAlmostEqual(
            bd.component("round_trip_total").amount_usd, 135.0
        )
        self.assertAlmostEqual(
            bd.component("round_trip_per_contract").amount_usd, 27.0
        )

    def test_incomplete_quote_matches_production_none(self):
        quotes = {SOFI_LONG: {"bid": 1.93, "ask": 2.16},
                  SOFI_SHORT: {"bid": 0.67, "ask": None}}
        real = executable_roundtrip_cost(
            legs=_sofi_legs(), leg_quotes=quotes, quantity=SOFI_QTY,
        )
        self.assertIsNone(real["round_trip"])
        bd = extract_stage_executable_cross(
            legs=_sofi_legs(), leg_quotes=quotes, quantity=SOFI_QTY,
        )
        self.assertFalse(bd.component("round_trip_total").available)


class TestE2LegacyBasisGateParity(_RealModulesTestCase):
    """Drive the REAL production stage gate end-to-end at qty>1 and assert
    the typed reconciliation reproduces the gate's own numbers exactly:
    legacy (live, flag OFF) decides on gross_ev - TOTAL; the fixed basis is
    gross_ev - per_contract. Same inputs, opposite decisions."""

    QTY = 4
    EV = 45.0
    QUOTES = {
        "O:TST260101C00100000": {"bid": 2.00, "ask": 2.10},
        "O:TST260101C00105000": {"bid": 1.00, "ask": 1.10},
    }

    def _ticket(self):
        return TradeTicket(
            symbol="TST",
            legs=[
                OptionLeg(symbol="O:TST260101C00100000", action="buy",
                          strike=100.0, quantity=self.QTY),
                OptionLeg(symbol="O:TST260101C00105000", action="sell",
                          strike=105.0, quantity=self.QTY),
            ],
            quantity=self.QTY,
            expected_value=self.EV,
            limit_price=1.05,
        )

    def _legs_dicts(self):
        return [
            {"occ_symbol": "O:TST260101C00100000", "action": "buy",
             "quantity": self.QTY, "strike": 100.0},
            {"occ_symbol": "O:TST260101C00105000", "action": "sell",
             "quantity": self.QTY, "strike": 105.0},
        ]

    def test_gate_reject_net_equals_typed_legacy_net(self):
        from packages.quantum.paper_endpoints import (
            EntryRoundtripCostExceedsEV,
            _apply_entry_roundtrip_gate,
        )

        env = dict(os.environ)
        env.pop("ENTRY_ROUNDTRIP_COST_GATE_ENABLED", None)  # default ON
        env.pop("GATE_QTY_FIX_LIVE_ENABLED", None)          # default OFF
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
                _apply_entry_roundtrip_gate(
                    None, self._ticket(), None, self.QUOTES,
                    suggestion_id=None, is_shadow=False,
                )
        exc = ctx.exception

        stage = extract_stage_executable_cross(
            legs=self._legs_dicts(), leg_quotes=self.QUOTES,
            quantity=self.QTY,
        )
        recon = reconcile_cost_bases(
            quantity=self.QTY, gross_ev=self.EV, stage=stage,
        )
        d = recon.delta("quantity_scaling_stage_total_vs_per_contract")

        # The REAL gate's applied (legacy) numbers == the typed report's.
        self.assertEqual(
            exc.round_trip, stage.component("round_trip_total").amount_usd
        )
        self.assertEqual(exc.net, d.detail["legacy_net"])
        self.assertEqual(exc.gross_ev, self.EV)
        # And the fixed basis flips the decision (>= $15 floor).
        self.assertLess(d.detail["legacy_net"], 15.0)
        self.assertGreaterEqual(d.detail["fixed_net"], 15.0)
        self.assertIn("legacy_gate_basis_divergent_qty_gt_1", recon.flags)

    def test_shadow_routing_applies_fixed_basis_and_allows(self):
        from packages.quantum.paper_endpoints import (
            _apply_entry_roundtrip_gate,
        )

        env = dict(os.environ)
        env.pop("ENTRY_ROUNDTRIP_COST_GATE_ENABLED", None)
        env.pop("GATE_QTY_FIX_LIVE_ENABLED", None)
        with patch.dict(os.environ, env, clear=True):
            # Shadow cohorts always get the fixed per-contract decision:
            # net = 45 - 20/contract = 25 >= 15 -> no raise.
            _apply_entry_roundtrip_gate(
                None, self._ticket(), None, self.QUOTES,
                suggestion_id=None, is_shadow=True,
            )


# ── Basis 4a: execution TransactionCostModel.estimate ───────────────────────

class TestExecutionTcmParity(_RealModulesTestCase):
    def _ticket(self, qty=2, limit=1.10):
        return TradeTicket(
            symbol="TST",
            legs=[OptionLeg(symbol="O:TST260101C00100000", action="buy")],
            quantity=qty, limit_price=limit,
        )

    def test_estimate_byte_equal_and_pinned(self):
        quote = {"bid_price": 1.00, "ask_price": 1.20}
        real = ExecutionTCM.estimate(ticket=self._ticket(), quote=dict(quote))
        bd = extract_tcm_estimate(ticket=self._ticket(), quote=quote)
        self.assertEqual(bd.component("fees").amount_usd, real["fees_usd"])
        self.assertEqual(
            bd.component("expected_spread_cost").amount_usd,
            real["expected_spread_cost_usd"],
        )
        self.assertEqual(
            bd.component("expected_slippage").amount_usd,
            real["expected_slippage_usd"],
        )
        # Pinned: fees 2 x 0.65 = 1.30 (ONE-WAY, leg-count-blind);
        # spread (0.20/2) x 2 x 100 = 20.00; slippage 1.10 x 200 x 5bps = 0.11
        self.assertAlmostEqual(bd.component("fees").amount_usd, 1.30)
        self.assertAlmostEqual(
            bd.component("expected_spread_cost").amount_usd, 20.00
        )
        self.assertAlmostEqual(
            bd.component("expected_slippage").amount_usd, 0.11
        )
        self.assertFalse(bd.provenance.fallback)

    def test_missing_quote_fallback_reproduced_and_flagged(self):
        real = ExecutionTCM.estimate(ticket=self._ticket(limit=2.00), quote=None)
        self.assertTrue(real["used_fallback"])
        bd = extract_tcm_estimate(ticket=self._ticket(limit=2.00), quote=None)
        # Production FABRICATES bid/ask at +/-1% of limit — reproduced
        # exactly (frozen baseline), but typed fallback=True.
        self.assertEqual(
            bd.component("expected_spread_cost").amount_usd,
            real["expected_spread_cost_usd"],
        )
        self.assertTrue(bd.provenance.fallback)
        self.assertIn(
            "fabricated_pm1pct_of_limit", bd.provenance.source_detail
        )


# ── Basis 4b: the SECOND (legacy) TransactionCostModel ──────────────────────

class TestLegacyTcmParity(_RealModulesTestCase):
    def test_estimate_costs_byte_equal_and_pinned(self):
        real = LegacyTCM().estimate_costs(price=1.5, quantity=2, side="buy")
        bd = extract_legacy_tcm_estimate(price=1.5, quantity=2)
        self.assertEqual(bd.primary_component.amount_usd, real)
        # Pinned: slippage 1.5 x 5bps x 2 = 0.0015 (NO x100 option
        # multiplier — the legacy model's frozen defect) + fees 1.30.
        self.assertAlmostEqual(bd.primary_component.amount_usd, 1.3015)

    def test_no_multiplier_divergence_vs_execution_tcm(self):
        """The two same-named TCMs disagree by ~x100 on slippage for the
        same option economics — formalized as typed provenance."""
        bd = extract_legacy_tcm_estimate(price=1.5, quantity=2)
        self.assertIn(
            "legacy_no_option_multiplier",
            bd.primary_component.provenance.source_detail,
        )

    def test_missing_inputs_typed_unavailable(self):
        bd = extract_legacy_tcm_estimate(price=None, quantity=2)
        self.assertFalse(bd.available)
        self.assertIn(
            "price", bd.primary_component.unavailable_reason
        )


# ── Basis 5: realized close_fill_gap ────────────────────────────────────────

class TestRealizedParity(_RealModulesTestCase):
    def test_sofi_debit_close_byte_equal(self):
        oj = {"close_fill_gap_cross": 1.31, "close_fill_gap_mid": 1.525}
        cross, mid = read_stamp(oj)
        fill = broker_fill_to_mark_basis(-1.36)
        real_gap = compute_gap_fraction(cross, mid, fill)
        rc = extract_realized_close_costs(
            order_json=oj, broker_fill=-1.36, quantity=1,
        )
        self.assertEqual(rc.gap_fraction, real_gap)
        self.assertAlmostEqual(rc.gap_fraction, 0.05 / 0.215)
        self.assertEqual(
            rc.breakdown.component("realized_fill_mark").amount_usd,
            fill * 100.0,
        )

    def test_qqq_credit_close_negation_map(self):
        # QQQ 07-07 (close_fill_gap.py:92): broker +1.64 debit -> -1.64 in
        # mark basis; gap = (-1.64 + 1.98) / (-1.74 + 1.98) = 1.4166...
        oj = {"close_fill_gap_cross": -1.98, "close_fill_gap_mid": -1.74}
        rc = extract_realized_close_costs(
            order_json=oj, broker_fill=1.64, quantity=1,
        )
        self.assertEqual(
            rc.gap_fraction,
            compute_gap_fraction(-1.98, -1.74, broker_fill_to_mark_basis(1.64)),
        )
        self.assertAlmostEqual(rc.gap_fraction, 0.34 / 0.24)
        self.assertAlmostEqual(
            rc.breakdown.component("realized_fill_mark").amount_usd, -164.0
        )

    def test_degenerate_mid_equals_cross_gap_none(self):
        oj = {"close_fill_gap_cross": 1.50, "close_fill_gap_mid": 1.50}
        rc = extract_realized_close_costs(
            order_json=oj, broker_fill=-1.50, quantity=1,
        )
        self.assertIsNone(rc.gap_fraction)


if __name__ == "__main__":
    unittest.main()
