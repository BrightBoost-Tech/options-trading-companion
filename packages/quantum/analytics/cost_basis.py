"""Multi-basis cost typed model — phase-2 foundation (Lane 3C, 2026-07-17).

OBSERVE-ONLY. This module RECORDS and RECONCILES the system's divergent cost
bases; it never decides, never writes to the DB, never runs as a job, and no
production decision module may import it (one-way dependency, pinned by
test_cost_basis_import_lock.py). The existing formulas are FROZEN BASELINES —
each extractor reproduces one production formula exactly (by importing and
calling the real code), and the parity tests pin the numbers so silent drift
in a production formula breaks the build.

FROZEN FORMULA INVENTORY (traced 2026-07-17 at main 62b5f4f):

1. scanner_estimate — TWO max()'d layers:
   a. options_scanner._determine_execution_cost (options_scanner.py:2445-2502):
      proxy_per_contract = (combo_width_share * take_frac
                            + num_legs * 0.0065) * 100
      with take_frac = EXECUTION_SPREAD_TAKE_FRAC_LIMIT (0.25, :141) for
      limit orders / 0.50 market (:143); expected = max(history avg_drag,
      proxy) (history wins only when >= proxy AND samples > 0, :2486).
      UNITS: USD per structure-contract (1-lot). FEES: num_legs * $0.65,
      ONE SIDE ONLY, never quantity-scaled.
   b. analytics/scoring.calculate_unified_score (scoring.py:90-114): its OWN
      inner proxy = (entry_cost * spread_pct * 0.5 + num_legs * 0.0065) * 100
      — note the DIFFERENT take fraction (fixed 0.5 vs 0.25) and width basis
      (entry_cost*spread_pct vs combo_width_share) — then
      final_execution_cost = max(inner_proxy, execution_drag_estimate)
      (:114). The scanner's gate consumes THIS
      (unified_score.execution_cost_dollars, options_scanner.py:3874).

2. ranker_model — analytics/canonical_ranker (canonical_ranker.py:24-74,
   100-142): fees = 0.65 * contracts * leg_count * 2 (round-trip, per leg per
   structure-contract, :64; malformed legs raise -> -999 filter :119-132);
   slippage = tcm.expected_slippage or sizing.expected_slippage or
   5%-of-|EV| floor (:197-209); expected_pnl = ev - slippage - fees vs
   MIN_EDGE_AFTER_COSTS ($15). EV BASIS: CALIBRATED when apply-at-scoring is
   armed (calibration_apply_ordering.py:134-146 overwrites c["ev"]=cal_ev,
   raw preserved in _ev_raw_true). NOTE the quantity mixing: fees are
   quantity-scaled TOTALS while ev rides per-structure.

3. stage_executable_cross — paper_endpoints._apply_entry_roundtrip_gate
   (paper_endpoints.py:1260-1414) on
   exit_mark_corroboration.executable_roundtrip_cost
   (exit_mark_corroboration.py:396-484):
   round_trip = sum per-leg (ask - bid) * 100 * contracts (all-or-nothing
   None on any one-sided leg, :460-469); round_trip_per_contract =
   sum (ask - bid) * 100 (1-lot basis, :470). GATE_QTY_FIX_LIVE_ENABLED
   wrinkle (:1349-1370): legacy live decision = gross_ev(per-structure) -
   round_trip(TOTAL, qty-scaled) — a unit mismatch at qty>1 (the E2
   divergence); fixed basis = gross_ev - round_trip_per_contract; shadows
   always fixed, live legacy unless flag ON.

4. tcm — TWO classes share one name:
   a. execution/transaction_cost_model.TransactionCostModel.estimate
      (transaction_cost_model.py:107-223, VERSION 1.1.0):
      fees = max(min_fee, qty * 0.65) ONE-WAY and LEG-COUNT-BLIND (:151-152);
      spread cost = (spread / 2) * qty * 100 (half-cross on a SINGLE quote —
      leg-1-only for multi-leg, :160); slippage = mid * qty * 100 *
      spread_slippage_bps/1e4 (:164-165); missing/zero quote -> FABRICATES
      bid/ask at limit_price*(1 +/- 1%) with used_fallback=True (:121-143).
   b. services/transaction_cost_model.TransactionCostModel.estimate_costs
      (transaction_cost_model.py:21-29, legacy): slippage = price *
      bps/1e4 * qty — NO option multiplier — plus max(min_fee, 0.65*qty).
      Consumers: historical_simulation + backtest LegacyTCM.

5. realized — services/close_fill_gap (close_fill_gap.py:44-47 keys,
   :62-99): stage-stamped cross/mid in SIGNED mark basis (per-structure-
   contract price), fill = NEGATION of the broker mleg net fill (:81-99);
   gap_fraction = (fill - cross) / (mid - cross).

NO decision, threshold, rank, or gate changes anywhere in this module.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

OPTION_MULTIPLIER = 100.0
MODEL_VERSION = "cost-basis/phase2-foundation-1.0"

# Rendered marker for an unavailable value in as_dict outputs — a missing
# input is typed UNAVAILABLE, never zero (H9 both ends).
UNAVAILABLE = "UNAVAILABLE"

# Frozen-baseline provenance tags (bump ONLY when the traced production
# formula itself changes — the parity tests are the tripwire).
_FROZEN = "frozen-2026-07-17@62b5f4f"


class CostSource(str, Enum):
    SCANNER_ESTIMATE = "scanner_estimate"
    RANKER_MODEL = "ranker_model"
    STAGE_EXECUTABLE_CROSS = "stage_executable_cross"
    TCM = "tcm"
    REALIZED = "realized"


class CostUnit(str, Enum):
    """Scaling of amount_usd.

    PER_LEG                — one leg x one contract (never quantity-scaled).
    PER_STRUCTURE_CONTRACT — whole structure x one contract (a 1-lot).
    TOTAL                  — whole structure x all contracts.
    """

    PER_LEG = "per_leg"
    PER_STRUCTURE_CONTRACT = "per_structure_contract"
    TOTAL = "total"


class CostSide(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    ROUND_TRIP = "round_trip"


class CostBasisKind(str, Enum):
    ESTIMATED = "estimated"
    EXECUTABLE = "executable"
    REALIZED = "realized"


@dataclass(frozen=True)
class Provenance:
    """Where a number came from. model_version identifies the FROZEN
    production formula; quote_timestamp is the quote-time when known;
    fallback=True marks values produced by a production fallback path
    (e.g. the TCM fabricated +/-1% quote) — flagged, never endorsed."""

    model_version: str
    quote_timestamp: Optional[str] = None
    source_detail: Optional[str] = None
    fallback: bool = False


@dataclass(frozen=True)
class CostComponent:
    """One typed cost number. A missing input is a typed UNAVAILABLE
    (available=False, amount_usd=None, reason set) — NEVER zero (H9)."""

    name: str
    source: CostSource
    side: CostSide
    basis: CostBasisKind
    unit: CostUnit
    amount_usd: Optional[float]
    quantity: Optional[float] = None
    multiplier: float = OPTION_MULTIPLIER
    available: bool = True
    unavailable_reason: Optional[str] = None
    provenance: Optional[Provenance] = None

    def __post_init__(self) -> None:
        if self.available and self.amount_usd is None:
            raise ValueError(
                f"CostComponent {self.name!r}: available=True requires an "
                f"amount_usd — a missing value must be typed UNAVAILABLE, "
                f"never an implicit None/zero"
            )
        if not self.available:
            if self.amount_usd is not None:
                raise ValueError(
                    f"CostComponent {self.name!r}: available=False cannot "
                    f"carry an amount_usd"
                )
            if not self.unavailable_reason:
                raise ValueError(
                    f"CostComponent {self.name!r}: available=False requires "
                    f"unavailable_reason"
                )

    @classmethod
    def make_unavailable(
        cls,
        name: str,
        source: CostSource,
        side: CostSide,
        basis: CostBasisKind,
        unit: CostUnit,
        reason: str,
        quantity: Optional[float] = None,
        provenance: Optional[Provenance] = None,
    ) -> "CostComponent":
        return cls(
            name=name, source=source, side=side, basis=basis, unit=unit,
            amount_usd=None, quantity=quantity, available=False,
            unavailable_reason=reason, provenance=provenance,
        )

    def in_unit(self, target: CostUnit) -> "CostComponent":
        """Convert between PER_STRUCTURE_CONTRACT and TOTAL via quantity.

        PER_LEG is deliberately NOT convertible (leg composition is not
        carried on a single component) — a typed refusal, never a guess.
        Unavailable components propagate their reason. A missing/invalid
        quantity yields a typed UNAVAILABLE, never a fabricated scale."""
        if target == self.unit:
            return self
        if not self.available:
            return CostComponent.make_unavailable(
                self.name, self.source, self.side, self.basis, target,
                self.unavailable_reason or "unavailable",
                quantity=self.quantity, provenance=self.provenance,
            )
        if self.unit == CostUnit.PER_LEG or target == CostUnit.PER_LEG:
            return CostComponent.make_unavailable(
                self.name, self.source, self.side, self.basis, target,
                "per_leg_not_convertible",
                quantity=self.quantity, provenance=self.provenance,
            )
        qty = self.quantity
        try:
            qty_f = abs(float(qty)) if qty is not None else None
        except (TypeError, ValueError):
            qty_f = None
        if not qty_f:
            return CostComponent.make_unavailable(
                self.name, self.source, self.side, self.basis, target,
                "quantity_missing_for_unit_conversion",
                quantity=self.quantity, provenance=self.provenance,
            )
        if (self.unit, target) == (
            CostUnit.PER_STRUCTURE_CONTRACT, CostUnit.TOTAL
        ):
            amount = float(self.amount_usd) * qty_f
        elif (self.unit, target) == (
            CostUnit.TOTAL, CostUnit.PER_STRUCTURE_CONTRACT
        ):
            amount = float(self.amount_usd) / qty_f
        else:  # pragma: no cover - the enum pairs above are exhaustive
            return CostComponent.make_unavailable(
                self.name, self.source, self.side, self.basis, target,
                f"unsupported_unit_conversion:{self.unit.value}->{target.value}",
                quantity=self.quantity, provenance=self.provenance,
            )
        return CostComponent(
            name=self.name, source=self.source, side=self.side,
            basis=self.basis, unit=target, amount_usd=amount,
            quantity=self.quantity, multiplier=self.multiplier,
            provenance=self.provenance,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.value,
            "side": self.side.value,
            "basis": self.basis.value,
            "unit": self.unit.value,
            "amount_usd": self.amount_usd,
            "quantity": self.quantity,
            "multiplier": self.multiplier,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "provenance": (
                {
                    "model_version": self.provenance.model_version,
                    "quote_timestamp": self.provenance.quote_timestamp,
                    "source_detail": self.provenance.source_detail,
                    "fallback": self.provenance.fallback,
                }
                if self.provenance
                else None
            ),
        }


@dataclass(frozen=True)
class CostBreakdown:
    """All typed components one source produced for one candidate, plus the
    name of the PRIMARY component (the number that source's production
    consumer actually acts on)."""

    source: CostSource
    side: CostSide
    basis: CostBasisKind
    components: Tuple[CostComponent, ...]
    primary: str
    quantity: Optional[float] = None
    provenance: Optional[Provenance] = None

    def component(self, name: str) -> Optional[CostComponent]:
        for c in self.components:
            if c.name == name:
                return c
        return None

    @property
    def primary_component(self) -> CostComponent:
        c = self.component(self.primary)
        if c is None:  # pragma: no cover - constructors always include it
            raise KeyError(f"primary component {self.primary!r} missing")
        return c

    def primary_in_unit(self, unit: CostUnit) -> CostComponent:
        return self.primary_component.in_unit(unit)

    @property
    def available(self) -> bool:
        return self.primary_component.available

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "side": self.side.value,
            "basis": self.basis.value,
            "primary": self.primary,
            "quantity": self.quantity,
            "components": [c.as_dict() for c in self.components],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Frozen-baseline extractors. Each one IMPORTS AND CALLS the real production
# formula (lazy imports keep this module's import surface inert) and wraps the
# result in typed components. None of them mutates its inputs.
# ─────────────────────────────────────────────────────────────────────────────


def extract_scanner_drag_cost(
    *,
    drag_map: Optional[Mapping[str, Any]],
    symbol: str,
    combo_width_share: Optional[float],
    num_legs: Optional[int],
    is_limit: bool = True,
    quantity: Optional[float] = None,
) -> CostBreakdown:
    """Basis 1a — options_scanner._determine_execution_cost, called for real.

    Output unit is USD PER STRUCTURE-CONTRACT; the embedded commission is
    num_legs x $0.65 ONE SIDE ONLY and never quantity-scaled (frozen fact,
    surfaced via provenance)."""
    mv = Provenance(
        model_version=f"options_scanner._determine_execution_cost@{_FROZEN}",
        source_detail="commission_embedded_one_side_only",
    )
    if combo_width_share is None or num_legs is None:
        missing = [
            n for n, v in (
                ("combo_width_share", combo_width_share),
                ("num_legs", num_legs),
            ) if v is None
        ]
        comp = CostComponent.make_unavailable(
            "expected_execution_cost", CostSource.SCANNER_ESTIMATE,
            CostSide.ENTRY, CostBasisKind.ESTIMATED,
            CostUnit.PER_STRUCTURE_CONTRACT,
            f"scanner_inputs_missing:{','.join(missing)}",
            quantity=quantity, provenance=mv,
        )
        return CostBreakdown(
            source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
            basis=CostBasisKind.ESTIMATED, components=(comp,),
            primary="expected_execution_cost", quantity=quantity,
            provenance=mv,
        )

    from packages.quantum.options_scanner import _determine_execution_cost

    result = _determine_execution_cost(
        drag_map=dict(drag_map or {}), symbol=symbol,
        combo_width_share=float(combo_width_share), num_legs=int(num_legs),
        is_limit=is_limit,
    )
    prov = Provenance(
        model_version=f"options_scanner._determine_execution_cost@{_FROZEN}",
        source_detail=(
            f"source_used={result['execution_cost_source_used']}"
            f",samples={result['execution_cost_samples_used']}"
            f",take_frac={result['spread_take_frac']}"
            f",commission_embedded_one_side_only"
        ),
    )
    primary = CostComponent(
        name="expected_execution_cost",
        source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED,
        unit=CostUnit.PER_STRUCTURE_CONTRACT,
        amount_usd=float(result["expected_execution_cost"]),
        quantity=quantity, provenance=prov,
    )
    proxy = CostComponent(
        name="proxy_cost_contract",
        source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED,
        unit=CostUnit.PER_STRUCTURE_CONTRACT,
        amount_usd=float(result["proxy_cost_contract"]),
        quantity=quantity, provenance=prov,
    )
    return CostBreakdown(
        source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, components=(primary, proxy),
        primary="expected_execution_cost", quantity=quantity, provenance=prov,
    )


def extract_scanner_unified_final_cost(
    *,
    trade: Optional[Mapping[str, Any]],
    regime_snapshot: Optional[Mapping[str, Any]] = None,
    market_data: Optional[Mapping[str, Any]] = None,
    execution_drag_estimate: float = 0.0,
    num_legs: Optional[int] = None,
    entry_cost: Optional[float] = None,
    quantity: Optional[float] = None,
) -> CostBreakdown:
    """Basis 1b — the scanner's FINAL execution cost: the hidden second
    max() layer inside analytics/scoring.calculate_unified_score
    (execution_cost_dollars, consumed at options_scanner.py:3874).

    Its inner proxy uses a 0.5 take fraction where _determine_execution_cost
    uses 0.25 for limits — two disagreeing formulas max()'d together."""
    prov = Provenance(
        model_version=f"analytics.scoring.calculate_unified_score@{_FROZEN}",
        source_detail="max(inner_half_width_proxy_0.5, execution_drag_estimate)",
    )
    if trade is None:
        comp = CostComponent.make_unavailable(
            "unified_execution_cost", CostSource.SCANNER_ESTIMATE,
            CostSide.ENTRY, CostBasisKind.ESTIMATED,
            CostUnit.PER_STRUCTURE_CONTRACT, "trade_missing",
            quantity=quantity, provenance=prov,
        )
        return CostBreakdown(
            source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
            basis=CostBasisKind.ESTIMATED, components=(comp,),
            primary="unified_execution_cost", quantity=quantity,
            provenance=prov,
        )

    from packages.quantum.analytics.scoring import calculate_unified_score

    score = calculate_unified_score(
        trade=dict(trade),
        regime_snapshot=dict(regime_snapshot or {"state": "normal"}),
        market_data=dict(market_data or {}),
        execution_drag_estimate=float(execution_drag_estimate or 0.0),
        num_legs=num_legs,
        entry_cost=entry_cost,
    )
    comp = CostComponent(
        name="unified_execution_cost",
        source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED,
        unit=CostUnit.PER_STRUCTURE_CONTRACT,
        amount_usd=float(score.execution_cost_dollars),
        quantity=quantity, provenance=prov,
    )
    return CostBreakdown(
        source=CostSource.SCANNER_ESTIMATE, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, components=(comp,),
        primary="unified_execution_cost", quantity=quantity, provenance=prov,
    )


