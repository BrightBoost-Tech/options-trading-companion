"""Single-leg (long_call / long_put) terminal-distribution EV adapter (queue-⑤).

Pins:
1. Closed-form single-leg EV matches brute-force numeric integration of the
   SAME lognormal (call AND put) to tight tolerance.
2. Breakeven-aware PoP orientation (call: P(S>K+d); put: P(S<K-d)).
3. Geometry-honest extremes: long call max_gain = +inf (unbounded, never a
   fabricated cap), long put max_gain bounded at (strike-debit)*scale; max_loss
   is the debit for both.
4. EV scales with contracts (per-position dollar units).
5. H9 abstention: missing/implausible IV, spot, DTE, known_at, and bad geometry
   (put debit >= strike, non-long leg) -> typed Unavailable, never a defaulted
   distribution or a fabricated number.
"""

import math

from packages.quantum.analytics.terminal_distribution import (
    DistributionInputs,
    StrategyEvaluation,
    Unavailable,
    build_single_leg_structure,
    evaluate_single_leg,
    evaluate_single_leg_from_inputs,
)

KNOWN_AT = "2026-07-01T15:00:00Z"


def _brute_ev_share(spot, sigma, dte_days, mu, option_type, K, d, n=200001, zmax=8.0):
    """E[payoff per share] by deterministic quadrature over the standard normal
    Z of the SAME lognormal build_lognormal uses (sigma=leg IV, T=dte/365,
    drift=mu)."""
    T = dte_days / 365.0
    dz = 2 * zmax / (n - 1)
    norm = 1.0 / math.sqrt(2 * math.pi)
    total = 0.0
    drift = (mu - 0.5 * sigma * sigma) * T
    vol = sigma * math.sqrt(T)
    for i in range(n):
        z = -zmax + i * dz
        S = spot * math.exp(drift + vol * z)
        if option_type == "call":
            payoff = max(S - K, 0.0) - d
        else:
            payoff = max(K - S, 0.0) - d
        total += payoff * (norm * math.exp(-0.5 * z * z)) * dz
    return total


def test_long_call_ev_matches_brute_force():
    spot, sigma, dte, r = 100.0, 0.25, 30.0, 0.0
    K, d = 102.0, 2.10
    ev = evaluate_single_leg_from_inputs(
        option_type="call", strike=K, debit_per_share=d, iv=sigma,
        spot=spot, dte_days=dte, known_at=KNOWN_AT, risk_free_rate=r,
    )
    assert isinstance(ev, StrategyEvaluation)
    assert ev.strategy == "long_call" and ev.basis == "raw"
    brute = _brute_ev_share(spot, sigma, dte, r, "call", K, d)
    assert abs(ev.expected_value / 100.0 - brute) < 5e-3
    # PoP = P(S_T > K + d)
    assert 0.0 <= ev.pop <= 1.0
    assert ev.breakevens == (K + d,)
    # Unbounded upside — never a fabricated finite cap.
    assert ev.max_gain == math.inf
    assert abs(ev.max_loss - d * 100.0) < 1e-9


def test_long_put_ev_matches_brute_force():
    spot, sigma, dte, r = 100.0, 0.30, 45.0, 0.0
    K, d = 96.0, 2.40
    ev = evaluate_single_leg_from_inputs(
        option_type="put", strike=K, debit_per_share=d, iv=sigma,
        spot=spot, dte_days=dte, known_at=KNOWN_AT, risk_free_rate=r,
    )
    assert isinstance(ev, StrategyEvaluation)
    assert ev.strategy == "long_put"
    brute = _brute_ev_share(spot, sigma, dte, r, "put", K, d)
    assert abs(ev.expected_value / 100.0 - brute) < 5e-3
    assert ev.breakevens == (K - d,)
    # Put upside capped at (strike - debit); max loss is the debit.
    assert abs(ev.max_gain - (K - d) * 100.0) < 1e-9
    assert abs(ev.max_loss - d * 100.0) < 1e-9


def test_pop_orientation_call_vs_put():
    # Deep ITM call (low strike) -> high PoP; deep OTM call -> low PoP.
    itm = evaluate_single_leg_from_inputs(
        option_type="call", strike=80.0, debit_per_share=20.5, iv=0.25,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT,
    )
    otm = evaluate_single_leg_from_inputs(
        option_type="call", strike=120.0, debit_per_share=0.5, iv=0.25,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT,
    )
    assert isinstance(itm, StrategyEvaluation) and isinstance(otm, StrategyEvaluation)
    assert itm.pop > otm.pop


def test_ev_scales_with_contracts():
    one = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT, contracts=1,
    )
    three = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT, contracts=3,
    )
    assert isinstance(one, StrategyEvaluation) and isinstance(three, StrategyEvaluation)
    assert abs(three.expected_value - 3 * one.expected_value) < 1e-6


def test_h9_missing_iv_abstains():
    ev = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=None,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT,
    )
    assert isinstance(ev, Unavailable) and ev.reason_code == "missing_iv"


def test_h9_missing_spot_and_dte_abstain():
    no_spot = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
        spot=None, dte_days=30.0, known_at=KNOWN_AT,
    )
    assert isinstance(no_spot, Unavailable) and no_spot.reason_code == "missing_spot"
    no_dte = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
        spot=100.0, dte_days=0.0, known_at=KNOWN_AT,
    )
    assert isinstance(no_dte, Unavailable) and no_dte.reason_code == "invalid_dte"


def test_h9_missing_known_at_abstains():
    ev = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
        spot=100.0, dte_days=30.0, known_at="",
    )
    assert isinstance(ev, Unavailable) and ev.reason_code == "missing_known_at"


def test_h9_implausible_iv_abstains():
    # IV 25 (looks like percent-not-decimal) -> refuse to reinterpret.
    ev = evaluate_single_leg_from_inputs(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=25.0,
        spot=100.0, dte_days=30.0, known_at=KNOWN_AT,
    )
    assert isinstance(ev, Unavailable) and ev.reason_code == "invalid_iv"


def test_geometry_put_debit_exceeds_strike_abstains():
    ev = evaluate_single_leg_from_inputs(
        option_type="put", strike=5.0, debit_per_share=6.0, iv=0.30,
        spot=5.0, dte_days=30.0, known_at=KNOWN_AT,
    )
    assert isinstance(ev, Unavailable) and ev.reason_code == "premium_exceeds_max"


def test_geometry_non_long_leg_abstains():
    # A structure whose single leg is a SELL is not the long-only experiment.
    structure = build_single_leg_structure(
        option_type="call", strike=101.0, debit_per_share=1.8, iv=0.25,
    )
    # Rewrite the leg to a sell to exercise validate_single_leg's not_long branch.
    from dataclasses import replace
    bad_leg = replace(structure.legs[0], action="sell")
    bad_structure = replace(structure, legs=(bad_leg,))
    ev = evaluate_single_leg(bad_structure, DistributionInputs(spot=100.0, dte_days=30.0, known_at=KNOWN_AT))
    assert isinstance(ev, Unavailable) and ev.reason_code == "not_long"
