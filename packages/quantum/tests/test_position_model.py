"""Tests for the canonical position representation (PR-1: contract + math only).

Two halves:

  PHASE 1 — TestCurrentDefects now proves D1 closed at the first production
  consumer while retaining executable evidence for D2-D5. Each later consumer
  migration must invert its defect assertion rather than delete it.

  PHASE 2 — the golden fixtures, payoff/greek/reconciliation contracts, and the
  typed rejection matrices for the new module.

Style follows the risk/ package's own tests (test_legs_convention.py,
test_payoff_bound_guard.py): unittest.TestCase, module-level factories with
inline dicts, assertAlmostEqual(places=2).
"""

import unittest
from datetime import date
from pathlib import Path

from packages.quantum.risk.risk_envelope import (
    EnvelopeConfig,
    PositionRiskUnavailable,
    _pos_risk,
    check_greeks,
    compute_stress_scenarios,
)
from packages.quantum.risk.position_model import (
    CanonicalLeg,
    CanonicalPosition,
    Completeness,
    GreekExposure,
    IncompletenessReason,
    LegGreeks,
    ObservedLeg,
    OptionType,
    PositionNormalizationError,
    Provenance,
    RejectReason,
    RiskClassification,
    aggregate_greeks,
    analyze_payoff,
    clamp_stress_to_payoff,
    entry_cashflow_from_net_premium,
    expiration_pnl,
    intrinsic_value,
    normalize_position,
    reconcile_legs,
)

EXPIRY = date(2026, 9, 18)
_PROV = Provenance(source="test")
_COMPLETE = Completeness(representation_incomplete=False)


# ══════════════════════════════════════════════════════════════════════════
# Factories
# ══════════════════════════════════════════════════════════════════════════


def _occ(root: str, right: str, strike: float) -> str:
    """Build an OCC symbol: ROOT + YYMMDD + C/P + strike*1000 zero-padded to 8."""
    return f"{root}260918{right}{int(round(strike * 1000)):08d}"


def _leg(
    root: str,
    right: str,
    strike: float,
    signed_ratio: int,
    *,
    multiplier: float = 100.0,
    greeks=None,
) -> CanonicalLeg:
    return CanonicalLeg(
        occ_symbol=_occ(root, right, strike),
        underlying=root,
        expiry=EXPIRY,
        option_type=OptionType.CALL if right == "C" else OptionType.PUT,
        strike=strike,
        signed_ratio=signed_ratio,
        multiplier=multiplier,
        greeks=greeks,
    )


def _position(
    legs,
    total_entry_cashflow: float,
    structure_quantity: int = 1,
    root: str = "SPY",
) -> CanonicalPosition:
    return CanonicalPosition(
        underlying=root,
        expiry=EXPIRY,
        currency="USD",
        structure_quantity=structure_quantity,
        legs=tuple(legs),
        total_entry_cashflow=total_entry_cashflow,
        provenance=_PROV,
        completeness=_COMPLETE,
    )


# ── The nine golden structures ────────────────────────────────────────────


def _f1_short_put_vertical() -> CanonicalPosition:
    """100/95 short put vertical, $1.20 credit, qty 2 -> max loss $760."""
    return _position(
        [_leg("SPY", "P", 100.0, -1), _leg("SPY", "P", 95.0, +1)],
        total_entry_cashflow=+1.20 * 100 * 2,
        structure_quantity=2,
    )


def _f2_short_call_vertical() -> CanonicalPosition:
    """100/105 short call vertical, $1.20 credit, qty 2 -> max loss $760."""
    return _position(
        [_leg("SPY", "C", 100.0, -1), _leg("SPY", "C", 105.0, +1)],
        total_entry_cashflow=+1.20 * 100 * 2,
        structure_quantity=2,
    )


def _f3_qqq_iron_condor() -> CanonicalPosition:
    """QQQ 650/645P + 765/770C, $1.49 credit, qty 1 -> max loss $351."""
    return _position(
        [
            _leg("QQQ", "P", 650.0, -1),
            _leg("QQQ", "P", 645.0, +1),
            _leg("QQQ", "C", 765.0, -1),
            _leg("QQQ", "C", 770.0, +1),
        ],
        total_entry_cashflow=+1.49 * 100 * 1,
        structure_quantity=1,
        root="QQQ",
    )


def _f4_asymmetric_condor() -> CanonicalPosition:
    """5-pt put wing / 10-pt call wing, $2.00 credit, qty 1 -> max loss $800.

    The wider wing sets the bound. A width-blind or symmetric-assuming
    calculation reports the 5-pt put wing's $300 and understates by $500.
    """
    return _position(
        [
            _leg("SPY", "P", 95.0, -1),
            _leg("SPY", "P", 90.0, +1),
            _leg("SPY", "C", 105.0, -1),
            _leg("SPY", "C", 115.0, +1),
        ],
        total_entry_cashflow=+2.00 * 100 * 1,
        structure_quantity=1,
    )


def _f5_debit_vertical() -> CanonicalPosition:
    """100/105 long call vertical, $1.50 debit, qty 3 -> max loss $450."""
    return _position(
        [_leg("SPY", "C", 100.0, +1), _leg("SPY", "C", 105.0, -1)],
        total_entry_cashflow=-1.50 * 100 * 3,
        structure_quantity=3,
    )


def _f6_put_ratio() -> CanonicalPosition:
    """1x2 put ratio: long 1x 100P, short 2x 95P, $1.00 credit, qty 1.

    True max loss $8,900 at S=0. Treat both ratios as +/-1 and the same
    structure prices as RISKLESS. This is the ratio-blindness proof.
    """
    return _position(
        [_leg("SPY", "P", 100.0, +1), _leg("SPY", "P", 95.0, -2)],
        total_entry_cashflow=+1.00 * 100 * 1,
        structure_quantity=1,
    )


