"""Single-leg (long_call / long_put) terminal-distribution EV adapter.

The one-contract shadow-only single-leg EXPERIMENT (owner decision
SINGLE_LEG=ONE_CONTRACT_SHADOW_ONLY_EXPERIMENT) needs an INDEPENDENT EV
estimate for a long option — the same queue-⑤ challenger distribution the
verticals/condors are scored against, applied to a one-leg payoff the shared
``payoff.integrate_structure`` deliberately does not enumerate (it prices only
the three DEFINED-RISK structures, and its max-gain knot logic assumes a
bounded payoff — a long call's upside is unbounded).

This adapter therefore:
  1. builds the v1 lognormal challenger (``build_lognormal``) — REUSING its H9
     abstention verbatim (missing/implausible IV, spot, DTE, known_at ->
     typed ``Unavailable``, never a defaulted distribution), and
  2. integrates the exact single-leg payoff in closed form against that
     distribution's ``cdf`` / ``partial_expectation`` (the identical exactness
     the vertical/condor integrator uses), and
  3. reports geometry-honest extremes: a long call's max gain is UNBOUNDED
     (``math.inf`` — never a fabricated finite cap), a long put's is capped at
     ``(strike - debit)`` (spot floors at 0); max loss is the debit for both.

OBSERVE-ONLY: like the rest of this package, nothing in the live economics
path imports it (the import-lock test enforces the negative). The single-leg
EXPERIMENT generator consumes this adapter ONLY through an INJECTED estimator
(dependency injection) so the generator source never references this package —
the wiring is exercised in tests, and the experiment ships dark.

Output units match production ``calculate_ev``: dollars per position
(per-share x 100 x contracts). ``basis`` is "raw" — no calibration here.
"""

from __future__ import annotations

import math
from typing import Optional, Union

from packages.quantum.analytics.terminal_distribution.challenger_lognormal import (
    MODEL_NAME,
    build_lognormal,
)
from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    DistributionInputs,
    EvalOutcome,
    LegSpec,
    OptionType,
    Provenance,
    StrategyEvaluation,
    StructureSpec,
    TerminalDistribution,
    Unavailable,
    params_hash,
    structure_params,
    validate_single_leg,
)

SINGLE_LEG_SOURCE = "single_leg_adapter"
SINGLE_LEG_VERSION = f"single_leg@{CONTRACT_VERSION}"


def _cdf_checked(dist: TerminalDistribution, k: Optional[float], source: str) -> Union[float, Unavailable]:
    """Query CDF (k=None -> total mass 1.0) and refuse non-probability output
    (mirrors payoff._cdf_checked — the same H9 distribution-error guard)."""
    if k is None:
        return 1.0
    value = dist.cdf(k)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < -1e-9 or value > 1.0 + 1e-9:
        return Unavailable(
            "distribution_error",
            f"cdf({k}) returned non-probability {value!r} from {dist.provenance.source}",
            source,
        )
    return min(1.0, max(0.0, float(value)))


def _pe_checked(dist: TerminalDistribution, lo: Optional[float], hi: Optional[float], source: str) -> Union[float, Unavailable]:
    pe = dist.partial_expectation(lo, hi)
    if not isinstance(pe, (int, float)) or not math.isfinite(pe) or pe < -1e-9:
        return Unavailable(
            "distribution_error",
            f"partial_expectation({lo}, {hi}) returned {pe!r}",
            source,
        )
    return max(0.0, float(pe))


def build_single_leg_structure(
    *,
    option_type: OptionType,
    strike: float,
    debit_per_share: float,
    iv: Optional[float],
    delta: Optional[float] = None,
    contracts: int = 1,
) -> StructureSpec:
    """Typed one-leg StructureSpec for a long option (buy premium).

    ``debit_per_share`` is the per-share debit PAID (positive), mirroring the
    production ``calculate_ev(premium=...)`` convention (net_premium is always
    positive; its meaning follows the strategy — debit paid for a long option).
    """
    strategy = "long_call" if option_type == "call" else "long_put"
    leg = LegSpec(action="buy", option_type=option_type, strike=strike, iv=iv, delta=delta)
    return StructureSpec(strategy=strategy, legs=(leg,), net_premium=debit_per_share, contracts=contracts)