def extract_ranker_costs(
    suggestion: Mapping[str, Any],
    *,
    fee_per_contract: float = 0.65,
    ev_basis: Optional[str] = None,
    quantity: Optional[float] = None,
) -> CostBreakdown:
    """Basis 2 — canonical_ranker fees + slippage, called for real on a DEEP
    COPY (production _ranking_round_trip_fees mutates its suggestion; this
    extractor never mutates the caller's object).

    ev_basis: "calibrated" | "raw" | None(unknown) — caller-declared, since
    apply-at-scoring overwrites suggestion["ev"] in place when armed
    (calibration_apply_ordering.py:134-146)."""
    from packages.quantum.analytics.canonical_ranker import (
        _estimate_slippage,
        _ranking_round_trip_fees,
    )

    work = copy.deepcopy(dict(suggestion))
    sizing = work.get("sizing_metadata") or {}
    qty = quantity
    if qty is None:
        try:
            qty = float(sizing.get("contracts") or 1)
        except (TypeError, ValueError):
            qty = None

    prov_base = Provenance(
        model_version=f"canonical_ranker@{_FROZEN}",
        source_detail=f"ev_basis={ev_basis or 'unknown'}",
    )

    # Fees — the real formula, or a typed UNAVAILABLE on the exact exception
    # classes production filters to -999 on (canonical_ranker.py:119-132).
    try:
        fees_val = _ranking_round_trip_fees(work, fee_per_contract)
        ranking_costs = work.get("ranking_costs") or {}
        fees = CostComponent(
            name="round_trip_fees",
            source=CostSource.RANKER_MODEL, side=CostSide.ROUND_TRIP,
            basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
            amount_usd=float(fees_val), quantity=qty,
            provenance=Provenance(
                model_version=f"canonical_ranker._ranking_round_trip_fees@{_FROZEN}",
                source_detail=(
                    f"commission_basis={ranking_costs.get('commission_basis')}"
                    f",leg_count={ranking_costs.get('leg_count')}"
                    f",fee_per_leg_contract_side={fee_per_contract}"
                    f",round_trip_sides=2"
                ),
            ),
        )
    except (TypeError, ValueError) as exc:
        fees = CostComponent.make_unavailable(
            "round_trip_fees", CostSource.RANKER_MODEL, CostSide.ROUND_TRIP,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            f"commission_basis_unavailable:{exc}",
            quantity=qty,
            provenance=Provenance(
                model_version=f"canonical_ranker._ranking_round_trip_fees@{_FROZEN}",
                source_detail="production_disposition=filtered_-999",
            ),
        )

    # Slippage — the real proxy; provenance records WHICH branch supplied it
    # (mirrors canonical_ranker.py:197-209 branch order exactly).
    slip_val = _estimate_slippage(work)
    tcm_slip = (work.get("tcm") or {}).get("expected_slippage")
    sizing_slip = (work.get("sizing_metadata") or {}).get("expected_slippage")
    ev = work.get("ev")
    if tcm_slip:
        branch = "tcm_expected_slippage"
    elif sizing_slip:
        branch = "sizing_expected_slippage"
    elif ev:
        branch = "five_pct_of_ev_floor"
    else:
        branch = "zero_no_ev"
    slippage = CostComponent(
        name="expected_slippage",
        source=CostSource.RANKER_MODEL, side=CostSide.ROUND_TRIP,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=float(slip_val), quantity=qty,
        provenance=Provenance(
            model_version=f"canonical_ranker._estimate_slippage@{_FROZEN}",
            source_detail=f"branch={branch}",
            fallback=(branch in ("five_pct_of_ev_floor", "zero_no_ev")),
        ),
    )

    # Primary = the number production subtracts from EV: fees + slippage.
    if fees.available:
        primary = CostComponent(
            name="fees_plus_slippage",
            source=CostSource.RANKER_MODEL, side=CostSide.ROUND_TRIP,
            basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
            amount_usd=float(fees.amount_usd) + float(slippage.amount_usd),
            quantity=qty, provenance=prov_base,
        )
    else:
        primary = CostComponent.make_unavailable(
            "fees_plus_slippage", CostSource.RANKER_MODEL,
            CostSide.ROUND_TRIP, CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            fees.unavailable_reason or "commission_basis_unavailable",
            quantity=qty, provenance=prov_base,
        )

    return CostBreakdown(
        source=CostSource.RANKER_MODEL, side=CostSide.ROUND_TRIP,
        basis=CostBasisKind.ESTIMATED,
        components=(primary, fees, slippage),
        primary="fees_plus_slippage", quantity=qty, provenance=prov_base,
    )