def _f6_ratio_blind() -> CanonicalPosition:
    """The same structure with the ratio flattened to 1 — what D3 sees."""
    return _position(
        [_leg("SPY", "P", 100.0, +1), _leg("SPY", "P", 95.0, -1)],
        total_entry_cashflow=+1.00 * 100 * 1,
        structure_quantity=1,
    )


def _f7_naked_short_call() -> CanonicalPosition:
    """Short 100C, $3.00 credit, qty 1 -> unbounded loss."""
    return _position(
        [_leg("SPY", "C", 100.0, -1)],
        total_entry_cashflow=+3.00 * 100 * 1,
        structure_quantity=1,
    )


def _f8_reordered_condor() -> CanonicalPosition:
    """_f3's legs in a different order — must be indistinguishable."""
    return _position(
        [
            _leg("QQQ", "C", 770.0, +1),
            _leg("QQQ", "P", 650.0, -1),
            _leg("QQQ", "C", 765.0, -1),
            _leg("QQQ", "P", 645.0, +1),
        ],
        total_entry_cashflow=+1.49 * 100 * 1,
        structure_quantity=1,
        root="QQQ",
    )


def _persisted_short_put_vertical(qty: int = -2, premium: float = 1.20) -> dict:
    """_f1 as paper_positions actually stores it.

    Persisted convention: quantity SIGNED (negative == credit), legs carry
    FULL-COUNT quantity (== abs(pos.quantity)), avg_entry_price ABSOLUTE.
    """
    full = abs(qty)
    return {
        "id": "pos-1",
        "quantity": qty,
        "avg_entry_price": premium,
        "legs": [
            {
                "symbol": _occ("SPY", "P", 100.0),
                "action": "sell",
                "type": "put",
                "strike": 100.0,
                "expiry": "2026-09-18",
                "quantity": full,
            },
            {
                "symbol": _occ("SPY", "P", 95.0),
                "action": "buy",
                "type": "put",
                "strike": 95.0,
                "expiry": "2026-09-18",
                "quantity": full,
            },
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# PHASE 1 — reproduce the current defects against LIVE risk_envelope code
# ══════════════════════════════════════════════════════════════════════════


class TestCurrentDefects(unittest.TestCase):
    """Consumer-closure evidence plus the remaining live defects.

    D1 is inverted by canonical-position PR-2. D2-D5 remain pinned to the live
    envelope until their own one-consumer migrations; never delete them.
    """

    def test_d1_exact_max_loss_replaces_credit_received(self):
        """The first consumer returns exact payoff max loss, already qty-scaled."""
        pos = _persisted_short_put_vertical()

        actual = _pos_risk(pos)
        honest = analyze_payoff(_f1_short_put_vertical()).max_loss_total

        self.assertAlmostEqual(actual, 760.0, places=2)
        self.assertAlmostEqual(actual, honest, places=2)
        self.assertNotAlmostEqual(actual, 240.0, places=2)

    def test_d1_strike_width_changes_risk(self):
        """Widening the protective leg changes exact risk; strikes are consumed."""
        narrow = _persisted_short_put_vertical()
        wide = _persisted_short_put_vertical()
        wide["legs"][1]["symbol"] = _occ("SPY", "P", 80.0)
        wide["legs"][1]["strike"] = 80.0

        self.assertAlmostEqual(_pos_risk(narrow), 760.0, places=2)
        self.assertAlmostEqual(_pos_risk(wide), 3760.0, places=2)
        self.assertGreater(_pos_risk(wide), _pos_risk(narrow))

    def test_d1_missing_structure_fails_closed(self):
        """Premium alone can no longer masquerade as a finite risk number."""
        with self.assertRaises(PositionRiskUnavailable):
            _pos_risk(
                {"id": "missing-legs", "max_credit": 1.20,
                 "quantity": -2, "avg_entry_price": 1.20}
            )

    def test_d1_unbounded_structure_fails_closed(self):
        """The defined-risk envelope must not fabricate a cap for a naked call."""
        naked = {
            "id": "naked-call",
            "quantity": -1,
            "avg_entry_price": 3.00,
            "legs": [{
                "symbol": _occ("SPY", "C", 100.0),
                "action": "sell",
                "type": "call",
                "strike": 100.0,
                "expiry": "2026-09-18",
                "quantity": 1,
            }],
        }
        with self.assertRaises(PositionRiskUnavailable):
            _pos_risk(naked)

    def test_d2_opposing_leg_greeks_add_instead_of_netting(self):
        """risk_envelope.py:226-233 reads no side, so long+short ADD."""
        # A delta-neutral-by-construction structure: +0.50 long, -0.50 short.
        pos = {
            "quantity": 1,
            "legs": [
                {"action": "buy", "greeks": {"delta": 0.50}},
                {"action": "sell", "greeks": {"delta": 0.50}},
            ],
        }
        _violations, greeks = check_greeks([pos], EnvelopeConfig())

        # Live code: 0.50*100 + 0.50*100 = 100. The short leg added.
        self.assertAlmostEqual(greeks["delta"], 100.0, places=2)

        # Honest: the legs net to zero.
        honest = aggregate_greeks(
            _position(
                [
                    _leg("SPY", "C", 100.0, +1, greeks=LegGreeks(delta=0.50, gamma=0, vega=0, theta=0)),
                    _leg("SPY", "C", 105.0, -1, greeks=LegGreeks(delta=0.50, gamma=0, vega=0, theta=0)),
                ],
                total_entry_cashflow=-100.0,
            )
        )
        self.assertAlmostEqual(honest.delta_dollars_per_underlying_point, 0.0, places=2)

    def test_d2_greeks_envelope_is_dormant_no_leg_carries_greeks(self):
        """The persisted leg schema has no `greeks` key, so the sum is all zeros.

        paper_endpoints.py:1290 writes {occ_symbol, action, quantity, strike}.
        risk_envelope.py:229 reads leg["greeks"] — a key no writer has ever set.
        """
        realistic = {
            "quantity": 2,
            "legs": [
                {"occ_symbol": _occ("SPY", "P", 100.0), "action": "sell", "quantity": 2, "strike": 100.0},
                {"occ_symbol": _occ("SPY", "P", 95.0), "action": "buy", "quantity": 2, "strike": 95.0},
            ],
        }
        _violations, greeks = check_greeks([realistic], EnvelopeConfig())
        self.assertEqual(
            greeks, {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        )

        # The honest module refuses to call that a flat book.
        canonical = normalize_position(_persisted_short_put_vertical())
        exposure = aggregate_greeks(canonical)
        self.assertFalse(exposure.complete)
        self.assertIsNone(exposure.delta_dollars_per_underlying_point)
        self.assertEqual(len(exposure.missing_legs), 2)

    def test_d2_greek_caps_default_to_no_limit(self):
        """Second dormancy limb: all four caps default 0 and 0 means no limit."""
        config = EnvelopeConfig()
        self.assertEqual(config.max_portfolio_delta, 0.0)
        self.assertEqual(config.max_portfolio_gamma, 0.0)
        self.assertEqual(config.max_portfolio_vega, 0.0)
        self.assertEqual(config.max_portfolio_theta, 0.0)

        huge = {"quantity": 1000, "legs": [{"greeks": {"delta": 9.99}}]}
        violations, greeks = check_greeks([huge], config)
        self.assertAlmostEqual(greeks["delta"], 999000.0, places=2)
        self.assertEqual(violations, [])  # no cap => no violation, at any size

    def test_d3_leg_ratios_are_ignored(self):
        """The loop scales every leg by the POSITION quantity, not leg quantity."""
        # A 1x2 ratio: leg quantities 1 and 2.
        pos = {
            "quantity": 1,
            "legs": [
                {"action": "buy", "quantity": 1, "greeks": {"delta": 0.50}},
                {"action": "buy", "quantity": 2, "greeks": {"delta": 0.50}},
            ],
        }
        _violations, greeks = check_greeks([pos], EnvelopeConfig())
        # Both legs scaled by qty=1: 50 + 50 = 100. The 2x leg counted once.
        self.assertAlmostEqual(greeks["delta"], 100.0, places=2)
        # Ratio-aware: 0.50*1*100 + 0.50*2*100 = 150.
        self.assertNotAlmostEqual(greeks["delta"], 150.0, places=2)

    def test_d3_ratio_blindness_prices_a_ratio_spread_as_riskless(self):
        """The payoff consequence of D3, in dollars."""
        true_loss = analyze_payoff(_f6_put_ratio()).max_loss_total
        blind_loss = analyze_payoff(_f6_ratio_blind()).max_loss_total

        self.assertAlmostEqual(true_loss, 8900.0, places=2)
        self.assertAlmostEqual(blind_loss, 0.0, places=2)  # "cannot lose"

    def test_d4_multiplier_is_hardcoded_100(self):
        """No per-leg multiplier is read anywhere; 100 is a literal."""
        pos = {"max_credit": 1.00, "quantity": 1}
        self.assertAlmostEqual(_pos_risk(pos), 100.0, places=2)

        # A mini/non-standard contract (multiplier 10) is unrepresentable: the
        # live code has no field to carry it, so it prices at 100 regardless.
        pos_mini = {"max_credit": 1.00, "quantity": 1, "multiplier": 10}
        self.assertAlmostEqual(_pos_risk(pos_mini), 100.0, places=2)
        self.assertEqual(_pos_risk(pos), _pos_risk(pos_mini))

        # The honest module carries it and the payoff scales with it.
        ten = _position(
            [_leg("SPY", "P", 100.0, -1, multiplier=10.0), _leg("SPY", "P", 95.0, +1, multiplier=10.0)],
            total_entry_cashflow=+1.20 * 10 * 2,
            structure_quantity=2,
        )
        self.assertAlmostEqual(analyze_payoff(ten).max_loss_total, 76.0, places=2)

    def test_d5_stress_can_exceed_the_defined_risk_payoff_bound(self):
        """A linear delta extrapolation has no payoff floor.

        risk_envelope.py:522-540 computes delta x shock and takes the min of
        three scenarios with no clamp. A defined-risk structure cannot lose
        more than its max loss — that is arithmetic, not policy.
        """
        condor = _f3_qqq_iron_condor()
        max_loss = analyze_payoff(condor).max_loss_total
        self.assertAlmostEqual(max_loss, 351.0, places=2)

        # A stress engine extrapolating delta linearly through a big shock.
        raw_stress_pnl = -5000.0
        clamp = clamp_stress_to_payoff(condor, raw_stress_pnl)

        self.assertTrue(clamp.applicable)
        self.assertTrue(clamp.violated)
        self.assertAlmostEqual(clamp.floor_total, -351.0, places=2)
        self.assertAlmostEqual(clamp.clamped_total_pnl, -351.0, places=2)
        # The unclamped number is 14x the structure's true worst case.
        self.assertLess(clamp.raw_total_pnl, clamp.floor_total)

    def test_d5_correlation_one_stress_inherits_the_credit_basis(self):
        """`corr_one_loss = -total_risk` (:535) is -sum(credit), not -max_loss."""
        pos = {"max_credit": 1.49, "quantity": -1, "legs": []}
        _violations, results = compute_stress_scenarios([pos], equity=10000.0, config=EnvelopeConfig())

        # Live: "all positions at max loss" reports -$149 (the credit).
        self.assertAlmostEqual(results["correlation_one"] * 10000.0, -149.0, places=2)
        # Honest max loss for that structure is -$351.
        honest = analyze_payoff(_f3_qqq_iron_condor()).max_loss_total
        self.assertAlmostEqual(honest, 351.0, places=2)


# ══════════════════════════════════════════════════════════════════════════
# PHASE 2 — golden fixtures
# ══════════════════════════════════════════════════════════════════════════


class TestGoldenFixtures(unittest.TestCase):
    def test_1_short_put_vertical_760(self):
        profile = analyze_payoff(_f1_short_put_vertical())
        self.assertAlmostEqual(profile.max_loss_total, 760.0, places=2)
        self.assertAlmostEqual(profile.max_profit_total, 240.0, places=2)
        self.assertIs(profile.classification, RiskClassification.DEFINED_RISK)

    def test_2_short_call_vertical_is_the_mirror(self):
        profile = analyze_payoff(_f2_short_call_vertical())
        self.assertAlmostEqual(profile.max_loss_total, 760.0, places=2)
        self.assertAlmostEqual(profile.max_profit_total, 240.0, places=2)
        # Identical bounds to the put vertical of the same width and credit.
        put = analyze_payoff(_f1_short_put_vertical())
        self.assertAlmostEqual(profile.max_loss_total, put.max_loss_total, places=2)

    def test_3_qqq_iron_condor_351(self):
        profile = analyze_payoff(_f3_qqq_iron_condor())
        self.assertAlmostEqual(profile.max_loss_total, 351.0, places=2)
        self.assertAlmostEqual(profile.max_profit_total, 149.0, places=2)
        self.assertIs(profile.classification, RiskClassification.DEFINED_RISK)

    def test_4_asymmetric_condor_uses_the_wider_wing(self):
        profile = analyze_payoff(_f4_asymmetric_condor())
        self.assertAlmostEqual(profile.max_loss_total, 800.0, places=2)
        self.assertAlmostEqual(profile.max_profit_total, 200.0, places=2)

        # The narrow (put) side would have said $300 — the bound is the max
        # over the surface, not the first wing found.
        self.assertAlmostEqual(expiration_pnl(_f4_asymmetric_condor(), 0.0), -300.0, places=2)
        self.assertAlmostEqual(expiration_pnl(_f4_asymmetric_condor(), 115.0), -800.0, places=2)

    def test_5_debit_vertical_450(self):
        profile = analyze_payoff(_f5_debit_vertical())
        self.assertAlmostEqual(profile.max_loss_total, 450.0, places=2)
        # Debit vertical max profit = (width - debit) * mult * qty.
        self.assertAlmostEqual(profile.max_profit_total, (5.0 - 1.5) * 100 * 3, places=2)
        self.assertIs(profile.classification, RiskClassification.DEFINED_RISK)

    def test_6_signed_ratios_change_the_answer(self):
        ratio = analyze_payoff(_f6_put_ratio())
        blind = analyze_payoff(_f6_ratio_blind())

        self.assertAlmostEqual(ratio.max_loss_total, 8900.0, places=2)
        self.assertAlmostEqual(ratio.max_profit_total, 600.0, places=2)
        self.assertAlmostEqual(blind.max_loss_total, 0.0, places=2)
        self.assertNotAlmostEqual(ratio.max_loss_total, blind.max_loss_total, places=2)

    def test_7_naked_short_call_is_not_defined_risk(self):
        profile = analyze_payoff(_f7_naked_short_call())
        self.assertIs(profile.classification, RiskClassification.NOT_DEFINED_RISK)
        self.assertTrue(profile.loss_unbounded)
        self.assertIsNone(profile.max_loss_total)
        self.assertLess(profile.upside_slope, 0)

    def test_7_naked_long_call_has_unbounded_profit_but_defined_risk(self):
        long_call = _position(
            [_leg("SPY", "C", 100.0, +1)], total_entry_cashflow=-300.0
        )
        profile = analyze_payoff(long_call)
        self.assertIs(profile.classification, RiskClassification.DEFINED_RISK)
        self.assertAlmostEqual(profile.max_loss_total, 300.0, places=2)
        self.assertIsNone(profile.max_profit_total)
        self.assertTrue(profile.profit_unbounded)

    def test_7_short_put_downside_is_bounded_at_s_zero(self):
        """S=0 is a real endpoint: a short put's worst case is finite."""
        short_put = _position(
            [_leg("SPY", "P", 100.0, -1)], total_entry_cashflow=+300.0
        )
        profile = analyze_payoff(short_put)
        self.assertIs(profile.classification, RiskClassification.DEFINED_RISK)
        self.assertAlmostEqual(profile.max_loss_total, 100 * 100 - 300.0, places=2)

    def test_8_leg_order_does_not_change_payoff_or_risk(self):
        a = analyze_payoff(_f3_qqq_iron_condor())
        b = analyze_payoff(_f8_reordered_condor())

        self.assertAlmostEqual(a.max_loss_total, b.max_loss_total, places=2)
        self.assertAlmostEqual(a.max_profit_total, b.max_profit_total, places=2)
        self.assertEqual(a.classification, b.classification)
        self.assertEqual(a.breakpoints, b.breakpoints)
        for s in (0.0, 645.0, 650.0, 700.0, 765.0, 770.0, 900.0):
            self.assertAlmostEqual(
                expiration_pnl(_f3_qqq_iron_condor(), s),
                expiration_pnl(_f8_reordered_condor(), s),
                places=6,
            )

    def test_9_invalid_multiplier_matrix_fails_typed(self):
        for bad in (0, -1, -100.0, float("nan"), float("inf")):
            with self.subTest(multiplier=bad):
                with self.assertRaises(PositionNormalizationError) as ctx:
                    _leg("SPY", "P", 100.0, -1, multiplier=bad)
                self.assertIn(
                    ctx.exception.reason,
                    (RejectReason.NON_POSITIVE_MULTIPLIER, RejectReason.NON_FINITE),
                )

    def test_9_invalid_contract_count_matrix_fails_typed(self):
        cases = [
            (0, RejectReason.NON_POSITIVE_STRUCTURE_QUANTITY),
            (-2, RejectReason.NON_POSITIVE_STRUCTURE_QUANTITY),
            (True, RejectReason.NOT_A_NUMBER),
            (2.5, RejectReason.NOT_A_NUMBER),
        ]
        for qty, reason in cases:
            with self.subTest(structure_quantity=qty):
                with self.assertRaises(PositionNormalizationError) as ctx:
                    _position(
                        [_leg("SPY", "P", 100.0, -1)],
                        total_entry_cashflow=100.0,
                        structure_quantity=qty,
                    )
                self.assertIs(ctx.exception.reason, reason)

    def test_9_zero_signed_ratio_fails_typed(self):
        with self.assertRaises(PositionNormalizationError) as ctx:
            _leg("SPY", "P", 100.0, 0)
        self.assertIs(ctx.exception.reason, RejectReason.ZERO_QUANTITY)

    def test_9_malformed_strike_fails_typed(self):
        # Built directly: a NaN/inf strike cannot round-trip through an OCC
        # symbol, so the factory cannot express these cases.
        for bad in (0.0, -5.0, float("nan"), float("inf")):
            with self.subTest(strike=bad):
                with self.assertRaises(PositionNormalizationError) as ctx:
                    CanonicalLeg(
                        occ_symbol=_occ("SPY", "P", 100.0),
                        underlying="SPY",
                        expiry=EXPIRY,
                        option_type=OptionType.PUT,
                        strike=bad,
                        signed_ratio=-1,
                        multiplier=100.0,
                    )
                self.assertIs(ctx.exception.reason, RejectReason.MALFORMED_STRIKE)


# ══════════════════════════════════════════════════════════════════════════
# Payoff contract
# ══════════════════════════════════════════════════════════════════════════


class TestPayoffContract(unittest.TestCase):
    def test_intrinsic_value_is_never_negative(self):
        self.assertAlmostEqual(intrinsic_value(OptionType.CALL, 100.0, 90.0), 0.0, places=6)
        self.assertAlmostEqual(intrinsic_value(OptionType.CALL, 100.0, 110.0), 10.0, places=6)
        self.assertAlmostEqual(intrinsic_value(OptionType.PUT, 100.0, 110.0), 0.0, places=6)
        self.assertAlmostEqual(intrinsic_value(OptionType.PUT, 100.0, 90.0), 10.0, places=6)

    def test_negative_underlying_price_rejects(self):
        with self.assertRaises(PositionNormalizationError) as ctx:
            intrinsic_value(OptionType.CALL, 100.0, -1.0)
        self.assertIs(ctx.exception.reason, RejectReason.NOT_A_NUMBER)

    def test_breakpoints_include_zero_and_every_strike(self):
        profile = analyze_payoff(_f3_qqq_iron_condor())
        self.assertEqual(profile.breakpoints, (0.0, 645.0, 650.0, 765.0, 770.0))

    def test_min_pnl_is_exact_not_sampled(self):
        """Piecewise-linear: a dense scan must not beat the breakpoint minimum."""
        condor = _f4_asymmetric_condor()
        floor = -analyze_payoff(condor).max_loss_total
        for i in range(0, 3001):
            s = i * 0.1
            self.assertGreaterEqual(expiration_pnl(condor, s) - floor, -1e-9)

    def test_totals_are_position_level_and_scale_once(self):
        """Doubling quantity doubles the totals — and only once."""
        one = _position(
            [_leg("SPY", "P", 100.0, -1), _leg("SPY", "P", 95.0, +1)],
            total_entry_cashflow=+1.20 * 100 * 1,
            structure_quantity=1,
        )
        two = _f1_short_put_vertical()
        self.assertAlmostEqual(analyze_payoff(one).max_loss_total, 380.0, places=2)
        self.assertAlmostEqual(
            analyze_payoff(two).max_loss_total,
            2 * analyze_payoff(one).max_loss_total,
            places=2,
        )

    def test_stress_clamp_not_applicable_to_undefined_risk(self):
        """There is no floor to clamp to; inventing one would fabricate a bound."""
        clamp = clamp_stress_to_payoff(_f7_naked_short_call(), -1_000_000.0)
        self.assertFalse(clamp.applicable)
        self.assertIsNone(clamp.floor_total)
        self.assertFalse(clamp.violated)
        self.assertAlmostEqual(clamp.clamped_total_pnl, -1_000_000.0, places=2)

    def test_stress_within_bound_is_untouched(self):
        clamp = clamp_stress_to_payoff(_f3_qqq_iron_condor(), -100.0)
        self.assertTrue(clamp.applicable)
        self.assertFalse(clamp.violated)
        self.assertAlmostEqual(clamp.clamped_total_pnl, -100.0, places=2)


# ══════════════════════════════════════════════════════════════════════════
# Greek contract
# ══════════════════════════════════════════════════════════════════════════


def _g(delta=0.0, gamma=0.0, vega=0.0, theta=0.0) -> LegGreeks:
    return LegGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta)


class TestGreekContract(unittest.TestCase):
    def test_aggregation_is_signed_ratio_x_qty_x_multiplier(self):
        pos = _position(
            [
                _leg("SPY", "P", 100.0, -1, greeks=_g(delta=-0.30, gamma=0.02, vega=0.10, theta=-0.05)),
                _leg("SPY", "P", 95.0, +1, greeks=_g(delta=-0.20, gamma=0.01, vega=0.08, theta=-0.03)),
            ],
            total_entry_cashflow=+240.0,
            structure_quantity=2,
        )
        exposure = aggregate_greeks(pos)

        # delta: (-1*2*100*-0.30) + (+1*2*100*-0.20) = 60 - 40 = 20
        self.assertAlmostEqual(exposure.delta_dollars_per_underlying_point, 20.0, places=2)
        # gamma: (-1*2*100*0.02) + (+1*2*100*0.01) = -4 + 2 = -2
        self.assertAlmostEqual(exposure.gamma_dollars_per_point_squared, -2.0, places=2)
        # vega: (-1*2*100*0.10) + (+1*2*100*0.08) = -20 + 16 = -4
        self.assertAlmostEqual(exposure.vega_dollars_per_vol_point, -4.0, places=2)
        # theta: (-1*2*100*-0.05) + (+1*2*100*-0.03) = 10 - 6 = 4
        self.assertAlmostEqual(exposure.theta_dollars_per_day, 4.0, places=2)
        self.assertTrue(exposure.complete)

    def test_ratios_scale_greeks(self):
        pos = _position(
            [
                _leg("SPY", "P", 100.0, +1, greeks=_g(delta=-0.50)),
                _leg("SPY", "P", 95.0, -2, greeks=_g(delta=-0.25)),
            ],
            total_entry_cashflow=+100.0,
        )
        # (+1*1*100*-0.50) + (-2*1*100*-0.25) = -50 + 50 = 0
        self.assertAlmostEqual(
            aggregate_greeks(pos).delta_dollars_per_underlying_point, 0.0, places=2
        )

    def test_missing_greeks_never_claim_a_flat_book(self):
        pos = _position(
            [
                _leg("SPY", "P", 100.0, -1, greeks=_g(delta=-0.30)),
                _leg("SPY", "P", 95.0, +1, greeks=None),
            ],
            total_entry_cashflow=+240.0,
        )
        exposure = aggregate_greeks(pos)
        self.assertFalse(exposure.complete)
        self.assertIsNone(exposure.delta_dollars_per_underlying_point)
        self.assertEqual(exposure.missing_legs, (_occ("SPY", "P", 95.0),))

    def test_partially_missing_greek_nulls_only_that_greek(self):
        pos = _position(
            [
                _leg("SPY", "P", 100.0, -1, greeks=LegGreeks(delta=-0.30, gamma=0.02, vega=None, theta=-0.05)),
                _leg("SPY", "P", 95.0, +1, greeks=LegGreeks(delta=-0.20, gamma=0.01, vega=0.08, theta=-0.03)),
            ],
            total_entry_cashflow=+240.0,
        )
        exposure = aggregate_greeks(pos)
        self.assertFalse(exposure.complete)
        self.assertIsNone(exposure.vega_dollars_per_vol_point)
        # The greeks that WERE complete still report.
        self.assertAlmostEqual(exposure.delta_dollars_per_underlying_point, 10.0, places=2)
        self.assertIn("vega", exposure.missing_detail[0])

    def test_genuine_zero_is_distinguishable_from_missing(self):
        pos = _position(
            [
                _leg("SPY", "C", 100.0, +1, greeks=_g(delta=0.50)),
                _leg("SPY", "C", 105.0, -1, greeks=_g(delta=0.50)),
            ],
            total_entry_cashflow=-100.0,
        )
        exposure = aggregate_greeks(pos)
        self.assertTrue(exposure.complete)
        self.assertEqual(exposure.delta_dollars_per_underlying_point, 0.0)
        self.assertIsNotNone(exposure.delta_dollars_per_underlying_point)


# ══════════════════════════════════════════════════════════════════════════
# Reconciliation contract
# ══════════════════════════════════════════════════════════════════════════


class TestReconciliation(unittest.TestCase):
    def _observed_for_f1(self):
        return [
            ObservedLeg(occ_symbol=_occ("SPY", "P", 100.0), signed_contracts=-2),
            ObservedLeg(occ_symbol=_occ("SPY", "P", 95.0), signed_contracts=+2),
        ]

    def test_exact_match(self):
        report = reconcile_legs(_f1_short_put_vertical(), self._observed_for_f1())
        self.assertTrue(report.matched)
        self.assertEqual(report.discrepancies, ())

    def test_expected_contracts_are_ratio_x_structure_quantity(self):
        observed = [
            ObservedLeg(occ_symbol=_occ("SPY", "P", 100.0), signed_contracts=-1),
            ObservedLeg(occ_symbol=_occ("SPY", "P", 95.0), signed_contracts=+1),
        ]
        report = reconcile_legs(_f1_short_put_vertical(), observed)
        self.assertFalse(report.matched)
        self.assertEqual(len(report.quantity_mismatched), 2)
        self.assertEqual(report.quantity_mismatched[0].expected, -2)
        self.assertEqual(report.quantity_mismatched[0].observed, -1)

    def test_missing_leg(self):
        report = reconcile_legs(
            _f1_short_put_vertical(), [self._observed_for_f1()[0]]
        )
        self.assertFalse(report.matched)
        self.assertEqual(len(report.missing), 1)
        self.assertEqual(report.missing[0].occ_symbol, _occ("SPY", "P", 95.0))

    def test_extra_leg(self):
        observed = self._observed_for_f1() + [
            ObservedLeg(occ_symbol=_occ("SPY", "C", 120.0), signed_contracts=+1)
        ]
        report = reconcile_legs(_f1_short_put_vertical(), observed)
        self.assertFalse(report.matched)
        self.assertEqual(len(report.extra), 1)
        self.assertEqual(report.extra[0].occ_symbol, _occ("SPY", "C", 120.0))

    def test_direction_mismatch_is_distinct_from_quantity_mismatch(self):
        observed = [
            ObservedLeg(occ_symbol=_occ("SPY", "P", 100.0), signed_contracts=+2),  # flipped
            ObservedLeg(occ_symbol=_occ("SPY", "P", 95.0), signed_contracts=+2),
        ]
        report = reconcile_legs(_f1_short_put_vertical(), observed)
        self.assertFalse(report.matched)
        self.assertEqual(len(report.direction_mismatched), 1)
        self.assertEqual(len(report.quantity_mismatched), 0)
        self.assertEqual(report.direction_mismatched[0].expected, -2)
        self.assertEqual(report.direction_mismatched[0].observed, +2)

    def test_attribute_mismatch_reported_when_observed_supplies_it(self):
        observed = [
            ObservedLeg(occ_symbol=_occ("SPY", "P", 100.0), signed_contracts=-2, multiplier=10.0),
            ObservedLeg(occ_symbol=_occ("SPY", "P", 95.0), signed_contracts=+2),
        ]
        report = reconcile_legs(_f1_short_put_vertical(), observed)
        self.assertFalse(report.matched)
        kinds = {d.kind for d in report.discrepancies}
        self.assertIn("attribute_mismatch", kinds)


# ══════════════════════════════════════════════════════════════════════════
# Normalization from the persisted convention
# ══════════════════════════════════════════════════════════════════════════


class TestNormalization(unittest.TestCase):
    def test_persisted_credit_row_normalizes_to_the_honest_basis(self):
        pos = normalize_position(_persisted_short_put_vertical())

        self.assertEqual(pos.underlying, "SPY")
        self.assertEqual(pos.expiry, EXPIRY)
        self.assertEqual(pos.structure_quantity, 2)
        # Negative persisted quantity means CREDIT: cashflow is positive.
        self.assertAlmostEqual(pos.total_entry_cashflow, +240.0, places=2)
        self.assertAlmostEqual(analyze_payoff(pos).max_loss_total, 760.0, places=2)
        self.assertEqual(pos.provenance.position_id, "pos-1")

    def test_persisted_debit_row_signs_cashflow_negative(self):
        raw = _persisted_short_put_vertical(qty=+2, premium=1.20)
        pos = normalize_position(raw)
        self.assertAlmostEqual(pos.total_entry_cashflow, -240.0, places=2)

    def test_full_count_legs_recover_a_ratio_of_one(self):
        pos = normalize_position(_persisted_short_put_vertical(qty=-2))
        self.assertEqual(sorted(l.signed_ratio for l in pos.legs), [-1, 1])

    def test_missing_quantity_rejects_rather_than_defaulting_to_one(self):
        raw = _persisted_short_put_vertical()
        del raw["quantity"]
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.MISSING_FIELD)

    def test_missing_leg_quantity_rejects_rather_than_defaulting_to_one(self):
        raw = _persisted_short_put_vertical()
        del raw["legs"][0]["quantity"]
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.MISSING_FIELD)

    def test_bool_quantity_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["quantity"] = True
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.BOOL_NOT_ALLOWED)

    def test_fractional_quantity_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["quantity"] = -2.5
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.FRACTIONAL_QUANTITY)

    def test_nan_and_inf_premium_reject(self):
        for bad in (float("nan"), float("inf")):
            with self.subTest(premium=bad):
                raw = _persisted_short_put_vertical()
                raw["avg_entry_price"] = bad
                with self.assertRaises(PositionNormalizationError) as ctx:
                    normalize_position(raw)
                self.assertIs(ctx.exception.reason, RejectReason.NON_FINITE)

    def test_unknown_side_rejects_instead_of_defaulting_to_buy(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][0]["action"] = "wibble"
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.UNKNOWN_SIDE)

    def test_scanner_side_key_is_accepted(self):
        raw = _persisted_short_put_vertical()
        for leg in raw["legs"]:
            leg["side"] = leg.pop("action")
        pos = normalize_position(raw)
        self.assertEqual(sorted(l.signed_ratio for l in pos.legs), [-1, 1])

    def test_unparseable_occ_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][0]["symbol"] = "NOT-AN-OCC-SYMBOL"
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.UNPARSEABLE_OCC)

    def test_dict_strike_disagreeing_with_occ_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][0]["strike"] = 42.0  # OCC says 100
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.MALFORMED_STRIKE)

    def test_dict_type_disagreeing_with_occ_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][0]["type"] = "call"  # OCC says put
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.UNKNOWN_OPTION_TYPE)

    def test_inconsistent_underlying_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][1]["symbol"] = _occ("QQQ", "P", 95.0)
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.INCONSISTENT_UNDERLYING)

    def test_calendar_spread_is_not_representable_and_says_so(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][1]["symbol"] = "SPY261218P00095000"
        raw["legs"][1]["expiry"] = "2026-12-18"
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.INCONSISTENT_EXPIRY)

    def test_no_legs_rejects(self):
        raw = _persisted_short_put_vertical()
        raw["legs"] = []
        with self.assertRaises(PositionNormalizationError) as ctx:
            normalize_position(raw)
        self.assertIs(ctx.exception.reason, RejectReason.NO_LEGS)

    def test_completeness_names_the_unrepresentable_fields(self):
        pos = normalize_position(_persisted_short_put_vertical())
        self.assertTrue(pos.completeness.representation_incomplete)
        self.assertIn(
            IncompletenessReason.GREEKS_NOT_PERSISTED, pos.completeness.reasons
        )
        self.assertIn(
            IncompletenessReason.MULTIPLIER_ASSUMED_STANDARD_OCC,
            pos.completeness.reasons,
        )
        self.assertIn(
            IncompletenessReason.CURRENCY_ASSUMED_USD, pos.completeness.reasons
        )
        self.assertEqual(len(pos.completeness.missing_greek_legs), 2)

    def test_supplied_greeks_clear_the_greek_incompleteness(self):
        greeks = {
            _occ("SPY", "P", 100.0): _g(delta=-0.30),
            _occ("SPY", "P", 95.0): _g(delta=-0.20),
        }
        pos = normalize_position(
            _persisted_short_put_vertical(), greeks_by_symbol=greeks
        )
        self.assertNotIn(
            IncompletenessReason.GREEKS_NOT_PERSISTED, pos.completeness.reasons
        )
        self.assertEqual(pos.completeness.missing_greek_legs, ())
        self.assertTrue(aggregate_greeks(pos).complete)

    def test_explicit_multiplier_clears_the_multiplier_assumption(self):
        raw = _persisted_short_put_vertical()
        for leg in raw["legs"]:
            leg["multiplier"] = 100.0
        pos = normalize_position(raw)
        self.assertNotIn(
            IncompletenessReason.MULTIPLIER_ASSUMED_STANDARD_OCC,
            pos.completeness.reasons,
        )

    def test_entry_cashflow_helper_sign_convention(self):
        self.assertAlmostEqual(
            entry_cashflow_from_net_premium(1.20, True, 2, 100.0), +240.0, places=2
        )
        self.assertAlmostEqual(
            entry_cashflow_from_net_premium(1.50, False, 3, 100.0), -450.0, places=2
        )

    def test_entry_cashflow_helper_rejects_a_signed_premium(self):
        with self.assertRaises(PositionNormalizationError) as ctx:
            entry_cashflow_from_net_premium(-1.20, True, 2, 100.0)
        self.assertIs(ctx.exception.reason, RejectReason.NOT_A_NUMBER)


