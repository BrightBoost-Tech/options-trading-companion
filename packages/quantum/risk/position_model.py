"""Canonical typed position representation — the honest defined-risk basis.

PR-1 shipped the typed contract + pure math unwired. Consumer PR-2 migrated
the first production seam: risk_envelope._pos_risk uses the exact
payoff-derived max-loss total. Consumer PR-3 migrated the stress seam:
risk_envelope.compute_stress_scenarios floors every scenario at
-Σ max_loss_total (clamp_stress_to_payoff semantics applied at book level)
and types missing greek inputs as unavailable instead of summing silent
zeros. Greeks aggregation (check_greeks), sizing, reconciliation, ranking,
and order paths remain unmigrated and retain their separate PR boundaries.

WHY THIS EXISTS (defects reproduced by tests/test_position_model.py, all in
risk/risk_envelope.py as of bef2cdd):

  D1 credit-as-risk      :200-201  `return max_credit * qty * 100` — the credit
                          RECEIVED (max GAIN) is returned as the position's
                          risk. No width term; strikes are never read. True
                          basis is (width - credit) x multiplier x qty.
  D2 unsigned greeks     :226-233  legs summed with `abs(qty)`; no action/side
                          is read, so a long leg and a short leg ADD. A 4-leg
                          condor contributes 4x|per-leg greek|.
  D3 leg ratios ignored  :226-233  the loop iterates `leg` but scales by the
                          POSITION quantity hoisted at :223. leg["quantity"]
                          is never read.
  D4 multiplier == 100   :201,203,230-233,519-520,530  literal 100 throughout.
  D5 unbounded stress    :522-540  Delta x shock extrapolation with no payoff
                          floor; `corr_one_loss = -total_risk` inherits D1's
                          basis wholesale.

UNITS CONTRACT (the trap this module exists to kill). `risk_basis_shadow.py:86`
and `risk_budget_engine.py:165` disagree today: the former keys `max_loss_total`
as a POSITION-LEVEL TOTAL (already x contracts x multiplier), the latter keys
`max_loss` PER-CONTRACT and multiplies by qty. Every dollar field in this module
is named `_total` when it is position-level and is ALREADY scaled by
structure_quantity and multiplier. NEVER multiply a `_total` by quantity again.

SIGN CONTRACT:
  - signed_ratio: +N long, -N short. abs() is never applied to it.
  - total_entry_cashflow: credit received POSITIVE, debit paid NEGATIVE.
    (Note the persisted convention differs: paper_positions stores
    avg_entry_price ABSOLUTE and carries direction in the SIGN OF quantity —
    see paper_endpoints.py:1403 `_abs_entry_premium` and mark_math.py:156.
    normalize_position() performs that translation explicitly.)

REUSE (H13 — no parallel architecture):
  - OCC parsing: services.options_utils.parse_option_symbol (accepts both the
    Alpaca `XLE260717C00058000` and Polygon `O:XLE...` forms). Four parsers
    already exist; this module adds none.
  - This module does NOT duplicate: payoff_bounds.py (a mark GUARD, long
    2-leg debit verticals only), trade_economics.py (2-leg verticals only,
    per-contract), legs_convention.py (quantity coercion only), mark_math.py
    (mark valuation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from packages.quantum.services.options_utils import parse_option_symbol

# ══════════════════════════════════════════════════════════════════════════
# Typed reasons
# ══════════════════════════════════════════════════════════════════════════


class RejectReason(str, Enum):
    """Why a raw payload cannot become a CanonicalPosition. Typed, never bare."""

    NOT_A_MAPPING = "not_a_mapping"
    NO_LEGS = "no_legs"
    MISSING_FIELD = "missing_field"
    BOOL_NOT_ALLOWED = "bool_not_allowed"
    NOT_A_NUMBER = "not_a_number"
    NON_FINITE = "non_finite"
    ZERO_QUANTITY = "zero_quantity"
    FRACTIONAL_QUANTITY = "fractional_quantity"
    NON_POSITIVE_STRUCTURE_QUANTITY = "non_positive_structure_quantity"
    UNKNOWN_SIDE = "unknown_side"
    UNKNOWN_OPTION_TYPE = "unknown_option_type"
    MALFORMED_STRIKE = "malformed_strike"
    NON_POSITIVE_MULTIPLIER = "non_positive_multiplier"
    UNPARSEABLE_OCC = "unparseable_occ"
    INCONSISTENT_UNDERLYING = "inconsistent_underlying"
    INCONSISTENT_EXPIRY = "inconsistent_expiry"
    MIXED_MULTIPLIER = "mixed_multiplier"
    DUPLICATE_LEG = "duplicate_leg"


class IncompletenessReason(str, Enum):
    """Fields current persistence cannot represent honestly.

    These do NOT reject — they flag (H9: reject or flag, never fabricate).
    Each is a filed dependency for a later PR; none is fixed by a migration
    in PR-1.
    """

    # No writer ever puts greeks on a persisted leg. The scanner flattens
    # delta/gamma/vega/theta onto the CHAIN contract (options_scanner.py:1630)
    # and _suggestion_to_ticket drops them at the OptionLeg boundary
    # (paper_endpoints.py:536). risk_envelope.py:229 reads leg["greeks"] —
    # a key that has never existed. This is D2's dormancy, made explicit.
    GREEKS_NOT_PERSISTED = "greeks_not_persisted"

    # No leg carries a multiplier key anywhere in the repo. 100.0 is derived
    # from OCC-parseability, which cannot prove a non-standard (adjusted)
    # deliverable. Recorded, never silent.
    MULTIPLIER_ASSUMED_STANDARD_OCC = "multiplier_assumed_standard_occ"

    # Currency is persisted nowhere; every instrument in scanner_universe is
    # a US equity option. Recorded so a future non-USD listing cannot inherit
    # a silent assumption.
    CURRENCY_ASSUMED_USD = "currency_assumed_usd"


class RiskClassification(str, Enum):
    DEFINED_RISK = "defined_risk"
    NOT_DEFINED_RISK = "not_defined_risk"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class PositionNormalizationError(ValueError):
    """Rejection carrying a typed reason. Never raise a bare ValueError here."""

    def __init__(self, reason: RejectReason, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


# ══════════════════════════════════════════════════════════════════════════
# Scalar validation — bool/NaN/inf/fraction rejection
# ══════════════════════════════════════════════════════════════════════════


def _reject_bool(value: Any, name: str) -> None:
    """bool is a subclass of int in Python; isinstance(True, int) is True.

    Without this guard `quantity=True` normalizes to 1 contract silently.
    """
    if isinstance(value, bool):
        raise PositionNormalizationError(
            RejectReason.BOOL_NOT_ALLOWED, f"{name} received bool {value!r}"
        )


def _finite_float(value: Any, name: str) -> float:
    _reject_bool(value, name)
    if value is None:
        raise PositionNormalizationError(RejectReason.MISSING_FIELD, name)
    if isinstance(value, str) or not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise PositionNormalizationError(
                RejectReason.NOT_A_NUMBER, f"{name}={value!r}"
            )
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        raise PositionNormalizationError(RejectReason.NON_FINITE, f"{name}={value!r}")
    return out


def _finite_or_none(value: Any) -> Optional[float]:
    """float(value) when finite, else None — the NON-raising sibling of
    _finite_float. None / bool / non-numeric / NaN / inf all resolve to None
    (a MISSING input), never a fabricated 0 (H9). Used to type an
    optional/persisted greek block whose absence must flag, not reject."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _exact_int(value: Any, name: str) -> int:
    """Contract counts are integers. 2.5 contracts is a rejection, not a round."""
    out = _finite_float(value, name)
    if out != int(out):
        raise PositionNormalizationError(
            RejectReason.FRACTIONAL_QUANTITY, f"{name}={value!r}"
        )
    return int(out)