def extract_stage_executable_cross(
    *,
    legs: List[Dict[str, Any]],
    leg_quotes: Mapping[str, Mapping[str, Any]],
    quantity: Any,
    quote_timestamp: Optional[str] = None,
) -> CostBreakdown:
    """Basis 3 — the stage gate's executable round-trip cross, via the real
    exit_mark_corroboration.executable_roundtrip_cost (the SAME helper
    _apply_entry_roundtrip_gate calls). Carries BOTH the qty-scaled TOTAL and
    the 1-lot PER_STRUCTURE_CONTRACT so the E2 legacy-basis divergence is a
    typed difference, not a hidden unit pun."""
    from packages.quantum.analytics.exit_mark_corroboration import (
        executable_roundtrip_cost,
    )

    rt = executable_roundtrip_cost(
        legs=list(legs or []), leg_quotes=dict(leg_quotes or {}),
        quantity=quantity,
    )
    try:
        qty = abs(float(quantity)) if quantity is not None else None
    except (TypeError, ValueError):
        qty = None

    prov = Provenance(
        model_version=(
            f"exit_mark_corroboration.executable_roundtrip_cost@{_FROZEN}"
        ),
        quote_timestamp=quote_timestamp,
        source_detail=f"quote_complete={bool(rt.get('quote_complete'))}",
    )

    components: List[CostComponent] = []
    if rt.get("round_trip") is not None:
        components.append(CostComponent(
            name="round_trip_total",
            source=CostSource.STAGE_EXECUTABLE_CROSS,
            side=CostSide.ROUND_TRIP, basis=CostBasisKind.EXECUTABLE,
            unit=CostUnit.TOTAL, amount_usd=float(rt["round_trip"]),
            quantity=qty, provenance=prov,
        ))
        components.append(CostComponent(
            name="round_trip_per_contract",
            source=CostSource.STAGE_EXECUTABLE_CROSS,
            side=CostSide.ROUND_TRIP, basis=CostBasisKind.EXECUTABLE,
            unit=CostUnit.PER_STRUCTURE_CONTRACT,
            amount_usd=float(rt["round_trip_per_contract"]),
            quantity=qty, provenance=prov,
        ))
    else:
        for name, unit in (
            ("round_trip_total", CostUnit.TOTAL),
            ("round_trip_per_contract", CostUnit.PER_STRUCTURE_CONTRACT),
        ):
            components.append(CostComponent.make_unavailable(
                name, CostSource.STAGE_EXECUTABLE_CROSS, CostSide.ROUND_TRIP,
                CostBasisKind.EXECUTABLE, unit,
                "leg_quote_incomplete", quantity=qty, provenance=prov,
            ))

    # Per-leg 1-lot crosses — informational, typed per leg.
    for leg in rt.get("per_leg") or []:
        occ = leg.get("occ")
        bid, ask = leg.get("bid"), leg.get("ask")
        if bid is not None and ask is not None:
            components.append(CostComponent(
                name=f"leg_cross:{occ}",
                source=CostSource.STAGE_EXECUTABLE_CROSS,
                side=CostSide.ROUND_TRIP, basis=CostBasisKind.EXECUTABLE,
                unit=CostUnit.PER_LEG,
                amount_usd=(float(ask) - float(bid)) * OPTION_MULTIPLIER,
                quantity=leg.get("contracts"), provenance=prov,
            ))
        else:
            missing = ",".join(
                n for n, v in (("bid", bid), ("ask", ask)) if v is None
            )
            components.append(CostComponent.make_unavailable(
                f"leg_cross:{occ}", CostSource.STAGE_EXECUTABLE_CROSS,
                CostSide.ROUND_TRIP, CostBasisKind.EXECUTABLE,
                CostUnit.PER_LEG, f"leg_quote_missing:{missing}",
                quantity=leg.get("contracts"), provenance=prov,
            ))

    return CostBreakdown(
        source=CostSource.STAGE_EXECUTABLE_CROSS, side=CostSide.ROUND_TRIP,
        basis=CostBasisKind.EXECUTABLE, components=tuple(components),
        primary="round_trip_total", quantity=qty, provenance=prov,
    )