# ══════════════════════════════════════════════════════════════════════════
# Adversarial constructor and identity invariants
# ══════════════════════════════════════════════════════════════════════════


class TestAdversarialModelInvariants(unittest.TestCase):
    def test_close_actions_describe_the_position_being_closed(self):
        raw = _persisted_short_put_vertical()
        raw["legs"][0]["action"] = "BTC"  # closes a short leg
        raw["legs"][1]["action"] = "STC"  # closes a long leg
        pos = normalize_position(raw)
        by_strike = {leg.strike: leg.signed_ratio for leg in pos.legs}
        self.assertEqual(by_strike, {100.0: -1, 95.0: +1})

    def test_leg_greeks_reject_bool_nan_and_infinity(self):
        for field in ("delta", "gamma", "vega", "theta"):
            for bad in (True, float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, bad=bad):
                    kwargs = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
                    kwargs[field] = bad
                    with self.assertRaises(PositionNormalizationError):
                        LegGreeks(**kwargs)

    def test_direct_leg_constructor_rejects_bool_scalars(self):
        for field in ("strike", "multiplier"):
            with self.subTest(field=field):
                kwargs = {
                    "occ_symbol": _occ("SPY", "P", 100.0),
                    "underlying": "SPY",
                    "expiry": EXPIRY,
                    "option_type": OptionType.PUT,
                    "strike": 100.0,
                    "signed_ratio": -1,
                    "multiplier": 100.0,
                }
                kwargs[field] = True
                with self.assertRaises(PositionNormalizationError) as ctx:
                    CanonicalLeg(**kwargs)
                self.assertIs(ctx.exception.reason, RejectReason.BOOL_NOT_ALLOWED)

    def test_position_rejects_nonfinite_or_bool_cashflow(self):
        for bad in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                with self.assertRaises(PositionNormalizationError):
                    _position(
                        [_leg("SPY", "P", 100.0, -1)],
                        total_entry_cashflow=bad,
                    )

    def test_entry_cashflow_rejects_nonpositive_structure_quantity(self):
        for bad in (0, -1):
            with self.subTest(quantity=bad):
                with self.assertRaises(PositionNormalizationError) as ctx:
                    entry_cashflow_from_net_premium(1.20, True, bad, 100.0)
                self.assertIs(
                    ctx.exception.reason,
                    RejectReason.NON_POSITIVE_STRUCTURE_QUANTITY,
                )

    def test_position_rejects_duplicate_expected_occ_symbols(self):
        leg = _leg("SPY", "P", 100.0, -1)
        with self.assertRaises(PositionNormalizationError) as ctx:
            _position([leg, leg], total_entry_cashflow=120.0)
        self.assertIs(ctx.exception.reason, RejectReason.DUPLICATE_LEG)

    def test_reconciliation_reports_duplicate_observed_occ_symbols(self):
        short = ObservedLeg(
            occ_symbol=_occ("SPY", "P", 100.0), signed_contracts=-2
        )
        observed = [
            short,
            short,
            ObservedLeg(
                occ_symbol=_occ("SPY", "P", 95.0), signed_contracts=+2
            ),
        ]
        report = reconcile_legs(_f1_short_put_vertical(), observed)
        self.assertFalse(report.matched)
        self.assertEqual(len(report.duplicated), 1)
        self.assertEqual(report.duplicated[0].observed, 2)