def evaluate_single_leg(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs],
) -> EvalOutcome:
    """End-to-end single-leg challenger evaluation: build the v1 lognormal (or
    abstain), validate the one-leg geometry (or abstain), then exact closed-form
    payoff integration. Emits ``basis="raw"`` only; H9 abstention everywhere a
    value cannot be honestly priced."""
    source = SINGLE_LEG_SOURCE

    geom = validate_single_leg(structure, source)
    if isinstance(geom, Unavailable):
        return geom

    dist = build_lognormal(structure, inputs)
    if isinstance(dist, Unavailable):
        return dist

    k = geom.strike
    d = structure.net_premium  # per-share debit paid (> 0, validated)

    f_k = _cdf_checked(dist, k, source)
    if isinstance(f_k, Unavailable):
        return f_k

    if geom.option_type == "call":
        # Payoff/share: S<=K -> -d ; S>K -> (S-K)-d.
        # Segments: (0,K] alpha=-d beta=0 ; (K,inf) alpha=-K-d beta=1.
        pe_tail = _pe_checked(dist, k, None, source)
        if isinstance(pe_tail, Unavailable):
            return pe_tail
        ev_share = (-d) * f_k + (-k - d) * (1.0 - f_k) + pe_tail
        breakeven = k + d
        # PoP = P(S_T > breakeven) = 1 - cdf(breakeven).
        f_be = _cdf_checked(dist, breakeven, source)
        if isinstance(f_be, Unavailable):
            return f_be
        pop = 1.0 - f_be
        max_gain_share = math.inf   # unbounded upside — never a fabricated cap
        max_loss_share = d
    else:  # put
        # Payoff/share: S<K -> (K-S)-d ; S>=K -> -d.
        # Segments: (0,K] alpha=K-d beta=-1 ; (K,inf) alpha=-d beta=0.
        pe_body = _pe_checked(dist, None, k, source)
        if isinstance(pe_body, Unavailable):
            return pe_body
        ev_share = (k - d) * f_k - pe_body + (-d) * (1.0 - f_k)
        breakeven = k - d
        # PoP = P(S_T < breakeven) = cdf(breakeven).
        f_be = _cdf_checked(dist, breakeven, source)
        if isinstance(f_be, Unavailable):
            return f_be
        pop = f_be
        max_gain_share = k - d      # capped: spot floors at 0
        max_loss_share = d

    scale = 100.0 * structure.contracts
    prov = Provenance(
        source=source,
        version=f"{SINGLE_LEG_VERSION}|{dist.provenance.source}@{dist.provenance.version}",
        params_hash=params_hash(
            {
                "distribution": dist.provenance.params_hash,
                "structure": structure_params(structure),
            }
        ),
    )
    return StrategyEvaluation(
        strategy=structure.strategy,
        model=MODEL_NAME,
        pop=max(0.0, min(1.0, pop)),
        expected_value=ev_share * scale,
        basis="raw",
        max_gain=(math.inf if max_gain_share == math.inf else max_gain_share * scale),
        max_loss=max_loss_share * scale,
        breakevens=(breakeven,),
        provenance=prov,
    )


def evaluate_single_leg_from_inputs(
    *,
    option_type: OptionType,
    strike: float,
    debit_per_share: float,
    iv: Optional[float],
    spot: Optional[float],
    dte_days: Optional[float],
    known_at: str,
    risk_free_rate: float = 0.0,
    contracts: int = 1,
) -> EvalOutcome:
    """Convenience: build the structure + DistributionInputs from primitives and
    evaluate. This is the exact call shape a generator's injected EV estimator
    uses (the generator itself never imports this package — DI keeps the
    import-lock intact)."""
    structure = build_single_leg_structure(
        option_type=option_type,
        strike=strike,
        debit_per_share=debit_per_share,
        iv=iv,
        contracts=contracts,
    )
    inputs = DistributionInputs(
        spot=spot, dte_days=dte_days, known_at=known_at, risk_free_rate=risk_free_rate
    )
    return evaluate_single_leg(structure, inputs)