def executable_side_cost(
    breakdown: CostBreakdown, side: CostSide
) -> CostComponent:
    """Entry/exit half of the stage executable round trip (mid-reference
    convention: each direction crosses half the full width per leg, so the
    two sides are symmetric halves of round_trip_total — see
    exit_mark_corroboration.py:407-411)."""
    if side not in (CostSide.ENTRY, CostSide.EXIT):
        raise ValueError("side must be ENTRY or EXIT")
    total = breakdown.component("round_trip_total")
    if total is None or not total.available:
        return CostComponent.make_unavailable(
            f"{side.value}_cross", breakdown.source, side,
            breakdown.basis, CostUnit.TOTAL,
            (total.unavailable_reason if total else "round_trip_total_missing"),
            quantity=breakdown.quantity,
            provenance=total.provenance if total else None,
        )
    return CostComponent(
        name=f"{side.value}_cross", source=breakdown.source, side=side,
        basis=breakdown.basis, unit=CostUnit.TOTAL,
        amount_usd=float(total.amount_usd) / 2.0,
        quantity=breakdown.quantity, provenance=total.provenance,
    )


def extract_tcm_estimate(
    *,
    ticket: Any,
    quote: Optional[Mapping[str, Any]],
    config: Any = None,
    quote_timestamp: Optional[str] = None,
) -> CostBreakdown:
    """Basis 4a — execution/transaction_cost_model.TransactionCostModel
    .estimate, called for real. Its fees are ONE-WAY and LEG-COUNT-BLIND
    (qty x 0.65, transaction_cost_model.py:151-152) and its spread cost is a
    single-quote half-cross — both frozen facts stamped into provenance.
    A missing/zero quote makes production FABRICATE bid/ask at +/-1% of the
    limit price; that path is reproduced exactly but flagged fallback=True."""
    from packages.quantum.execution.transaction_cost_model import (
        TransactionCostModel,
    )
    from packages.quantum.strategy_profiles import CostModelConfig

    cfg = config or CostModelConfig()
    result = TransactionCostModel.estimate(
        ticket=ticket, quote=dict(quote) if quote else None, config=cfg,
    )
    try:
        qty = abs(float(getattr(ticket, "quantity", None)))
    except (TypeError, ValueError):
        qty = None

    fallback = bool(result.get("used_fallback"))
    detail = (
        f"missing_quote={bool(result.get('missing_quote'))}"
        f",used_fallback={fallback}"
        + (",fabricated_pm1pct_of_limit" if fallback else "")
    )
    prov = Provenance(
        model_version=(
            "execution.TransactionCostModel.estimate@"
            f"{result.get('tcm_version')}/{_FROZEN}"
        ),
        quote_timestamp=quote_timestamp,
        source_detail=detail,
        fallback=fallback,
    )
    fees = CostComponent(
        name="fees",
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=float(result["fees_usd"]), quantity=qty,
        provenance=Provenance(
            model_version=prov.model_version,
            quote_timestamp=quote_timestamp,
            source_detail="one_way_leg_count_blind_qty_x_commission",
        ),
    )
    spread_cost = CostComponent(
        name="expected_spread_cost",
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=float(result["expected_spread_cost_usd"]), quantity=qty,
        provenance=Provenance(
            model_version=prov.model_version,
            quote_timestamp=quote_timestamp,
            source_detail="half_cross_single_quote_leg1_only," + detail,
            fallback=fallback,
        ),
    )
    slippage = CostComponent(
        name="expected_slippage",
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=float(result["expected_slippage_usd"]), quantity=qty,
        provenance=Provenance(
            model_version=prov.model_version,
            quote_timestamp=quote_timestamp,
            source_detail=f"bps_of_notional={cfg.spread_slippage_bps}," + detail,
            fallback=fallback,
        ),
    )
    total = CostComponent(
        name="tcm_total",
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=(
            float(result["fees_usd"])
            + float(result["expected_spread_cost_usd"])
            + float(result["expected_slippage_usd"])
        ),
        quantity=qty, provenance=prov,
    )
    return CostBreakdown(
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED,
        components=(total, fees, spread_cost, slippage),
        primary="tcm_total", quantity=qty, provenance=prov,
    )