# ══════════════════════════════════════════════════════════════════════════
# Non-interference — PR-1's core contract
# ══════════════════════════════════════════════════════════════════════════


class TestNonInterference(unittest.TestCase):
    def test_exactly_one_production_consumer_imports_position_model(self):
        """PR-2 migrates risk_envelope only; later consumers stay separate."""
        root = Path(__file__).resolve().parents[3]
        consumers = []
        for path in root.rglob("*.py"):
            parts = path.parts
            if any(
                p in ("tests", ".venv", "venv", "site-packages", "__pycache__", "node_modules")
                for p in parts
            ):
                continue
            if path.name == "position_model.py":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "position_model" in text:
                consumers.append(str(path.relative_to(root)))
        self.assertEqual(
            consumers,
            ["packages/quantum/risk/risk_envelope.py"],
            f"canonical consumer boundary drifted: {consumers}",
        )

    def test_first_consumer_changes_only_risk_basis(self):
        """D1 closes while the separately-gated greeks migration stays dormant."""
        self.assertAlmostEqual(
            _pos_risk(_persisted_short_put_vertical()), 760.0, places=2
        )
        _violations, greeks = check_greeks(
            [{"quantity": 1, "legs": [{"action": "buy", "greeks": {"delta": 0.5}}]}],
            EnvelopeConfig(),
        )
        self.assertAlmostEqual(greeks["delta"], 50.0, places=2)


if __name__ == "__main__":
    unittest.main()
