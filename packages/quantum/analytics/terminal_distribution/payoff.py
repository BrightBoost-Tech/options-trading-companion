"""Common payoff integration over ANY TerminalDistribution.

Expiry payoffs of defined-risk verticals and iron condors are piecewise-LINEAR
in S_T. For any distribution exposing ``cdf`` (P(S_T <= k)) and
``partial_expectation`` (E[S_T * 1{lo < S_T <= hi}]), the expected payoff is
EXACT in closed form:

    payoff(S) = alpha + beta * S    on each segment (lo, hi]
    E[payoff] = sum over segments: alpha * (F(hi) - F(lo)) + beta * PE(lo, hi)

No quadrature, no sampling — deterministic to machine precision given the
distribution. PoP is breakeven-aware and call/put-aware: it is computed from
CDF queries AT THE BREAKEVENS (not at the strikes, not from deltas), with the
profitable side chosen by structure orientation.

This module fabricates nothing: a structure whose labeled strategy contradicts
its leg geometry (e.g. a "credit" call vertical shorting the HIGHER strike) is
a typed ``Unavailable``; a distribution that returns non-finite or out-of-range
CDF mass is a typed ``Unavailable`` ("distribution_error"), never clamped into
a plausible-looking number (H9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    EvalOutcome,
    Provenance,
    StrategyEvaluation,
    StructureSpec,
    TerminalDistribution,
    Unavailable,
    params_hash,
    structure_params,
    validate_condor,
    validate_vertical,
)

INTEGRATOR_VERSION = f"payoff@{CONTRACT_VERSION}"


@dataclass(frozen=True)
class _Segment:
    """Per-share payoff alpha + beta*S on (lo, hi]; hi=None means +inf."""

    lo: float
    hi: Optional[float]
    alpha: float
    beta: float


def _vertical_segments(
    structure: StructureSpec, source: str
) -> Union[Tuple[List[_Segment], Tuple[float, ...], str], Unavailable]:
    """Build payoff segments + breakevens + profit-side tag for a vertical.

    Returns (segments, breakevens, pop_side) where pop_side is "below"
    (profit when S_T <= BE), "above", or for condors "between"."""
    geom = validate_vertical(structure, source)
    if isinstance(geom, Unavailable):
        return geom
    prem = structure.net_premium
    k_long, k_short = geom.long_leg.strike, geom.short_leg.strike

    if structure.strategy == "credit_vertical":
        if geom.option_type == "call":
            # Short lower call, long higher call, collect credit.
            if not k_short < k_long:
                return Unavailable(
                    "strategy_geometry_mismatch",
                    "credit call vertical must short the LOWER strike",
                    source,
                )
            k1, k2 = k_short, k_long
            segments = [
                _Segment(0.0, k1, prem, 0.0),
                _Segment(k1, k2, prem + k1, -1.0),
                _Segment(k2, None, prem - (k2 - k1), 0.0),
            ]
            return segments, (k1 + prem,), "below"
        else:
            # Short higher put, long lower put, collect credit.
            if not k_short > k_long:
                return Unavailable(
                    "strategy_geometry_mismatch",
                    "credit put vertical must short the HIGHER strike",
                    source,
                )
            k1, k2 = k_long, k_short
            segments = [
                _Segment(0.0, k1, prem - (k2 - k1), 0.0),
                _Segment(k1, k2, prem - k2, 1.0),
                _Segment(k2, None, prem, 0.0),
            ]
            return segments, (k2 - prem,), "above"

    # debit_vertical
    if geom.option_type == "call":
        # Long lower call, short higher call, pay debit.
        if not k_long < k_short:
            return Unavailable(
                "strategy_geometry_mismatch",
                "debit call vertical must buy the LOWER strike",
                source,
            )
        k1, k2 = k_long, k_short
        segments = [
            _Segment(0.0, k1, -prem, 0.0),
            _Segment(k1, k2, -k1 - prem, 1.0),
            _Segment(k2, None, (k2 - k1) - prem, 0.0),
        ]
        return segments, (k1 + prem,), "above"
    else:
        # Long higher put, short lower put, pay debit.
        if not k_long > k_short:
            return Unavailable(
                "strategy_geometry_mismatch",
                "debit put vertical must buy the HIGHER strike",
                source,
            )
        k1, k2 = k_short, k_long
        segments = [
            _Segment(0.0, k1, (k2 - k1) - prem, 0.0),
            _Segment(k1, k2, k2 - prem, -1.0),
            _Segment(k2, None, -prem, 0.0),
        ]
        return segments, (k2 - prem,), "below"


def _condor_segments(
    structure: StructureSpec, source: str
) -> Union[Tuple[List[_Segment], Tuple[float, ...], str], Unavailable]:
    geom = validate_condor(structure, source)
    if isinstance(geom, Unavailable):
        return geom
    c = structure.net_premium
    lp, sp = geom.long_put.strike, geom.short_put.strike
    sc, lc = geom.short_call.strike, geom.long_call.strike
    segments = [
        _Segment(0.0, lp, c - geom.width_put, 0.0),
        _Segment(lp, sp, c - sp, 1.0),
        _Segment(sp, sc, c, 0.0),
        _Segment(sc, lc, c + sc, -1.0),
        _Segment(lc, None, c - geom.width_call, 0.0),
    ]
    return segments, (sp - c, sc + c), "between"


def _cdf_checked(dist: TerminalDistribution, k: Optional[float], source: str) -> Union[float, Unavailable]:
    """Query CDF (k=None -> total mass 1.0) and refuse non-probability output."""
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


def integrate_structure(
    dist: TerminalDistribution,
    structure: StructureSpec,
    *,
    model: Optional[str] = None,
) -> EvalOutcome:
    """Exact expected payoff + breakeven-aware PoP for a structure under ``dist``.

    Output units match production ``calculate_ev``: dollars per position
    (per-share x 100 x contracts). ``basis`` is "raw" — this layer never
    applies calibration."""
    source = "payoff_integrator"
    if structure.strategy == "iron_condor":
        built = _condor_segments(structure, source)
    elif structure.strategy in ("credit_vertical", "debit_vertical"):
        built = _vertical_segments(structure, source)
    else:
        return Unavailable("wrong_strategy", f"unsupported strategy {structure.strategy!r}", source)
    if isinstance(built, Unavailable):
        return built
    segments, breakevens, pop_side = built

    # Exact EV: sum alpha*(F(hi)-F(lo)) + beta*PE(lo,hi) over segments.
    ev_share = 0.0
    for seg in segments:
        f_lo = _cdf_checked(dist, seg.lo, source)
        if isinstance(f_lo, Unavailable):
            return f_lo
        f_hi = _cdf_checked(dist, seg.hi, source)
        if isinstance(f_hi, Unavailable):
            return f_hi
        mass = f_hi - f_lo
        if mass < -1e-9:
            return Unavailable(
                "distribution_error",
                f"cdf not monotone on ({seg.lo}, {seg.hi}]: mass={mass}",
                source,
            )
        contribution = seg.alpha * max(0.0, mass)
        if seg.beta != 0.0:
            pe = dist.partial_expectation(seg.lo, seg.hi)
            if not isinstance(pe, (int, float)) or not math.isfinite(pe) or pe < -1e-9:
                return Unavailable(
                    "distribution_error",
                    f"partial_expectation({seg.lo}, {seg.hi}) returned {pe!r}",
                    source,
                )
            contribution += seg.beta * max(0.0, float(pe))
        ev_share += contribution

    # Breakeven-aware PoP from CDF queries at the breakevens.
    if pop_side == "below":
        p = _cdf_checked(dist, breakevens[0], source)
        if isinstance(p, Unavailable):
            return p
        pop = p
    elif pop_side == "above":
        p = _cdf_checked(dist, breakevens[0], source)
        if isinstance(p, Unavailable):
            return p
        pop = 1.0 - p
    else:  # between (condor)
        p_low = _cdf_checked(dist, breakevens[0], source)
        if isinstance(p_low, Unavailable):
            return p_low
        p_high = _cdf_checked(dist, breakevens[1], source)
        if isinstance(p_high, Unavailable):
            return p_high
        pop = max(0.0, p_high - p_low)

    # Geometry-exact max gain/loss (per share), then production units.
    per_share_payoffs = [s.alpha for s in segments if s.beta == 0.0]
    # Linear segments attain extremes at their knots — include knot values.
    for s in segments:
        if s.beta != 0.0:
            per_share_payoffs.append(s.alpha + s.beta * s.lo)
            if s.hi is not None:
                per_share_payoffs.append(s.alpha + s.beta * s.hi)
    max_gain_share = max(per_share_payoffs)
    max_loss_share = -min(per_share_payoffs)

    scale = 100.0 * structure.contracts
    model_name = model or f"payoff_integral[{dist.provenance.source}]"
    prov = Provenance(
        source=source,
        version=f"{INTEGRATOR_VERSION}|{dist.provenance.source}@{dist.provenance.version}",
        params_hash=params_hash(
            {
                "distribution": dist.provenance.params_hash,
                "structure": structure_params(structure),
            }
        ),
    )
    return StrategyEvaluation(
        strategy=structure.strategy,
        model=model_name,
        pop=pop,
        expected_value=ev_share * scale,
        basis="raw",
        max_gain=max_gain_share * scale,
        max_loss=max_loss_share * scale,
        breakevens=breakevens,
        provenance=prov,
    )