def extract_legacy_tcm_estimate(
    *,
    price: Optional[float],
    quantity: Optional[float],
    side: str = "buy",
    config: Any = None,
) -> CostBreakdown:
    """Basis 4b — the SECOND class named TransactionCostModel
    (services/transaction_cost_model.py:21-29, legacy; consumers:
    historical_simulation + backtest LegacyTCM). Its slippage term carries NO
    option multiplier (price x bps x qty) — a frozen fact stamped into
    provenance, formalized here so the two same-named models stop being
    conflated."""
    prov = Provenance(
        model_version=f"services.TransactionCostModel.estimate_costs@{_FROZEN}",
        source_detail="legacy_no_option_multiplier",
    )
    if price is None or quantity is None:
        missing = ",".join(
            n for n, v in (("price", price), ("quantity", quantity))
            if v is None
        )
        comp = CostComponent.make_unavailable(
            "legacy_estimate_total", CostSource.TCM, CostSide.ENTRY,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            f"legacy_tcm_inputs_missing:{missing}",
            quantity=quantity, provenance=prov,
        )
        return CostBreakdown(
            source=CostSource.TCM, side=CostSide.ENTRY,
            basis=CostBasisKind.ESTIMATED, components=(comp,),
            primary="legacy_estimate_total", quantity=quantity,
            provenance=prov,
        )

    from packages.quantum.services.transaction_cost_model import (
        TransactionCostModel as LegacyTCM,
    )

    model = LegacyTCM(config) if config is not None else LegacyTCM()
    amount = model.estimate_costs(
        price=float(price), quantity=float(quantity), side=side
    )
    comp = CostComponent(
        name="legacy_estimate_total",
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=float(amount), quantity=quantity, provenance=prov,
    )
    return CostBreakdown(
        source=CostSource.TCM, side=CostSide.ENTRY,
        basis=CostBasisKind.ESTIMATED, components=(comp,),
        primary="legacy_estimate_total", quantity=quantity, provenance=prov,
    )


