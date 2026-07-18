"""Versioned terminal-distribution contract (queue-⑤ observe-only foundation).

One typed vocabulary for every probability/EV source in this package:

- ``TerminalDistribution`` — the protocol a distribution must satisfy:
  ``cdf(k)`` = P(S_T <= k) and ``partial_expectation(lo, hi)`` =
  E[S_T * 1{lo < S_T <= hi}]. Both together make piecewise-linear option
  payoffs EXACTLY integrable in closed form (see payoff.py).
- ``StructureSpec`` / ``LegSpec`` / ``DistributionInputs`` — typed inputs with
  ``known_at`` (as-of timestamp) so a prequential evaluation can never peek.
- ``StrategyEvaluation`` — typed output: per-strategy PoP + EV with an explicit
  ``basis`` label. THIS LAYER EMITS ``basis="raw"`` ONLY. A "calibrated" basis
  exists only inside the evaluator, produced by applying a production
  multiplier READ-ONLY (evaluator.with_production_multipliers) — raw and
  calibrated are kept as SEPARATE result objects, never overwritten.
- ``Unavailable`` — typed abstention. H9 both ends: a value we cannot price
  must REJECT or flag, never fabricate. Insufficient/malformed inputs return
  ``Unavailable``, never a neutral-0.5 or a default-IV guess (the dormant
  opportunity_scorer kernel's ``iv or 0.30`` / ``except: return 0.5`` habits
  are exactly what this contract forbids).
- ``Provenance`` — source + version + params_hash stamped on every result so
  any number in a report is traceable to the model and inputs that made it.

Version discipline: CONTRACT_VERSION is bumped on any breaking change to the
shapes below; provenance carries it so mixed-version fixture sets are
detectable instead of silently comparable.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

CONTRACT_VERSION = "1.0.0"

Basis = Literal["raw", "calibrated"]
StrategyName = Literal["credit_vertical", "debit_vertical", "iron_condor"]
OptionType = Literal["call", "put"]
Action = Literal["buy", "sell"]


def params_hash(params: Dict[str, Any]) -> str:
    """Deterministic short hash of a parameter dict (sorted-key canonical JSON).

    Used for provenance only — never for equality of economics. ``default=str``
    keeps it total over exotic values without fabricating precision.
    """
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Provenance:
    """Where a number came from: source module/model, version, input hash."""

    source: str
    version: str
    params_hash: str


@dataclass(frozen=True)
class LegSpec:
    """One option leg. ``iv``/``delta`` optional — models that need them must
    ABSTAIN (typed Unavailable) when absent, never default them."""

    action: Action
    option_type: OptionType
    strike: float
    iv: Optional[float] = None      # annualized decimal (0.25 = 25%)
    delta: Optional[float] = None   # raw signed or abs; consumers abs() like production


@dataclass(frozen=True)
class StructureSpec:
    """A defined-risk structure.

    ``net_premium`` is POSITIVE in both cases and its meaning follows the
    strategy: credit received per share for credit structures (credit_vertical,
    iron_condor), debit paid per share for debit_vertical. This mirrors the
    production ``calculate_ev(premium=...)`` convention.
    """

    strategy: StrategyName
    legs: Tuple[LegSpec, ...]
    net_premium: float
    contracts: int = 1


@dataclass(frozen=True)
class DistributionInputs:
    """Market inputs for building a terminal distribution, stamped ``known_at``
    (ISO-8601) — the as-of moment; prequential evaluation orders on it."""

    spot: Optional[float]
    dte_days: Optional[float]
    known_at: str
    risk_free_rate: float = 0.0


@dataclass(frozen=True)
class Unavailable:
    """Typed abstention (H9): the model cannot honestly price these inputs.

    ``reason_code`` is a stable machine token (e.g. ``missing_iv``,
    ``invalid_width``); ``detail`` is human context; ``source`` names the
    abstaining model/adapter.
    """

    reason_code: str
    detail: str
    source: str


@dataclass(frozen=True)
class StrategyEvaluation:
    """Typed per-strategy output. EV/max_gain/max_loss are DOLLARS PER POSITION
    (per-share x 100 x contracts — production ``calculate_ev`` units).

    ``basis`` is "raw" everywhere in this package; "calibrated" appears only on
    evaluator-side copies produced by read-only application of a production
    multiplier. ``known_defects`` keeps baseline defects VISIBLE on the result
    itself (the credit fair-odds EV==0 identity rides here, never hidden).
    """

    strategy: StrategyName
    model: str
    pop: float
    expected_value: float
    basis: Basis
    max_gain: float
    max_loss: float
    breakevens: Tuple[float, ...]
    provenance: Provenance
    known_defects: Tuple[str, ...] = ()


EvalOutcome = Union[StrategyEvaluation, Unavailable]


@runtime_checkable
class TerminalDistribution(Protocol):
    """Protocol for a terminal (expiry) price distribution.

    cdf(k):
        P(S_T <= k). Must be monotone nondecreasing in k, 0 at k<=0 for a
        positive-support distribution, -> 1 as k -> inf.
    partial_expectation(lo, hi):
        E[S_T * 1{lo < S_T <= hi}]. ``lo=None`` means 0, ``hi=None`` means
        +inf; partial_expectation(None, None) must equal E[S_T]. With cdf this
        makes any piecewise-linear payoff exactly integrable.
    """

    provenance: Provenance

    def cdf(self, strike: float) -> float:  # pragma: no cover - protocol
        ...

    def partial_expectation(
        self, lo: Optional[float], hi: Optional[float]
    ) -> float:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# Shared structure validation (used by baselines AND payoff integration).
# Validation failures are typed Unavailable — never an exception for a
# malformed candidate, never a defaulted value.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerticalGeometry:
    """Validated vertical: long/short legs, width, option type."""

    long_leg: LegSpec
    short_leg: LegSpec
    width: float
    option_type: OptionType


@dataclass(frozen=True)
class CondorGeometry:
    """Validated iron condor: two shorts inside two longs, per-side widths."""

    short_put: LegSpec
    long_put: LegSpec
    short_call: LegSpec
    long_call: LegSpec
    width_put: float
    width_call: float


def _finite_pos(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def validate_vertical(structure: StructureSpec, source: str) -> Union[VerticalGeometry, Unavailable]:
    """Validate a 2-leg vertical: one buy + one sell, same option type, distinct
    finite strikes, finite positive premium strictly inside the width."""
    legs = structure.legs
    if len(legs) != 2:
        return Unavailable("wrong_leg_count", f"expected 2 legs, got {len(legs)}", source)
    buys = [l for l in legs if l.action == "buy"]
    sells = [l for l in legs if l.action == "sell"]
    if len(buys) != 1 or len(sells) != 1:
        return Unavailable("missing_legs", "vertical needs exactly one buy and one sell leg", source)
    long_leg, short_leg = buys[0], sells[0]
    if long_leg.option_type != short_leg.option_type:
        return Unavailable("mixed_option_types", "vertical legs must share option_type", source)
    if not _finite_pos(long_leg.strike) or not _finite_pos(short_leg.strike):
        return Unavailable("missing_strike", "vertical legs need finite positive strikes", source)
    width = abs(long_leg.strike - short_leg.strike)
    if width <= 0:
        return Unavailable("invalid_width", "vertical width must be > 0 (distinct strikes)", source)
    premium = structure.net_premium
    if not _finite_pos(premium):
        return Unavailable("invalid_premium", f"net_premium must be finite and > 0, got {premium!r}", source)
    if premium >= width:
        return Unavailable(
            "premium_exceeds_width",
            f"net_premium {premium} >= width {width} — impossible vertical geometry",
            source,
        )
    if structure.contracts < 1:
        return Unavailable("invalid_contracts", f"contracts must be >= 1, got {structure.contracts}", source)
    return VerticalGeometry(long_leg=long_leg, short_leg=short_leg, width=width, option_type=long_leg.option_type)


def validate_condor(structure: StructureSpec, source: str) -> Union[CondorGeometry, Unavailable]:
    """Validate a 4-leg iron condor: short put/call inside long put/call wings,
    finite strikes ordered long_put < short_put < short_call < long_call,
    credit strictly inside min(width_put, width_call)."""
    legs = structure.legs
    if len(legs) != 4:
        return Unavailable("wrong_leg_count", f"expected 4 legs, got {len(legs)}", source)
    puts = [l for l in legs if l.option_type == "put"]
    calls = [l for l in legs if l.option_type == "call"]
    if len(puts) != 2 or len(calls) != 2:
        return Unavailable("missing_legs", "condor needs exactly 2 puts and 2 calls", source)
    short_puts = [l for l in puts if l.action == "sell"]
    long_puts = [l for l in puts if l.action == "buy"]
    short_calls = [l for l in calls if l.action == "sell"]
    long_calls = [l for l in calls if l.action == "buy"]
    if len(short_puts) != 1 or len(long_puts) != 1 or len(short_calls) != 1 or len(long_calls) != 1:
        return Unavailable("missing_legs", "condor needs one short+long put and one short+long call", source)
    sp, lp, sc, lc = short_puts[0], long_puts[0], short_calls[0], long_calls[0]
    for leg in (sp, lp, sc, lc):
        if not _finite_pos(leg.strike):
            return Unavailable("missing_strike", "condor legs need finite positive strikes", source)
    if not (lp.strike < sp.strike < sc.strike < lc.strike):
        return Unavailable(
            "invalid_width",
            f"condor strikes must order long_put < short_put < short_call < long_call, got "
            f"{lp.strike}/{sp.strike}/{sc.strike}/{lc.strike}",
            source,
        )
    width_put = sp.strike - lp.strike
    width_call = lc.strike - sc.strike
    credit = structure.net_premium
    if not _finite_pos(credit):
        return Unavailable("invalid_premium", f"net_premium must be finite and > 0, got {credit!r}", source)
    if credit >= min(width_put, width_call):
        return Unavailable(
            "premium_exceeds_width",
            f"credit {credit} >= min side width {min(width_put, width_call)} — impossible condor geometry",
            source,
        )
    if structure.contracts < 1:
        return Unavailable("invalid_contracts", f"contracts must be >= 1, got {structure.contracts}", source)
    return CondorGeometry(
        short_put=sp, long_put=lp, short_call=sc, long_call=lc,
        width_put=width_put, width_call=width_call,
    )


def structure_params(structure: StructureSpec) -> Dict[str, Any]:
    """Canonical param dict for provenance hashing of a structure."""
    return {
        "strategy": structure.strategy,
        "net_premium": structure.net_premium,
        "contracts": structure.contracts,
        "legs": [
            {
                "action": l.action,
                "option_type": l.option_type,
                "strike": l.strike,
                "iv": l.iv,
                "delta": l.delta,
            }
            for l in structure.legs
        ],
    }
