"""Tests for the canonical position representation (PR-1: contract + math only).

Two halves:

  PHASE 1 — TestCurrentDefects proves the production consumers close D1, D4
  (PR-2), and D5 in full — correlation-one basis plus the linear-stress
  payoff clamp (PR-3) — while retaining executable evidence for D2 and D3.
  Each later consumer migration must invert its defect assertion rather than
  delete it.

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
    aggregate_canonical_greeks,
    check_all_envelopes,
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
    leg_greeks_from_persisted,
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


def _persisted_debit_call_vertical(qty: int = 3, premium: float = 1.50) -> dict:
    """_f5 as persisted: POSITIVE quantity == debit, full-count legs.

    100/105 long call vertical, $1.50 debit, qty 3 -> max loss $450.
    """
    full = abs(qty)
    return {
        "id": "spy-debit-cv",
        "symbol": "SPY",
        "quantity": qty,
        "avg_entry_price": premium,
        "legs": [
            {"symbol": _occ("SPY", "C", 100.0), "action": "buy",
             "type": "call", "strike": 100.0, "expiry": "2026-09-18",
             "quantity": full},
            {"symbol": _occ("SPY", "C", 105.0), "action": "sell",
             "type": "call", "strike": 105.0, "expiry": "2026-09-18",
             "quantity": full},
        ],
    }


def _with_leg_greeks(pos: dict, **greeks) -> dict:
    """Attach the same greeks dict to every leg of a persisted position."""
    for leg in pos["legs"]:
        leg["greeks"] = dict(greeks)
    return pos


def _permissive_config(**overrides) -> EnvelopeConfig:
    """Config that silences concentration noise so stress asserts stay pure."""
    config = EnvelopeConfig(
        max_single_symbol_pct=1.0,
        max_sector_pct=1.0,
        max_same_expiry_pct=1.0,
        max_correlation_cluster_pct=1.0,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _persisted_iron_condor() -> dict:
    """_f3 as a persisted one-contract credit structure."""
    return {
        "id": "qqq-ic",
        "quantity": -1,
        "avg_entry_price": 1.49,
        "legs": [
            {"symbol": _occ("QQQ", "P", 650.0), "action": "sell",
             "type": "put", "strike": 650.0, "expiry": "2026-09-18",
             "quantity": 1},
            {"symbol": _occ("QQQ", "P", 645.0), "action": "buy",
             "type": "put", "strike": 645.0, "expiry": "2026-09-18",
             "quantity": 1},
            {"symbol": _occ("QQQ", "C", 765.0), "action": "sell",
             "type": "call", "strike": 765.0, "expiry": "2026-09-18",
             "quantity": 1},
            {"symbol": _occ("QQQ", "C", 770.0), "action": "buy",
             "type": "call", "strike": 770.0, "expiry": "2026-09-18",
             "quantity": 1},
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# PHASE 1 — reproduce the current defects against LIVE risk_envelope code
# ══════════════════════════════════════════════════════════════════════════


class TestCurrentDefects(unittest.TestCase):
    """Consumer-closure evidence plus the remaining live defects.

    D1, D4, and correlation-one D5 are inverted by canonical-position PR-2;
    the unclamped linear-stress slice of D5 is inverted by PR-3 (payoff-capped
    stress). D2 and D3 remain pinned; never delete them. (The D2/D3 fixtures now
    carry COMPLETE greeks blocks — all four values finite — because check_greeks
    was made null-safe: it aggregates a leg only when delta/gamma/vega/theta are
    all present and finite, contributing nothing otherwise, never a fabricated 0.
    The defects themselves — no side-netting, position-quantity-not-leg-ratio
    scaling — are unchanged and still asserted verbatim.)
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
        """risk_envelope.py check_greeks reads no side, so long+short ADD."""
        # A delta-neutral-by-construction structure: +0.50 long, -0.50 short.
        # Complete greeks blocks (all four finite): check_greeks is now null-safe
        # and only aggregates a leg whose delta/gamma/vega/theta are ALL present
        # and finite (matching #1259's complete-or-null populate contract and
        # aggregate_greeks.complete). The D2 defect — no side-netting — is
        # unchanged and still pinned by the delta==100 assertion below.
        pos = {
            "quantity": 1,
            "legs": [
                {"action": "buy", "greeks": {"delta": 0.50, "gamma": 0.0, "vega": 0.0, "theta": 0.0}},
                {"action": "sell", "greeks": {"delta": 0.50, "gamma": 0.0, "vega": 0.0, "theta": 0.0}},
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

        # Complete greeks block (null-safe completeness bar — see D2 netting test).
        huge = {"quantity": 1000,
                "legs": [{"greeks": {"delta": 9.99, "gamma": 0.0, "vega": 0.0, "theta": 0.0}}]}
        violations, greeks = check_greeks([huge], config)
        self.assertAlmostEqual(greeks["delta"], 999000.0, places=2)
        self.assertEqual(violations, [])  # no cap => no violation, at any size

    def test_d3_leg_ratios_are_ignored(self):
        """The loop scales every leg by the POSITION quantity, not leg quantity."""
        # A 1x2 ratio: leg quantities 1 and 2. Complete greeks blocks (null-safe
        # completeness bar); D3 ratio-blindness is unchanged and still pinned.
        pos = {
            "quantity": 1,
            "legs": [
                {"action": "buy", "quantity": 1, "greeks": {"delta": 0.50, "gamma": 0.0, "vega": 0.0, "theta": 0.0}},
                {"action": "buy", "quantity": 2, "greeks": {"delta": 0.50, "gamma": 0.0, "vega": 0.0, "theta": 0.0}},
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

    def test_d4_multiplier_is_read_from_each_leg(self):
        """The canonical consumer prices standard and mini multipliers honestly."""
        standard = _persisted_short_put_vertical()
        mini = _persisted_short_put_vertical()
        for leg in mini["legs"]:
            leg["multiplier"] = 10

        self.assertAlmostEqual(_pos_risk(standard), 760.0, places=2)
        self.assertAlmostEqual(_pos_risk(mini), 76.0, places=2)
        self.assertNotEqual(_pos_risk(standard), _pos_risk(mini))

        ten = _position(
            [_leg("SPY", "P", 100.0, -1, multiplier=10.0),
             _leg("SPY", "P", 95.0, +1, multiplier=10.0)],
            total_entry_cashflow=+1.20 * 10 * 2,
            structure_quantity=2,
        )
        self.assertAlmostEqual(
            _pos_risk(mini), analyze_payoff(ten).max_loss_total, places=2
        )

    def test_d5_stress_can_no_longer_exceed_the_defined_risk_payoff_bound(self):
        """INVERTED by PR-3: the production stress route clamps at the floor.

        The defect: a linear delta extrapolation with no payoff floor could
        win `worst = min(...)`. Now the production route floors every
        scenario at -Σ canonical max loss; the raw phantom is preserved in
        `spy_down_raw` but can no longer set the worst case. A defined-risk
        structure cannot lose more than its max loss — arithmetic, not
        policy.
        """
        condor = _f3_qqq_iron_condor()
        max_loss = analyze_payoff(condor).max_loss_total
        self.assertAlmostEqual(max_loss, 351.0, places=2)

        # A phantom per-contract delta drives the linear model far past the
        # structure's true worst case (the D5 class).
        pos = _persisted_iron_condor()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": 50.0, "vega": 0.0}

        _violations, results, unavailable = compute_stress_scenarios(
            [pos], equity=10000.0, config=EnvelopeConfig()
        )

        # Raw extrapolation: 4 legs x 50 x 1 x 100 = 20,000 delta dollars;
        # x 5% shock = -$1,000 — 2.8x the structure's true worst case.
        self.assertAlmostEqual(results["spy_down_raw"] * 10000.0, -1000.0, places=2)
        # Clamped at the canonical payoff floor, exactly.
        self.assertAlmostEqual(results["spy_down"] * 10000.0, -max_loss, places=2)
        # The phantom can no longer win the min(): worst == the payoff bound.
        self.assertAlmostEqual(results["worst_case"] * 10000.0, -max_loss, places=2)
        self.assertEqual(unavailable, {})

        # The pure-form clamp the route consumes agrees with itself.
        clamp = clamp_stress_to_payoff(condor, -1000.0)
        self.assertTrue(clamp.applicable)
        self.assertTrue(clamp.violated)
        self.assertAlmostEqual(clamp.clamped_total_pnl, -351.0, places=2)

    def test_d5_correlation_one_uses_exact_payoff_max_loss(self):
        """Correlation-one stress inherits the canonical position risk."""
        pos = _persisted_iron_condor()
        _violations, results, _unavailable = compute_stress_scenarios(
            [pos], equity=10000.0, config=EnvelopeConfig()
        )

        honest = analyze_payoff(_f3_qqq_iron_condor()).max_loss_total
        self.assertAlmostEqual(honest, 351.0, places=2)
        self.assertAlmostEqual(
            results["correlation_one"] * 10000.0, -honest, places=2
        )
        self.assertNotAlmostEqual(
            results["correlation_one"] * 10000.0, -149.0, places=2
        )


# ══════════════════════════════════════════════════════════════════════════
# PR-3 — payoff-capped stress at the REAL consumer route
# ══════════════════════════════════════════════════════════════════════════


class TestPayoffCappedStress(unittest.TestCase):
    """Drive check_all_envelopes — the entrypoint all four production callers
    (autopilot breaker, intraday monitor, MTM, midday orchestrator) invoke —
    and assert the stress outcome at the top (doctrine: inject the failure at
    its origin, assert the truth at the top).
    """

    EQUITY = 10000.0

    def test_credit_book_cap_binds_exactly_at_sum_max_loss(self):
        """Phantom delta on a credit vertical: stress loss == Σ max loss."""
        pos = _with_leg_greeks(
            _persisted_short_put_vertical(), delta=50.0, vega=0.0
        )
        result = check_all_envelopes(
            [pos], equity=self.EQUITY, config=_permissive_config()
        )
        sr = result.stress_results

        # Raw linear model: 2 legs x 50 x |qty 2| x 100 = 20,000 delta
        # dollars; x 5% shock = -$1,000 > the $760 the structure can lose.
        self.assertAlmostEqual(sr["spy_down_raw"] * self.EQUITY, -1000.0, places=2)
        self.assertAlmostEqual(sr["spy_down"] * self.EQUITY, -760.0, places=2)
        self.assertAlmostEqual(sr["worst_case"] * self.EQUITY, -760.0, places=2)
        self.assertAlmostEqual(sr["correlation_one"], sr["worst_case"], places=10)
        self.assertEqual(result.stress_unavailable, {})

    def test_debit_book_cap_binds_exactly_at_sum_max_loss(self):
        pos = _with_leg_greeks(
            _persisted_debit_call_vertical(), delta=50.0, vega=0.0
        )
        result = check_all_envelopes(
            [pos], equity=self.EQUITY, config=_permissive_config()
        )
        sr = result.stress_results

        # 2 legs x 50 x |qty 3| x 100 = 30,000; x 5% = -$1,500 vs $450 cap.
        self.assertAlmostEqual(sr["spy_down_raw"] * self.EQUITY, -1500.0, places=2)
        self.assertAlmostEqual(sr["spy_down"] * self.EQUITY, -450.0, places=2)
        self.assertAlmostEqual(sr["worst_case"] * self.EQUITY, -450.0, places=2)

    def test_mixed_book_cap_is_the_book_level_sum(self):
        """Credit + debit book: the floor is Σ per-structure max losses."""
        book = [
            _with_leg_greeks(_persisted_short_put_vertical(), delta=50.0, vega=0.0),
            _with_leg_greeks(_persisted_debit_call_vertical(), delta=50.0, vega=0.0),
        ]
        result = check_all_envelopes(
            book, equity=self.EQUITY, config=_permissive_config()
        )
        sr = result.stress_results

        self.assertAlmostEqual(sr["spy_down_raw"] * self.EQUITY, -2500.0, places=2)
        self.assertAlmostEqual(sr["spy_down"] * self.EQUITY, -(760.0 + 450.0), places=2)
        self.assertAlmostEqual(sr["worst_case"] * self.EQUITY, -1210.0, places=2)
        self.assertAlmostEqual(sr["correlation_one"] * self.EQUITY, -1210.0, places=2)

    def test_healthy_uncapped_book_matches_the_legacy_model_exactly(self):
        """Stress under the cap: values equal the legacy arithmetic, no
        _raw keys, no unavailability — the healthy path is unchanged."""
        pos = _with_leg_greeks(
            _persisted_short_put_vertical(), delta=0.30, vega=0.05
        )
        config = _permissive_config()
        result = check_all_envelopes([pos], equity=self.EQUITY, config=config)
        sr = result.stress_results

        # Replicate the legacy computation with identical expressions.
        qty = float(pos["quantity"])
        total_delta = 0.0
        total_vega = 0.0
        for leg in pos["legs"]:
            total_delta += float(leg["greeks"]["delta"]) * abs(qty) * 100
            total_vega += float(leg["greeks"]["vega"]) * abs(qty) * 100
        expected_spy = (total_delta * config.stress_spy_down_pct * -1) / self.EQUITY
        expected_vix = (total_vega * config.stress_vix_spike_pct * 100) / self.EQUITY

        self.assertEqual(
            set(sr.keys()),
            {"spy_down", "vix_spike", "correlation_one", "worst_case"},
        )
        self.assertEqual(sr["spy_down"], expected_spy)
        self.assertEqual(sr["vix_spike"], expected_vix)
        self.assertAlmostEqual(sr["correlation_one"] * self.EQUITY, -760.0, places=2)
        self.assertEqual(
            sr["worst_case"],
            min(expected_spy, expected_vix, sr["correlation_one"]),
        )
        self.assertEqual(result.stress_unavailable, {})
        self.assertEqual(
            [v for v in result.violations if v.envelope == "stress_scenario"], []
        )

    def test_unrepresentable_structure_raises_typed_never_finite(self):
        """A naked short call in the book: typed unavailability, no number."""
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
        book = [_persisted_short_put_vertical(), naked]
        with self.assertRaises(PositionRiskUnavailable):
            check_all_envelopes(book, equity=self.EQUITY, config=_permissive_config())
        with self.assertRaises(PositionRiskUnavailable):
            compute_stress_scenarios(book, self.EQUITY, _permissive_config())

    def test_missing_greeks_scenarios_typed_unavailable_not_zero(self):
        """The production-realistic book (no persisted greeks, §8): the greek
        scenarios are OMITTED + typed, never reported as a fabricated 0."""
        book = [_persisted_short_put_vertical(), _persisted_iron_condor()]
        result = check_all_envelopes(
            book, equity=self.EQUITY, config=_permissive_config()
        )
        sr = result.stress_results

        self.assertNotIn("spy_down", sr)
        self.assertNotIn("vix_spike", sr)
        self.assertIn("correlation_one", sr)
        self.assertAlmostEqual(
            sr["worst_case"] * self.EQUITY, -(760.0 + 351.0), places=2
        )
        self.assertEqual(
            result.stress_unavailable["spy_down"],
            {"reason": "greeks_missing", "missing_field": "delta",
             "legs_missing": 6},
        )
        self.assertEqual(
            result.stress_unavailable["vix_spike"],
            {"reason": "greeks_missing", "missing_field": "vega",
             "legs_missing": 6},
        )
        # Unavailability is a typed field, NOT a violation (would write a
        # risk_alerts row every monitor cycle for the ledgered dormancy).
        self.assertEqual(
            [v for v in result.violations if "unavailable" in v.envelope], []
        )
        # And the serialized result carries the typed record.
        import json
        as_dict = result.to_dict()
        self.assertNotIn("spy_down", as_dict["stress_results"])
        self.assertEqual(
            as_dict["stress_unavailable"]["spy_down"]["reason"],
            "greeks_missing",
        )
        json.dumps(as_dict)  # to_dict stays JSON-serializable

    def test_stress_violation_still_fires_on_the_honest_bound(self):
        """The warn violation predicate reads the CLAMPED worst case."""
        book = [_persisted_short_put_vertical(), _persisted_iron_condor()]
        result = check_all_envelopes(
            book, equity=5000.0, config=_permissive_config()
        )
        stress_v = [v for v in result.violations if v.envelope == "stress_scenario"]
        # worst = -(760+351)/5000 = -22.2% beyond the 15% default limit.
        self.assertEqual(len(stress_v), 1)
        self.assertEqual(stress_v[0].severity, "warn")
        self.assertAlmostEqual(stress_v[0].actual, 1111.0 / 5000.0, places=4)

    def test_partial_greeks_disable_only_the_missing_scenario(self):
        pos = _persisted_short_put_vertical()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": 0.30}  # vega absent
        result = check_all_envelopes(
            [pos], equity=self.EQUITY, config=_permissive_config()
        )
        sr = result.stress_results

        self.assertIn("spy_down", sr)
        self.assertNotIn("vix_spike", sr)
        self.assertEqual(list(result.stress_unavailable), ["vix_spike"])
        self.assertEqual(
            sr["worst_case"], min(sr["spy_down"], sr["correlation_one"])
        )

    def test_none_greek_injected_at_origin_is_unavailable_not_a_crash(self):
        """A leg carrying delta=None used to TypeError the STRESS computation
        (float(None)); now it is a typed per-scenario unavailability.

        Driven at the stress entrypoint: the unmigrated check_greeks (D2
        lane, deliberately untouched by this consumer) still float()-crashes
        on a None greek upstream inside check_all_envelopes, so the full
        route cannot demonstrate the stress seam's behavior until the greeks
        consumer migrates. That residual belongs to the D2 lane.
        """
        pos = _persisted_short_put_vertical()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": None, "vega": 0.05}
        _violations, results, unavailable = compute_stress_scenarios(
            [pos], self.EQUITY, _permissive_config()
        )

        self.assertNotIn("spy_down", results)
        self.assertEqual(unavailable["spy_down"]["missing_field"], "delta")
        self.assertEqual(unavailable["spy_down"]["legs_missing"], 2)
        self.assertIn("vix_spike", results)


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
                # as_posix(): the boundary literal below is posix-form; the
                # raw str() is backslashed on Windows and made this guard
                # fail there regardless of the actual consumer set.
                consumers.append(path.relative_to(root).as_posix())
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
        # Complete greeks block (null-safe completeness bar — check_greeks now
        # aggregates a leg only when all four greeks are present and finite).
        _violations, greeks = check_greeks(
            [{"quantity": 1, "legs": [
                {"action": "buy", "greeks": {"delta": 0.5, "gamma": 0.0, "vega": 0.0, "theta": 0.0}}]}],
            EnvelopeConfig(),
        )
        self.assertAlmostEqual(greeks["delta"], 50.0, places=2)


# ══════════════════════════════════════════════════════════════════════════
# 4A — persisted stage-time leg greeks wired into the canonical consumer
# ══════════════════════════════════════════════════════════════════════════


def _persisted_debit_qty3_with_greeks() -> dict:
    """_f5 debit call vertical (qty 3, debit) carrying per-leg stage greeks.

    leg0 buy 100C (signed_ratio +1), leg1 sell 105C (signed_ratio -1),
    full-count leg qty 3.
    """
    pos = _persisted_debit_call_vertical(qty=3, premium=1.50)
    pos["legs"][0]["greeks"] = {"delta": 0.60, "gamma": 0.03, "vega": 0.12, "theta": -0.06}
    pos["legs"][0]["greeks_source"] = "alpaca_options"
    pos["legs"][0]["greeks_as_of"] = "2026-07-18T14:30:00Z"
    pos["legs"][0]["greeks_status"] = "populated_at_stage"
    pos["legs"][1]["greeks"] = {"delta": 0.40, "gamma": 0.02, "vega": 0.09, "theta": -0.04}
    pos["legs"][1]["greeks_source"] = "alpaca_options"
    pos["legs"][1]["greeks_as_of"] = "2026-07-18T14:30:00Z"
    pos["legs"][1]["greeks_status"] = "populated_at_stage"
    return pos


class TestCanonicalGreeksWiring(unittest.TestCase):
    """4A: the persisted #1259 stage greeks flow into the canonical consumer,
    signed EXACTLY ONCE by aggregate_greeks, carried as typed provenance,
    observe-only — no cap armed, no threshold/monitor change."""

    EQUITY = 100000.0

    # ── normalize_position auto-sources the leg's own jsonb greeks ──────────

    def test_normalize_position_auto_sources_persisted_leg_greeks(self):
        pos = _persisted_short_put_vertical()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": -0.30, "gamma": 0.02, "vega": 0.10, "theta": -0.05}
            leg["greeks_source"] = "alpaca_options"
            leg["greeks_as_of"] = "2026-07-18T14:30:00Z"
            leg["greeks_status"] = "populated_at_stage"

        canonical = normalize_position(pos)
        # GREEKS_NOT_PERSISTED cleared because the legs now carry them.
        self.assertNotIn(
            IncompletenessReason.GREEKS_NOT_PERSISTED, canonical.completeness.reasons
        )
        self.assertEqual(canonical.completeness.missing_greek_legs, ())

        exposure = aggregate_greeks(canonical)
        self.assertTrue(exposure.complete)
        self.assertEqual(exposure.legs_total, 2)
        self.assertEqual(exposure.legs_with_greeks, 2)
        self.assertEqual(exposure.sources, ("alpaca_options",))
        self.assertEqual(exposure.as_of, ("2026-07-18T14:30:00Z",))

    def test_leg_greeks_from_persisted_preserves_raw_unsigned(self):
        """The helper keeps greeks RAW/UNSIGNED — a short leg is NOT pre-signed."""
        raw = {
            "symbol": _occ("SPY", "P", 100.0),
            "action": "sell",  # short
            "greeks": {"delta": -0.40, "gamma": 0.02, "vega": 0.10, "theta": -0.05},
            "greeks_source": "alpaca_options",
            "greeks_as_of": "2026-07-18T14:30:00Z",
            "greeks_status": "populated_at_stage",
        }
        lg = leg_greeks_from_persisted(raw)
        self.assertIsNotNone(lg)
        # RAW: the -0.40 is unchanged; the short sign is NOT applied here.
        self.assertAlmostEqual(lg.delta, -0.40, places=4)
        self.assertEqual(lg.source, "alpaca_options")
        self.assertEqual(lg.status, "populated_at_stage")

    def test_partial_persisted_greeks_type_unavailable_not_zero(self):
        pos = _persisted_short_put_vertical()
        pos["legs"][0]["greeks"] = {"delta": -0.30}  # gamma/vega/theta absent
        # leg1 has no greeks at all
        canonical = normalize_position(pos)
        exposure = aggregate_greeks(canonical)
        self.assertFalse(exposure.complete)
        self.assertIsNone(exposure.delta_dollars_per_underlying_point)
        self.assertIn(
            IncompletenessReason.GREEKS_NOT_PERSISTED, canonical.completeness.reasons
        )
        self.assertIsNone(leg_greeks_from_persisted(pos["legs"][0]))

    def test_explicit_override_wins_over_persisted_leg_jsonb(self):
        pos = _persisted_short_put_vertical()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": 9.99, "gamma": 9.99, "vega": 9.99, "theta": 9.99}
        override = {
            _occ("SPY", "P", 100.0): _g(delta=-0.30, gamma=0.02, vega=0.10, theta=-0.05),
            _occ("SPY", "P", 95.0): _g(delta=-0.20, gamma=0.01, vega=0.08, theta=-0.03),
        }
        canonical = normalize_position(pos, greeks_by_symbol=override)
        exposure = aggregate_greeks(canonical)
        # structure_quantity 2: (-1*2*100*-0.30) + (+1*2*100*-0.20) = 60 - 40 = 20
        # The 9.99 leg-jsonb values would have given a very different number.
        self.assertAlmostEqual(exposure.delta_dollars_per_underlying_point, 20.0, places=2)

    # ── end-to-end route through check_all_envelopes → canonical_greeks ─────

    def test_route_vertical_flows_to_signed_canonical_aggregate(self):
        pos = _persisted_short_put_vertical()  # sell 100P / buy 95P, qty -2
        pos["legs"][0]["greeks"] = {"delta": -0.40, "gamma": 0.02, "vega": 0.10, "theta": -0.05}
        pos["legs"][0]["greeks_source"] = "alpaca_options"
        pos["legs"][0]["greeks_status"] = "populated_at_stage"
        pos["legs"][1]["greeks"] = {"delta": -0.25, "gamma": 0.01, "vega": 0.08, "theta": -0.03}
        pos["legs"][1]["greeks_source"] = "alpaca_options"
        pos["legs"][1]["greeks_status"] = "populated_at_stage"

        result = check_all_envelopes([pos], equity=self.EQUITY, config=_permissive_config())
        cg = result.canonical_greeks

        # structure_quantity 2; short leg's -0.40 is signed +80, long leg's -0.25 is -50.
        self.assertAlmostEqual(cg["delta"], 30.0, places=2)
        self.assertAlmostEqual(cg["gamma"], -2.0, places=2)
        self.assertAlmostEqual(cg["vega"], -4.0, places=2)
        self.assertAlmostEqual(cg["theta"], 4.0, places=2)
        self.assertTrue(cg["complete"])
        self.assertEqual(cg["legs_with_greeks"], 2)
        self.assertEqual(cg["sources"], ["alpaca_options"])

    def test_route_sign_applied_exactly_once(self):
        """qty>1 debit: the signed aggregate is scaled ONCE — not doubled, not
        unsigned. Any double-qty (180) or unsigned-add (300) would show here."""
        result = check_all_envelopes(
            [_persisted_debit_qty3_with_greeks()], equity=self.EQUITY,
            config=_permissive_config(),
        )
        cg = result.canonical_greeks
        # +1*3*100*0.60 + -1*3*100*0.40 = 180 - 120 = 60
        self.assertAlmostEqual(cg["delta"], 60.0, places=2)
        self.assertNotAlmostEqual(cg["delta"], 180.0, places=2)  # double-qty phantom
        self.assertNotAlmostEqual(cg["delta"], 300.0, places=2)  # unsigned-add phantom
        self.assertTrue(cg["complete"])

    def test_route_condor_four_legs_signed(self):
        pos = _persisted_iron_condor()  # sell650P / buy645P / sell765C / buy770C, qty -1
        deltas = {650.0: -0.40, 645.0: -0.10, 765.0: 0.20, 770.0: 0.05}
        for leg in pos["legs"]:
            leg["greeks"] = {
                "delta": deltas[leg["strike"]],
                "gamma": 0.01, "vega": 0.05, "theta": -0.02,
            }
            leg["greeks_source"] = "alpaca_options"
        result = check_all_envelopes([pos], equity=self.EQUITY, config=_permissive_config())
        cg = result.canonical_greeks
        # (-1*100*-0.40)+(+1*100*-0.10)+(-1*100*0.20)+(+1*100*0.05) = 40-10-20+5 = 15
        self.assertAlmostEqual(cg["delta"], 15.0, places=2)
        self.assertTrue(cg["complete"])
        self.assertEqual(cg["legs_with_greeks"], 4)

    def test_route_greeksless_historical_position_incomplete_and_stress_unchanged(self):
        """A greeks-less (pre-#1259) position: the canonical aggregate is typed
        unavailable AND the payoff-capped stress path is byte-identical."""
        pos = _persisted_short_put_vertical()  # no greeks on legs
        result = check_all_envelopes([pos], equity=self.EQUITY, config=_permissive_config())
        cg = result.canonical_greeks
        self.assertFalse(cg["complete"])
        self.assertIsNone(cg["delta"])
        self.assertEqual(cg["legs_with_greeks"], 0)
        # Stress behavior unchanged: the greek scenarios stay typed-unavailable.
        self.assertNotIn("spy_down", result.stress_results)
        self.assertEqual(
            result.stress_unavailable["spy_down"],
            {"reason": "greeks_missing", "missing_field": "delta", "legs_missing": 2},
        )

    def test_route_dark_leg_makes_canonical_aggregate_incomplete(self):
        """One leg dark (greeks=None, typed unavailable at stage) → complete False."""
        pos = _persisted_short_put_vertical()
        pos["legs"][0]["greeks"] = {"delta": -0.40, "gamma": 0.02, "vega": 0.10, "theta": -0.05}
        pos["legs"][0]["greeks_status"] = "populated_at_stage"
        pos["legs"][1]["greeks"] = None
        pos["legs"][1]["greeks_status"] = "unavailable_at_stage"
        result = check_all_envelopes([pos], equity=self.EQUITY, config=_permissive_config())
        cg = result.canonical_greeks
        self.assertFalse(cg["complete"])
        self.assertIsNone(cg["delta"])
        self.assertIn(_occ("SPY", "P", 95.0), cg["missing_legs"])
        self.assertEqual(cg["legs_with_greeks"], 1)

    def test_route_observe_only_no_violation_and_json_serializable(self):
        """canonical_greeks arms nothing: caps default 0, no greek violation, and
        the serialized result stays JSON-safe."""
        import json
        pos = _persisted_short_put_vertical()
        for leg in pos["legs"]:
            leg["greeks"] = {"delta": 9.99, "gamma": 9.99, "vega": 9.99, "theta": 9.99}
            leg["greeks_source"] = "alpaca_options"
        result = check_all_envelopes([pos], equity=self.EQUITY, config=_permissive_config())
        # Huge signed exposure, zero greek violations (caps dormant).
        self.assertEqual(
            [v for v in result.violations if v.envelope.startswith("greeks_")], []
        )
        as_dict = result.to_dict()
        self.assertIn("canonical_greeks", as_dict)
        json.dumps(as_dict)  # must not raise

    def test_aggregate_canonical_greeks_never_raises_on_unrepresentable(self):
        """A structure that cannot be normalized (no legs) flags the book
        incomplete — the observe-only aggregate never raises."""
        malformed = {"id": "no-legs", "quantity": -2, "avg_entry_price": 1.20}
        cg = aggregate_canonical_greeks([malformed])
        self.assertFalse(cg["complete"])
        self.assertIsNone(cg["delta"])
        self.assertEqual(cg["unrepresentable_structures"], 1)


if __name__ == "__main__":
    unittest.main()