@dataclass(frozen=True)
class RealizedCloseCosts:
    breakdown: CostBreakdown
    gap_fraction: Optional[float]


def extract_realized_close_costs(
    *,
    order_json: Optional[Mapping[str, Any]],
    broker_fill: Any,
    quantity: Optional[float],
) -> RealizedCloseCosts:
    """Basis 5 — the realized comparison, via the real close_fill_gap keys:
    read_stamp (stage-stamped cross/mid, signed mark basis),
    broker_fill_to_mark_basis (fill = NEGATION of the broker mleg net fill),
    compute_gap_fraction. Mark-basis prices are surfaced in USD per
    structure-contract (x100); a missing stamp / fill is typed UNAVAILABLE
    (older unstamped orders log fill-only in production, gap=NA)."""
    from packages.quantum.services.close_fill_gap import (
        broker_fill_to_mark_basis,
        compute_gap_fraction,
        read_stamp,
    )

    cross, mid = read_stamp(dict(order_json) if order_json else None)
    fill = broker_fill_to_mark_basis(broker_fill)
    gap = compute_gap_fraction(cross, mid, fill)

    prov = Provenance(
        model_version=f"services.close_fill_gap@{_FROZEN}",
        source_detail="signed_mark_basis;fill=-broker_net_fill",
    )

    def _mark_component(
        name: str, value: Optional[float], basis: CostBasisKind, reason: str
    ) -> CostComponent:
        if value is None:
            return CostComponent.make_unavailable(
                name, CostSource.REALIZED, CostSide.EXIT, basis,
                CostUnit.PER_STRUCTURE_CONTRACT, reason,
                quantity=quantity, provenance=prov,
            )
        return CostComponent(
            name=name, source=CostSource.REALIZED, side=CostSide.EXIT,
            basis=basis, unit=CostUnit.PER_STRUCTURE_CONTRACT,
            amount_usd=float(value) * OPTION_MULTIPLIER,
            quantity=quantity, provenance=prov,
        )

    cross_c = _mark_component(
        "stage_cross_mark", cross, CostBasisKind.EXECUTABLE,
        "order_json_stamp_missing:cross",
    )
    mid_c = _mark_component(
        "trigger_mid_mark", mid, CostBasisKind.ESTIMATED,
        "order_json_stamp_missing:mid",
    )
    fill_c = _mark_component(
        "realized_fill_mark", fill, CostBasisKind.REALIZED,
        "broker_fill_missing",
    )

    qty_f: Optional[float]
    try:
        qty_f = abs(float(quantity)) if quantity is not None else None
    except (TypeError, ValueError):
        qty_f = None
    if mid is not None and fill is not None and qty_f:
        slip = CostComponent(
            name="realized_slippage_vs_mid",
            source=CostSource.REALIZED, side=CostSide.EXIT,
            basis=CostBasisKind.REALIZED, unit=CostUnit.TOTAL,
            amount_usd=(float(mid) - float(fill)) * OPTION_MULTIPLIER * qty_f,
            quantity=qty_f, provenance=prov,
        )
    else:
        missing = [
            n for n, v in (
                ("mid", mid), ("fill", fill), ("quantity", qty_f)
            ) if not v and v != 0.0
        ]
        slip = CostComponent.make_unavailable(
            "realized_slippage_vs_mid", CostSource.REALIZED, CostSide.EXIT,
            CostBasisKind.REALIZED, CostUnit.TOTAL,
            f"realized_inputs_missing:{','.join(missing) or 'unknown'}",
            quantity=qty_f, provenance=prov,
        )

    breakdown = CostBreakdown(
        source=CostSource.REALIZED, side=CostSide.EXIT,
        basis=CostBasisKind.REALIZED,
        components=(fill_c, cross_c, mid_c, slip),
        primary="realized_fill_mark", quantity=qty_f, provenance=prov,
    )
    return RealizedCloseCosts(breakdown=breakdown, gap_fraction=gap)


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation report — observe-only artifact (dataclass/dict; no DB write,
# no job, no decision).
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostDelta:
    """One typed cross-basis difference. amount_usd is None + available=False
    when either input is UNAVAILABLE — never a fabricated zero."""

    name: str
    amount_usd: Optional[float]
    available: bool
    reason: Optional[str] = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "amount_usd": self.amount_usd,
            "available": self.available,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class EvBasisFlag:
    """Which EV basis each comparison rides. The ranker's suggestion["ev"] is
    CALIBRATED when apply-at-scoring is armed; the stage gate's
    ticket.expected_value is the gross ticket EV."""

    gross_ev: Optional[float]
    calibrated_ev: Optional[float]
    flag: str  # calibrated_and_raw_diverge | raw_only | calibrated_only | equal | unknown
    delta: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gross_ev": self.gross_ev,
            "calibrated_ev": self.calibrated_ev,
            "flag": self.flag,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class CostReconciliation:
    quantity: Optional[float]
    normalized: Mapping[str, Mapping[str, Any]]
    deltas: Tuple[CostDelta, ...]
    ev_basis: EvBasisFlag
    flags: Tuple[str, ...]
    model_version: str = MODEL_VERSION

    def delta(self, name: str) -> Optional[CostDelta]:
        for d in self.deltas:
            if d.name == name:
                return d
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "model_version": self.model_version,
            "quantity": self.quantity,
            "normalized": {k: dict(v) for k, v in self.normalized.items()},
            "deltas": [d.as_dict() for d in self.deltas],
            "ev_basis": self.ev_basis.as_dict(),
            "flags": list(self.flags),
        }