_SHORT_POSITION_TOKENS = frozenset(
    {"sell", "short", "sell_to_open", "buy_to_close", "sto", "btc"}
)
_LONG_POSITION_TOKENS = frozenset(
    {"buy", "long", "buy_to_open", "sell_to_close", "bto", "stc"}
)


def _direction_sign(raw: Any) -> int:
    """+1 long / -1 short. Unknown tokens REJECT — never default to buy.

    Readers today default to "buy" on an unknown token (mark_math.py:134,
    close_math.py:79). A silent default turns an unparseable short leg long.
    """
    _reject_bool(raw, "side")
    token = str(raw or "").strip().lower()
    if token in _LONG_POSITION_TOKENS:
        return 1
    if token in _SHORT_POSITION_TOKENS:
        return -1
    raise PositionNormalizationError(RejectReason.UNKNOWN_SIDE, f"side={raw!r}")


def _option_type(raw: Any) -> OptionType:
    _reject_bool(raw, "option_type")
    token = str(raw or "").strip().lower()
    if token in ("call", "c"):
        return OptionType.CALL
    if token in ("put", "p"):
        return OptionType.PUT
    raise PositionNormalizationError(
        RejectReason.UNKNOWN_OPTION_TYPE, f"option_type={raw!r}"
    )


def _coerce_expiry(raw: Any) -> date:
    _reject_bool(raw, "expiry")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    token = str(raw or "").strip()
    if not token:
        raise PositionNormalizationError(RejectReason.MISSING_FIELD, "expiry")
    try:
        return datetime.strptime(token[:10], "%Y-%m-%d").date()
    except ValueError:
        raise PositionNormalizationError(
            RejectReason.INCONSISTENT_EXPIRY, f"unparseable expiry={raw!r}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LegGreeks:
    """Per-CONTRACT greeks, exactly as a chain snapshot reports them.

    Unscaled: no ratio, no structure quantity, no multiplier applied.
    aggregate_greeks() performs the one and only scaling.

    RAW and UNSIGNED by direction — a call delta is +, a put delta is −, EXACTLY
    as the snapshot reports it. The long/short sign is applied downstream by
    aggregate_greeks via signed_ratio; pre-signing here would double-negate.
    """

    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    # Provenance (observe-only; NOT part of the value math, never scaled, never
    # validated as a number). Carried verbatim from the #1259 stage-time populate
    # (greeks_source / greeks_as_of / greeks_status) so a canonical consumer can
    # see WHERE and WHEN the per-contract greeks were measured.
    source: Optional[str] = None
    as_of: Optional[str] = None
    status: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("delta", "gamma", "vega", "theta"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite_float(value, name))

    def missing_fields(self) -> Tuple[str, ...]:
        return tuple(
            name
            for name in ("delta", "gamma", "vega", "theta")
            if getattr(self, name) is None
        )


@dataclass(frozen=True)
class CanonicalLeg:
    """One option leg, normalized. Immutable.

    signed_ratio is the leg's ratio WITHIN ONE STRUCTURE (+2 == two long
    contracts per structure). It is NOT the position-level contract count —
    that is CanonicalPosition.structure_quantity. Total contracts for this leg
    is signed_ratio x structure_quantity.
    """

    occ_symbol: str
    underlying: str
    expiry: date
    option_type: OptionType
    strike: float
    signed_ratio: int
    multiplier: float
    greeks: Optional[LegGreeks] = None

    def __post_init__(self) -> None:
        try:
            strike = _finite_float(
                self.strike, f"leg {self.occ_symbol} strike"
            )
        except PositionNormalizationError as exc:
            if exc.reason in (
                RejectReason.MISSING_FIELD,
                RejectReason.NOT_A_NUMBER,
                RejectReason.NON_FINITE,
            ):
                raise PositionNormalizationError(
                    RejectReason.MALFORMED_STRIKE,
                    f"leg {self.occ_symbol} strike={self.strike!r}",
                ) from exc
            raise
        multiplier = _finite_float(
            self.multiplier, f"leg {self.occ_symbol} multiplier"
        )
        object.__setattr__(self, "strike", strike)
        object.__setattr__(self, "multiplier", multiplier)
        if self.signed_ratio == 0:
            raise PositionNormalizationError(
                RejectReason.ZERO_QUANTITY, f"leg {self.occ_symbol} signed_ratio=0"
            )
        if not isinstance(self.signed_ratio, int) or isinstance(self.signed_ratio, bool):
            raise PositionNormalizationError(
                RejectReason.NOT_A_NUMBER,
                f"leg {self.occ_symbol} signed_ratio must be int",
            )
        if self.strike <= 0:
            raise PositionNormalizationError(
                RejectReason.MALFORMED_STRIKE,
                f"leg {self.occ_symbol} strike={self.strike}",
            )
        if self.multiplier <= 0:
            raise PositionNormalizationError(
                RejectReason.NON_POSITIVE_MULTIPLIER,
                f"leg {self.occ_symbol} multiplier={self.multiplier}",
            )

    @property
    def is_long(self) -> bool:
        return self.signed_ratio > 0

    def total_contracts(self, structure_quantity: int) -> int:
        return self.signed_ratio * structure_quantity

    def intrinsic_value(self, underlying_price: float) -> float:
        """Per-contract, per-share intrinsic at expiration. Always >= 0."""
        return intrinsic_value(self.option_type, self.strike, underlying_price)


@dataclass(frozen=True)
class Provenance:
    """Where this representation came from and what was assumed building it."""

    source: str
    position_id: Optional[str] = None
    normalized_from: Optional[str] = None
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Completeness:
    """What this representation could NOT honestly source.

    representation_incomplete is True when any reason is present. A consumer
    that requires a complete representation must check this and degrade or
    reject — never read the numbers past it and assume they are whole.
    """

    representation_incomplete: bool
    reasons: Tuple[IncompletenessReason, ...] = ()
    missing_greek_legs: Tuple[str, ...] = ()
    detail: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalPosition:
    """An immutable, normalized multi-leg option structure.

    total_entry_cashflow is POSITION-LEVEL and already scaled by
    structure_quantity and multiplier. Credit received is POSITIVE, debit paid
    is NEGATIVE. Do not multiply it by quantity again.
    """

    underlying: str
    expiry: date
    currency: str
    structure_quantity: int
    legs: Tuple[CanonicalLeg, ...]
    total_entry_cashflow: float
    provenance: Provenance
    completeness: Completeness

    def __post_init__(self) -> None:
        if not self.legs:
            raise PositionNormalizationError(RejectReason.NO_LEGS, "legs is empty")
        if isinstance(self.structure_quantity, bool) or not isinstance(
            self.structure_quantity, int
        ):
            raise PositionNormalizationError(
                RejectReason.NOT_A_NUMBER,
                f"structure_quantity must be int, got {self.structure_quantity!r}",
            )
        if self.structure_quantity <= 0:
            raise PositionNormalizationError(
                RejectReason.NON_POSITIVE_STRUCTURE_QUANTITY,
                f"structure_quantity={self.structure_quantity}",
            )
        cashflow = _finite_float(
            self.total_entry_cashflow, "total_entry_cashflow"
        )
        object.__setattr__(self, "total_entry_cashflow", cashflow)
        symbols = [leg.occ_symbol for leg in self.legs]
        duplicate_symbols = sorted(
            {symbol for symbol in symbols if symbols.count(symbol) > 1}
        )
        if duplicate_symbols:
            raise PositionNormalizationError(
                RejectReason.DUPLICATE_LEG,
                f"duplicate OCC symbols={duplicate_symbols}",
            )
        for leg in self.legs:
            if leg.underlying != self.underlying:
                raise PositionNormalizationError(
                    RejectReason.INCONSISTENT_UNDERLYING,
                    f"leg {leg.occ_symbol} underlying={leg.underlying} != {self.underlying}",
                )
            if leg.expiry != self.expiry:
                raise PositionNormalizationError(
                    RejectReason.INCONSISTENT_EXPIRY,
                    f"leg {leg.occ_symbol} expiry={leg.expiry} != {self.expiry}",
                )

    @property
    def common_multiplier(self) -> float:
        multipliers = {leg.multiplier for leg in self.legs}
        if len(multipliers) != 1:
            raise PositionNormalizationError(
                RejectReason.MIXED_MULTIPLIER, f"multipliers={sorted(multipliers)}"
            )
        return next(iter(multipliers))

    @property
    def strikes(self) -> Tuple[float, ...]:
        return tuple(sorted({leg.strike for leg in self.legs}))


# ══════════════════════════════════════════════════════════════════════════
# Payoff
# ══════════════════════════════════════════════════════════════════════════


def intrinsic_value(
    option_type: OptionType, strike: float, underlying_price: float
) -> float:
    """Per-share intrinsic at expiration for underlying price S >= 0."""
    if underlying_price < 0:
        raise PositionNormalizationError(
            RejectReason.NOT_A_NUMBER, f"underlying_price={underlying_price} < 0"
        )
    if option_type is OptionType.CALL:
        return max(0.0, underlying_price - strike)
    return max(0.0, strike - underlying_price)


def expiration_pnl(position: CanonicalPosition, underlying_price: float) -> float:
    """Total position P&L at expiration for underlying price S >= 0.

    expiration_pnl(S) = total_entry_cashflow
        + SUM[signed_ratio x structure_quantity x multiplier x intrinsic(S)]

    Result is POSITION-LEVEL dollars. Already scaled — never multiply by
    structure_quantity again.
    """
    total = position.total_entry_cashflow
    for leg in position.legs:
        total += (
            leg.signed_ratio
            * position.structure_quantity
            * leg.multiplier
            * leg.intrinsic_value(underlying_price)
        )
    return total


def _upside_slope(position: CanonicalPosition) -> float:
    """d(pnl)/dS for S above every strike.

    Beyond the highest strike every call is ITM (slope 1/share) and every put
    is worthless (slope 0). Negative slope => loss grows without bound.
    """
    return sum(
        leg.signed_ratio * position.structure_quantity * leg.multiplier
        for leg in position.legs
        if leg.option_type is OptionType.CALL
    )


@dataclass(frozen=True)
class PayoffProfile:
    """Position-level payoff bounds. All dollar fields are totals.

    max_profit_total is None when profit is unbounded (long naked call).
    max_loss_total is None when loss is unbounded (short naked call) — and in
    that case classification is NOT_DEFINED_RISK.
    """

    classification: RiskClassification
    max_loss_total: Optional[float]
    max_profit_total: Optional[float]
    min_expiration_pnl: Optional[float]
    breakpoints: Tuple[float, ...]
    upside_slope: float
    loss_unbounded: bool
    profit_unbounded: bool


def analyze_payoff(position: CanonicalPosition) -> PayoffProfile:
    """Exact payoff bounds via breakpoint enumeration.

    expiration_pnl is piecewise-linear in S with kinks only at strikes, so the
    extrema over the domain [0, inf) are attained at a kink, at the S=0
    endpoint, or in the limit S->inf. Enumerating {0} U strikes and the tail
    slope is therefore exact, not a sample.

    Note S=0 is a real evaluable endpoint, so DOWNSIDE loss on an all-option
    structure is always bounded (a short put's worst case is finite at S=0).
    Only the upside can run away.
    """
    breakpoints: List[float] = [0.0]
    breakpoints.extend(position.strikes)
    values = [expiration_pnl(position, s) for s in breakpoints]

    slope = _upside_slope(position)
    loss_unbounded = slope < 0
    profit_unbounded = slope > 0

    min_pnl = min(values)
    max_pnl = max(values)

    if loss_unbounded:
        max_loss_total: Optional[float] = None
        classification = RiskClassification.NOT_DEFINED_RISK
        min_expiration_pnl: Optional[float] = None
    else:
        max_loss_total = max(0.0, -min_pnl)
        classification = RiskClassification.DEFINED_RISK
        min_expiration_pnl = min_pnl

    max_profit_total = None if profit_unbounded else max_pnl

    return PayoffProfile(
        classification=classification,
        max_loss_total=max_loss_total,
        max_profit_total=max_profit_total,
        min_expiration_pnl=min_expiration_pnl,
        breakpoints=tuple(breakpoints),
        upside_slope=slope,
        loss_unbounded=loss_unbounded,
        profit_unbounded=profit_unbounded,
    )


@dataclass(frozen=True)
class StressClamp:
    """Result of bounding a stress P&L to the structure's payoff floor."""

    raw_total_pnl: float
    clamped_total_pnl: float
    floor_total: Optional[float]
    violated: bool
    applicable: bool


def clamp_stress_to_payoff(
    position: CanonicalPosition, raw_total_pnl: float
) -> StressClamp:
    """A stress P&L may never be worse than -max_loss_total.

    This is D5's remedy in pure form. Consumer PR-3 wired the same floor into
    risk_envelope.compute_stress_scenarios at BOOK level (the sum of
    per-structure floors is the book floor), so the production
    `worst = min(...)` can no longer be won by an unfloored delta x shock
    extrapolation. A defined-risk book cannot lose more than the sum of its
    structures' max losses — that is arithmetic, not a policy choice.

    NOT applicable to a not-defined-risk structure: there is no floor to clamp
    to, and inventing one would fabricate a bound (H9).
    """
    profile = analyze_payoff(position)
    if profile.max_loss_total is None:
        return StressClamp(
            raw_total_pnl=raw_total_pnl,
            clamped_total_pnl=raw_total_pnl,
            floor_total=None,
            violated=False,
            applicable=False,
        )
    floor = -profile.max_loss_total
    violated = raw_total_pnl < floor
    return StressClamp(
        raw_total_pnl=raw_total_pnl,
        clamped_total_pnl=max(raw_total_pnl, floor),
        floor_total=floor,
        violated=violated,
        applicable=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# Greeks
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GreekExposure:
    """Position-level greek exposure. Units are in the field names.

    Every field is signed_ratio x structure_quantity x multiplier x per-contract
    greek, summed. A long leg and a short leg SUBTRACT — that is D2's fix.

    A field is None when any leg is missing that greek: a partial sum is a
    fabricated total (H9). complete=False names the offending legs.
    """

    delta_dollars_per_underlying_point: Optional[float]
    gamma_dollars_per_point_squared: Optional[float]
    vega_dollars_per_vol_point: Optional[float]
    theta_dollars_per_day: Optional[float]
    complete: bool
    missing_legs: Tuple[str, ...] = ()
    missing_detail: Tuple[str, ...] = ()
    # Coverage + provenance (observe-only, typed). legs_with_greeks counts legs
    # that contributed a COMPLETE finite greeks set; sources/as_of carry the
    # distinct #1259 stage-populate provenance across the contributing legs.
    legs_total: int = 0
    legs_with_greeks: int = 0
    sources: Tuple[str, ...] = ()
    as_of: Tuple[str, ...] = ()


def aggregate_greeks(position: CanonicalPosition) -> GreekExposure:
    """Sign- and ratio-aware greek aggregation.

    Contrast risk_envelope.py:226-233, which reads no side (so longs and shorts
    add), scales every leg by the POSITION quantity (so leg ratios vanish), and
    hardcodes 100.

    A zero here means the exposure genuinely nets to zero. A missing input
    means None + complete=False — never a silent zero claiming a flat book.
    """
    sums: Dict[str, float] = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    missing_legs: List[str] = []
    missing_detail: List[str] = []
    missing_names: set = set()
    legs_with_greeks = 0
    sources: List[str] = []
    as_of: List[str] = []

    for leg in position.legs:
        scale = leg.signed_ratio * position.structure_quantity * leg.multiplier
        if leg.greeks is None:
            missing_legs.append(leg.occ_symbol)
            missing_detail.append(f"{leg.occ_symbol}: no greeks")
            missing_names.update(sums.keys())
            continue
        absent = leg.greeks.missing_fields()
        if absent:
            missing_legs.append(leg.occ_symbol)
            missing_detail.append(f"{leg.occ_symbol}: missing {', '.join(absent)}")
            missing_names.update(absent)
        else:
            legs_with_greeks += 1
        if leg.greeks.source:
            sources.append(leg.greeks.source)
        if leg.greeks.as_of:
            as_of.append(leg.greeks.as_of)
        for name in sums:
            value = getattr(leg.greeks, name)
            if value is not None:
                sums[name] += scale * value

    def _resolve(name: str) -> Optional[float]:
        return None if name in missing_names else sums[name]

    return GreekExposure(
        delta_dollars_per_underlying_point=_resolve("delta"),
        gamma_dollars_per_point_squared=_resolve("gamma"),
        vega_dollars_per_vol_point=_resolve("vega"),
        theta_dollars_per_day=_resolve("theta"),
        complete=not missing_legs,
        missing_legs=tuple(dict.fromkeys(missing_legs)),
        missing_detail=tuple(missing_detail),
        legs_total=len(position.legs),
        legs_with_greeks=legs_with_greeks,
        sources=tuple(dict.fromkeys(sources)),
        as_of=tuple(dict.fromkeys(as_of)),
    )


# ══════════════════════════════════════════════════════════════════════════
# Reconciliation (pure; no broker calls, no writes)
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ObservedLeg:
    """A leg as some external source reports it. Signed contract count is
    POSITION-LEVEL (what the broker actually shows), not a per-structure ratio.
    """

    occ_symbol: str
    signed_contracts: int
    multiplier: Optional[float] = None
    expiry: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None


@dataclass(frozen=True)
class LegDiscrepancy:
    occ_symbol: str
    kind: str  # missing | extra | duplicate | direction_mismatch | quantity_mismatch | attribute_mismatch
    expected: Optional[Any] = None
    observed: Optional[Any] = None
    detail: str = ""


@dataclass(frozen=True)
class ReconciliationReport:
    matched: bool
    discrepancies: Tuple[LegDiscrepancy, ...]

    @property
    def missing(self) -> Tuple[LegDiscrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.kind == "missing")

    @property
    def extra(self) -> Tuple[LegDiscrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.kind == "extra")

    @property
    def direction_mismatched(self) -> Tuple[LegDiscrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.kind == "direction_mismatch")

    @property
    def quantity_mismatched(self) -> Tuple[LegDiscrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.kind == "quantity_mismatch")

    @property
    def duplicated(self) -> Tuple[LegDiscrepancy, ...]:
        return tuple(d for d in self.discrepancies if d.kind == "duplicate")


def reconcile_legs(
    position: CanonicalPosition, observed: Sequence[ObservedLeg]
) -> ReconciliationReport:
    """Pure expected-vs-observed leg comparison. Read-only.

    Expected signed contracts per leg = signed_ratio x structure_quantity.
    A direction mismatch (sign flip) is reported distinctly from a magnitude
    mismatch: they are different incidents with different causes.
    """
    expected_map: Dict[str, CanonicalLeg] = {
        leg.occ_symbol: leg for leg in position.legs
    }
    observed_map: Dict[str, ObservedLeg] = {}
    discrepancies: List[LegDiscrepancy] = []
    for leg in observed:
        if leg.occ_symbol in observed_map:
            discrepancies.append(
                LegDiscrepancy(
                    occ_symbol=leg.occ_symbol,
                    kind="duplicate",
                    expected=1,
                    observed=sum(
                        1 for candidate in observed
                        if candidate.occ_symbol == leg.occ_symbol
                    ),
                    detail="observed source returned duplicate OCC symbol",
                )
            )
            continue
        observed_map[leg.occ_symbol] = leg

    for occ, leg in expected_map.items():
        want = leg.total_contracts(position.structure_quantity)
        if occ not in observed_map:
            discrepancies.append(
                LegDiscrepancy(
                    occ_symbol=occ,
                    kind="missing",
                    expected=want,
                    observed=None,
                    detail="expected leg not present in observed",
                )
            )
            continue
        got = observed_map[occ]
        if (want > 0) != (got.signed_contracts > 0):
            discrepancies.append(
                LegDiscrepancy(
                    occ_symbol=occ,
                    kind="direction_mismatch",
                    expected=want,
                    observed=got.signed_contracts,
                    detail="signed direction differs",
                )
            )
        elif want != got.signed_contracts:
            discrepancies.append(
                LegDiscrepancy(
                    occ_symbol=occ,
                    kind="quantity_mismatch",
                    expected=want,
                    observed=got.signed_contracts,
                    detail="same direction, different magnitude",
                )
            )
        for name, want_v, got_v in (
            ("multiplier", leg.multiplier, got.multiplier),
            ("expiry", leg.expiry, got.expiry),
            ("strike", leg.strike, got.strike),
            ("option_type", leg.option_type, got.option_type),
        ):
            if got_v is not None and got_v != want_v:
                discrepancies.append(
                    LegDiscrepancy(
                        occ_symbol=occ,
                        kind="attribute_mismatch",
                        expected=want_v,
                        observed=got_v,
                        detail=f"{name} differs",
                    )
                )

    for occ, got in observed_map.items():
        if occ not in expected_map:
            discrepancies.append(
                LegDiscrepancy(
                    occ_symbol=occ,
                    kind="extra",
                    expected=None,
                    observed=got.signed_contracts,
                    detail="observed leg not in expected structure",
                )
            )

    return ReconciliationReport(
        matched=not discrepancies, discrepancies=tuple(discrepancies)
    )


# ══════════════════════════════════════════════════════════════════════════
# Normalization from the persisted convention
# ══════════════════════════════════════════════════════════════════════════


def entry_cashflow_from_net_premium(
    net_premium_abs: float,
    is_credit: bool,
    structure_quantity: int,
    multiplier: float,
) -> float:
    """Translate the persisted ABSOLUTE per-spread premium into signed total.

    paper_positions stores avg_entry_price / max_credit as an ABSOLUTE
    per-spread net premium for BOTH directions and carries direction in the
    SIGN OF quantity (paper_endpoints.py:1403, mark_math.py:156). This is the
    one place that translation happens.

    Returns POSITION-LEVEL dollars: credit positive, debit negative.
    """
    magnitude = _finite_float(net_premium_abs, "net_premium_abs")
    if magnitude < 0:
        raise PositionNormalizationError(
            RejectReason.NOT_A_NUMBER,
            f"net_premium_abs must be absolute, got {net_premium_abs!r}",
        )
    qty = _exact_int(structure_quantity, "structure_quantity")
    if qty <= 0:
        raise PositionNormalizationError(
            RejectReason.NON_POSITIVE_STRUCTURE_QUANTITY,
            f"structure_quantity={structure_quantity!r}",
        )
    mult = _finite_float(multiplier, "multiplier")
    if mult <= 0:
        raise PositionNormalizationError(
            RejectReason.NON_POSITIVE_MULTIPLIER, f"multiplier={multiplier!r}"
        )
    total = magnitude * qty * mult
    return total if is_credit else -total


def _leg_symbol(raw: Mapping[str, Any]) -> str:
    return str(raw.get("occ_symbol") or raw.get("symbol") or "").strip()


def leg_greeks_from_persisted(raw: Mapping[str, Any]) -> Optional[LegGreeks]:
    """Source RAW per-contract greeks from a persisted leg's own jsonb.

    This reads the #1259 stage-time populate written onto each option leg
    (paper_endpoints._apply_leg_greeks): a ``greeks`` block of
    {delta, gamma, vega, theta} plus provenance keys ``greeks_source`` /
    ``greeks_as_of`` / ``greeks_status``. Identity is by CONSTRUCTION — the
    greeks live on the very leg dict being normalized, so there is no
    symbol/index mapping to get wrong.

    Returns a LegGreeks ONLY when the block is a COMPLETE finite dict (all four
    of delta/gamma/vega/theta present AND finite — the exact shape #1259 writes
    on a full populate). A None / partial / absent / typed-unavailable
    (greeks=None + greeks_status='unavailable_at_stage') block returns None: the
    leg is typed greeks-unavailable, never a fabricated zero (H9). Greeks are
    kept RAW and UNSIGNED — signing and ×qty×multiplier scaling are
    aggregate_greeks' single responsibility."""
    if not isinstance(raw, Mapping):
        return None
    block = raw.get("greeks")
    if not isinstance(block, Mapping):
        return None
    values: Dict[str, float] = {}
    for name in ("delta", "gamma", "vega", "theta"):
        fv = _finite_or_none(block.get(name))
        if fv is None:
            return None  # partial / nonfinite → typed unavailable, not a 0
        values[name] = fv
    return LegGreeks(
        delta=values["delta"],
        gamma=values["gamma"],
        vega=values["vega"],
        theta=values["theta"],
        source=(str(raw["greeks_source"]) if raw.get("greeks_source") else None),
        as_of=(str(raw["greeks_as_of"]) if raw.get("greeks_as_of") else None),
        status=(str(raw["greeks_status"]) if raw.get("greeks_status") else None),
    )


def leg_full_contract_count(
    raw_leg: Mapping[str, Any], position_quantity: Any
) -> Optional[int]:
    """Honest FULL-COUNT contracts for ONE raw persisted leg — the single place
    a raw-dict greek/stress consumer reads a leg's own contract count so leg
    RATIOS are honored identically to ``aggregate_greeks`` (D3's owner-side fix).

    In the persisted FULL-COUNT convention (legs_convention.py, normalize_leg) a
    leg's ``quantity`` IS its total contract count: ``abs(pos.quantity)`` for a
    1:1 structure, and ``ratio × structure_quantity`` for a ratio spread. That
    count equals ``signed_ratio × structure_quantity`` — the exact magnitude
    ``aggregate_greeks`` scales each per-contract greek by — so a consumer that
    multiplies its per-contract greek by THIS count composes byte-identically to
    the canonical owner (the per-leg multiplier, D4, stays the consumer's own
    lane). A 1×2 ratio's short 2-lot is therefore counted twice, not once.

    Reuses ``_exact_int`` (no second parser). Returns a POSITIVE int, or ``None``
    when the count cannot be honestly determined — a malformed / non-integral /
    zero leg quantity is typed unavailable (H9: the caller contributes NOTHING
    and flags the leg uncovered, never a fabricated count). An ABSENT leg
    quantity falls back to ``abs(position_quantity)`` — the full-count identity
    (leg.quantity == abs(pos.quantity)) — so a 1:1 book is byte-identical to the
    pre-ratio ``abs(qty)`` scaling and a sideless minimal dict still scales.
    """
    raw = raw_leg.get("quantity") if isinstance(raw_leg, Mapping) else None
    source = raw if raw is not None else position_quantity
    try:
        count = abs(_exact_int(source, "leg contract count"))
    except PositionNormalizationError:
        return None
    return count or None


def normalize_leg(
    raw: Mapping[str, Any],
    structure_quantity: int,
    *,
    greeks: Optional[LegGreeks] = None,
) -> Tuple[CanonicalLeg, List[IncompletenessReason]]:
    """Normalize one persisted leg dict into a CanonicalLeg.

    Accepts the persisted convention (`action`) and the scanner/broker
    convention (`side`) — the two disagree in the wild (close_math.py:77).
    Identity is taken from the OCC symbol, which is the only field every
    writer sets; strike/type/expiry dict keys are cross-checked against it
    when present, and a disagreement REJECTS rather than picking a winner.
    """
    if not isinstance(raw, Mapping):
        raise PositionNormalizationError(
            RejectReason.NOT_A_MAPPING, f"leg={raw!r}"
        )

    occ = _leg_symbol(raw)
    if not occ:
        raise PositionNormalizationError(RejectReason.MISSING_FIELD, "leg symbol")

    parsed = parse_option_symbol(occ)
    if not parsed:
        raise PositionNormalizationError(RejectReason.UNPARSEABLE_OCC, occ)

    underlying = parsed["underlying"]
    expiry = _coerce_expiry(parsed["expiry"])
    option_type = _option_type(parsed["type"])
    strike = _finite_float(parsed["strike"], "strike")

    # Cross-check the dict keys against OCC identity. Disagreement rejects.
    if raw.get("strike") is not None:
        dict_strike = _finite_float(raw.get("strike"), "strike")
        if abs(dict_strike - strike) > 1e-6:
            raise PositionNormalizationError(
                RejectReason.MALFORMED_STRIKE,
                f"{occ}: dict strike {dict_strike} != OCC strike {strike}",
            )
    if raw.get("type") or raw.get("option_type") or raw.get("right"):
        dict_type = _option_type(
            raw.get("type") or raw.get("option_type") or raw.get("right")
        )
        if dict_type is not option_type:
            raise PositionNormalizationError(
                RejectReason.UNKNOWN_OPTION_TYPE,
                f"{occ}: dict type {dict_type.value} != OCC type {option_type.value}",
            )
    if raw.get("expiry") or raw.get("expiration"):
        dict_expiry = _coerce_expiry(raw.get("expiry") or raw.get("expiration"))
        if dict_expiry != expiry:
            raise PositionNormalizationError(
                RejectReason.INCONSISTENT_EXPIRY,
                f"{occ}: dict expiry {dict_expiry} != OCC expiry {expiry}",
            )

    side_raw = raw.get("action") if raw.get("action") is not None else raw.get("side")
    sign = _direction_sign(side_raw)

    if "quantity" not in raw or raw.get("quantity") is None:
        raise PositionNormalizationError(
            RejectReason.MISSING_FIELD, f"{occ}: quantity absent — will not default to 1"
        )
    leg_contracts = _exact_int(raw.get("quantity"), f"{occ}.quantity")
    if leg_contracts == 0:
        raise PositionNormalizationError(RejectReason.ZERO_QUANTITY, occ)
    leg_contracts = abs(leg_contracts)

    # The persisted convention is FULL-COUNT: leg.quantity == abs(pos.quantity)
    # (legs_convention.py:4-8). Recover the per-structure ratio by dividing out
    # the structure quantity — and reject rather than round if it does not
    # divide, because a fractional ratio is not representable.
    if leg_contracts % structure_quantity != 0:
        raise PositionNormalizationError(
            RejectReason.FRACTIONAL_QUANTITY,
            f"{occ}: leg contracts {leg_contracts} not divisible by "
            f"structure_quantity {structure_quantity}",
        )
    ratio = leg_contracts // structure_quantity

    incomplete: List[IncompletenessReason] = []
    raw_multiplier = raw.get("multiplier")
    if raw_multiplier is None:
        # No writer sets a multiplier key. 100.0 is the standard OCC equity
        # deliverable, but OCC-parseability cannot PROVE the deliverable is
        # standard (adjusted contracts exist). Recorded, never silent.
        multiplier = 100.0
        incomplete.append(IncompletenessReason.MULTIPLIER_ASSUMED_STANDARD_OCC)
    else:
        multiplier = _finite_float(raw_multiplier, f"{occ}.multiplier")
        if multiplier <= 0:
            raise PositionNormalizationError(
                RejectReason.NON_POSITIVE_MULTIPLIER, f"{occ}: multiplier={raw_multiplier!r}"
            )

    # Auto-source per-leg greeks from the leg's OWN persisted jsonb (#1259
    # stage-time populate) when the caller did not supply an explicit override.
    # Precedence: an explicit greeks_by_symbol entry (passed as `greeks`) WINS;
    # otherwise read the leg's own block. Identity is by construction (same leg
    # dict), never index-guessed.
    if greeks is None:
        greeks = leg_greeks_from_persisted(raw)

    if greeks is None:
        incomplete.append(IncompletenessReason.GREEKS_NOT_PERSISTED)

    leg = CanonicalLeg(
        occ_symbol=occ,
        underlying=underlying,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
        signed_ratio=sign * ratio,
        multiplier=multiplier,
        greeks=greeks,
    )
    return leg, incomplete


def normalize_position(
    raw: Mapping[str, Any],
    *,
    currency: str = "USD",
    greeks_by_symbol: Optional[Mapping[str, LegGreeks]] = None,
    source: str = "paper_positions",
) -> CanonicalPosition:
    """Build a CanonicalPosition from a persisted paper_positions row.

    Expects the persisted convention:
      quantity          signed; POSITIVE = debit, NEGATIVE = credit
      legs              [{symbol|occ_symbol, action|side, quantity, ...}]
      avg_entry_price   ABSOLUTE per-spread net premium (max_credit accepted
                        as a fallback; both are absolute by contract)

    Raises PositionNormalizationError with a typed reason on any rejection.
    The returned position's `completeness` names what could not be sourced.
    """
    if not isinstance(raw, Mapping):
        raise PositionNormalizationError(RejectReason.NOT_A_MAPPING, f"position={raw!r}")

    raw_qty = raw.get("quantity")
    if raw_qty is None:
        raise PositionNormalizationError(
            RejectReason.MISSING_FIELD, "quantity — will not default to 1"
        )
    signed_qty = _exact_int(raw_qty, "quantity")
    if signed_qty == 0:
        raise PositionNormalizationError(RejectReason.ZERO_QUANTITY, "quantity=0")

    structure_quantity = abs(signed_qty)
    is_credit = signed_qty < 0

    raw_legs = raw.get("legs")
    if not raw_legs or not isinstance(raw_legs, (list, tuple)):
        raise PositionNormalizationError(RejectReason.NO_LEGS, f"legs={raw_legs!r}")

    greeks_by_symbol = greeks_by_symbol or {}
    legs: List[CanonicalLeg] = []
    reasons: List[IncompletenessReason] = []
    for raw_leg in raw_legs:
        occ = _leg_symbol(raw_leg) if isinstance(raw_leg, Mapping) else ""
        leg, leg_reasons = normalize_leg(
            raw_leg, structure_quantity, greeks=greeks_by_symbol.get(occ)
        )
        legs.append(leg)
        reasons.extend(leg_reasons)

    underlyings = {leg.underlying for leg in legs}
    if len(underlyings) != 1:
        raise PositionNormalizationError(
            RejectReason.INCONSISTENT_UNDERLYING, f"underlyings={sorted(underlyings)}"
        )
    expiries = {leg.expiry for leg in legs}
    if len(expiries) != 1:
        raise PositionNormalizationError(
            RejectReason.INCONSISTENT_EXPIRY,
            f"expiries={sorted(str(e) for e in expiries)} — calendars are not "
            "representable as a single-expiry structure",
        )

    premium = raw.get("avg_entry_price")
    if premium is None:
        premium = raw.get("max_credit")
    if premium is None:
        raise PositionNormalizationError(
            RejectReason.MISSING_FIELD, "avg_entry_price / max_credit"
        )

    multipliers = {leg.multiplier for leg in legs}
    if len(multipliers) != 1:
        raise PositionNormalizationError(
            RejectReason.MIXED_MULTIPLIER, f"multipliers={sorted(multipliers)}"
        )

    total_entry_cashflow = entry_cashflow_from_net_premium(
        net_premium_abs=premium,
        is_credit=is_credit,
        structure_quantity=structure_quantity,
        multiplier=next(iter(multipliers)),
    )

    reasons.append(IncompletenessReason.CURRENCY_ASSUMED_USD)
    ordered_reasons = tuple(dict.fromkeys(reasons))
    missing_greek_legs = tuple(leg.occ_symbol for leg in legs if leg.greeks is None)

    completeness = Completeness(
        representation_incomplete=bool(ordered_reasons),
        reasons=ordered_reasons,
        missing_greek_legs=missing_greek_legs,
        detail=tuple(r.value for r in ordered_reasons),
    )

    return CanonicalPosition(
        underlying=next(iter(underlyings)),
        expiry=next(iter(expiries)),
        currency=currency,
        structure_quantity=structure_quantity,
        legs=tuple(legs),
        total_entry_cashflow=total_entry_cashflow,
        provenance=Provenance(
            source=source,
            position_id=(str(raw["id"]) if raw.get("id") is not None else None),
            normalized_from="persisted_legs_full_count_convention",
        ),
        completeness=completeness,
    )