def _normalized_entry(
    breakdown: Optional[CostBreakdown], quantity: Optional[float]
) -> Optional[Dict[str, Any]]:
    if breakdown is None:
        return None
    primary = breakdown.primary_component
    if primary.quantity is None and quantity is not None:
        # Re-key for conversion without mutating the original.
        primary = CostComponent(
            name=primary.name, source=primary.source, side=primary.side,
            basis=primary.basis, unit=primary.unit,
            amount_usd=primary.amount_usd, quantity=quantity,
            multiplier=primary.multiplier, available=primary.available,
            unavailable_reason=primary.unavailable_reason,
            provenance=primary.provenance,
        ) if primary.available else CostComponent.make_unavailable(
            primary.name, primary.source, primary.side, primary.basis,
            primary.unit, primary.unavailable_reason or "unavailable",
            quantity=quantity, provenance=primary.provenance,
        )
    out: Dict[str, Any] = {
        "primary": primary.name,
        "side": breakdown.side.value,
        "basis": breakdown.basis.value,
    }
    for label, unit in (
        ("total_usd", CostUnit.TOTAL),
        ("per_structure_contract_usd", CostUnit.PER_STRUCTURE_CONTRACT),
    ):
        conv = primary.in_unit(unit)
        if conv.available:
            out[label] = conv.amount_usd
        else:
            out[label] = UNAVAILABLE
            out[f"{label}_reason"] = conv.unavailable_reason
    return out


def _pair_delta(
    name: str,
    a: Optional[CostComponent],
    b: Optional[CostComponent],
    detail: Optional[Dict[str, Any]] = None,
) -> CostDelta:
    """a − b, typed-unavailable when either side is missing/unavailable."""
    detail = dict(detail or {})
    if a is None or b is None or not a.available or not b.available:
        reasons = []
        for label, c in (("a", a), ("b", b)):
            if c is None:
                reasons.append(f"{label}=missing")
            elif not c.available:
                reasons.append(f"{label}={c.unavailable_reason}")
        return CostDelta(
            name=name, amount_usd=None, available=False,
            reason=";".join(reasons) or "inputs_unavailable", detail=detail,
        )
    detail.setdefault("a_usd", a.amount_usd)
    detail.setdefault("b_usd", b.amount_usd)
    return CostDelta(
        name=name,
        amount_usd=float(a.amount_usd) - float(b.amount_usd),
        available=True, detail=detail,
    )


def reconcile_cost_bases(
    *,
    quantity: Optional[float],
    gross_ev: Optional[float] = None,
    calibrated_ev: Optional[float] = None,
    scanner: Optional[CostBreakdown] = None,
    scanner_unified: Optional[CostBreakdown] = None,
    ranker: Optional[CostBreakdown] = None,
    stage: Optional[CostBreakdown] = None,
    tcm: Optional[CostBreakdown] = None,
    tcm_legacy: Optional[CostBreakdown] = None,
    realized: Optional[RealizedCloseCosts] = None,
) -> CostReconciliation:
    """Given one candidate's extracted breakdowns, produce every basis
    normalized to comparable units plus the typed differences. PURE:
    dict/dataclass out, no DB write, no job, no decision."""
    flags: List[str] = []
    deltas: List[CostDelta] = []

    normalized: Dict[str, Dict[str, Any]] = {}
    for key, bd in (
        ("scanner_estimate", scanner),
        ("scanner_unified_final", scanner_unified),
        ("ranker_model", ranker),
        ("stage_executable_cross", stage),
        ("tcm", tcm),
        ("tcm_legacy", tcm_legacy),
        ("realized", realized.breakdown if realized else None),
    ):
        entry = _normalized_entry(bd, quantity)
        if entry is not None:
            normalized[key] = entry
    if realized is not None:
        normalized["realized"]["gap_fraction"] = realized.gap_fraction

    # ── fee-model delta: ranker round-trip fees vs TCM one-way fees ────────
    ranker_fees = ranker.component("round_trip_fees") if ranker else None
    tcm_fees = tcm.component("fees") if tcm else None
    deltas.append(_pair_delta(
        "fee_model_ranker_round_trip_vs_tcm_one_way",
        ranker_fees, tcm_fees,
        detail={"note": "ranker=0.65*contracts*legs*2; tcm=0.65*qty one-way leg-blind"},
    ))
    if scanner is not None and ranker is not None:
        flags.append("scanner_commission_one_side_embedded_vs_ranker_round_trip")
    if tcm is not None:
        flags.append("tcm_fee_leg_count_blind")
        if tcm.provenance and tcm.provenance.fallback:
            flags.append("tcm_quote_fallback_fabricated")

    # ── slippage-proxy vs executable-cross delta (the SOFI class) ──────────
    stage_total = stage.component("round_trip_total") if stage else None
    ranker_slip = ranker.component("expected_slippage") if ranker else None
    deltas.append(_pair_delta(
        "slippage_executable_cross_vs_ranker_proxy",
        stage_total, ranker_slip,
        detail={"note": "positive = the ranker proxy understates the executable cross"},
    ))
    if (
        ranker_slip is not None and ranker_slip.available
        and ranker_slip.provenance and ranker_slip.provenance.fallback
    ):
        flags.append("ranker_slippage_five_pct_ev_floor_proxy")

    # ── quantity-scaling delta (the E2 legacy-basis wrinkle) ───────────────
    stage_pc = stage.component("round_trip_per_contract") if stage else None
    qty_detail: Dict[str, Any] = {
        "note": (
            "legacy live gate: per-structure gross_ev - TOTAL round_trip; "
            "fixed: gross_ev - per_contract (GATE_QTY_FIX_LIVE_ENABLED)"
        ),
    }
    if (
        gross_ev is not None
        and stage_total is not None and stage_total.available
        and stage_pc is not None and stage_pc.available
    ):
        qty_detail["legacy_net"] = float(gross_ev) - float(stage_total.amount_usd)
        qty_detail["fixed_net"] = float(gross_ev) - float(stage_pc.amount_usd)
    delta_qty = _pair_delta(
        "quantity_scaling_stage_total_vs_per_contract",
        stage_total, stage_pc, detail=qty_detail,
    )
    deltas.append(delta_qty)
    if (
        delta_qty.available
        and quantity is not None and float(quantity) > 1
        and abs(delta_qty.amount_usd or 0.0) > 0
    ):
        flags.append("legacy_gate_basis_divergent_qty_gt_1")

    # ── modeled scanner estimate vs executable cross, per contract ─────────
    scanner_pc = (
        (scanner_unified or scanner).primary_component
        if (scanner_unified or scanner) else None
    )
    deltas.append(_pair_delta(
        "scanner_modeled_vs_stage_executable_per_contract",
        stage_pc, scanner_pc,
        detail={"note": "positive = the scanner model understates the executable cross"},
    ))

    # ── realized vs stage cross (per contract, exit side only) ─────────────
    realized_fill = (
        realized.breakdown.component("realized_fill_mark") if realized else None
    )
    realized_cross = (
        realized.breakdown.component("stage_cross_mark") if realized else None
    )
    deltas.append(_pair_delta(
        "realized_fill_vs_stage_cross_mark",
        realized_fill, realized_cross,
        detail={"note": "signed mark basis x100; gap_fraction locates fill between cross and mid"},
    ))
    if realized is not None and (
        realized_cross is None or not realized_cross.available
    ):
        flags.append("realized_stamp_missing")

    # ── EV basis flag (calibrated vs raw) ──────────────────────────────────
    if gross_ev is not None and calibrated_ev is not None:
        ev_delta = float(calibrated_ev) - float(gross_ev)
        ev_flag = EvBasisFlag(
            gross_ev=float(gross_ev), calibrated_ev=float(calibrated_ev),
            flag=("calibrated_and_raw_diverge" if ev_delta != 0 else "equal"),
            delta=ev_delta,
        )
        if ev_delta != 0:
            flags.append("ranker_ev_calibrated_vs_stage_gate_gross_ev")
    elif gross_ev is not None:
        ev_flag = EvBasisFlag(
            gross_ev=float(gross_ev), calibrated_ev=None, flag="raw_only",
        )
    elif calibrated_ev is not None:
        ev_flag = EvBasisFlag(
            gross_ev=None, calibrated_ev=float(calibrated_ev),
            flag="calibrated_only",
        )
    else:
        ev_flag = EvBasisFlag(gross_ev=None, calibrated_ev=None, flag="unknown")

    return CostReconciliation(
        quantity=quantity,
        normalized=normalized,
        deltas=tuple(deltas),
        ev_basis=ev_flag,
        flags=tuple(flags),
    )
