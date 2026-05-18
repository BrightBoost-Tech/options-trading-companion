"""Portfolio-level capital allocator for small tier ($1k-$5k).

Implements the allocation-aware sizing policy specified in
``docs/small_tier_allocation.md``. Distributes capital across the
viable candidate set in a single cycle, replacing the per-trade
independent-sizing pattern previously used by
``SmallAccountCompounder.calculate_variable_sizing`` at the small
tier.

This is GAP 1 territory per ``CLAUDE.md`` "5 Open Code Gaps" —
specifically the portfolio-construction half. ``DynamicWeightService``
(packages/quantum/services/dynamic_weight_service.py) provides
per-segment SCORE multipliers but is not a portfolio allocator;
this module is independent.

Scope (this module DOES):
    - Apply a 85% × regime_mult global envelope
    - Subtract open-position cost basis from the envelope
    - Distribute capital across top N candidates (capped at 4 for
      small tier) using score-skewed proportional allocation
    - Apply a 36% per-trade ceiling
    - Return per-candidate allocated budgets

Scope (this module DOES NOT):
    - Modify the H7 round-trip safety check (downstream gate)
    - Re-rank candidates (caller pre-sorts by score)
    - Persist any state (pure function; caller persists)
    - Handle micro or standard tier (caller dispatches by tier)

H10 caveat (per docs/loud_error_doctrine.md "H10 — Stale state
cascades through pipeline gates"): the open-position cost basis
subtraction reads from caller-supplied open_positions. If
paper_positions has stale ghost rows, this allocator will
under-allocate. Caller must ensure open_positions reflects current
reality before invocation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# Regime multipliers — must match RiskBudgetEngine and
# SmallAccountCompounder for cross-layer consistency. See
# small_account_compounder.py calculate_variable_sizing for the
# canonical regime → multiplier mapping.
_REGIME_MULT = {
    "normal": 1.0,
    "suppressed": 0.9,
    "elevated": 0.8,
    "shock": 0.5,
    "chop": 1.0,
    "rebound": 1.0,
}

# Policy constants for small tier. Sized per docs/small_tier_allocation.md.
GLOBAL_ENVELOPE_PCT = 0.85       # 85% of equity × regime_mult
PER_TRADE_CEILING_PCT = 0.36     # 36% per-trade max
MAX_CONCURRENT_POSITIONS = 4     # Mirrors CapitalTier(name="small").max_trades
SCORE_SKEW_MIN = 0.8             # Same clamp as score_mult in compounder
SCORE_SKEW_MAX = 1.2


@dataclass(frozen=True)
class AllocationResult:
    """One candidate's allocated portfolio slot.

    Attributes:
        candidate: The original candidate dict (preserved verbatim
            so the caller can keep the score, strategy, sizing
            metadata it expects downstream).
        allocated_budget: Dollar budget for this candidate's
            max_loss, computed by the allocator. Caller passes
            this as ``allocation_hint`` to RiskBudgetEngine and
            SmallAccountCompounder.
        allocated_pct: Allocated budget as a fraction of total
            equity (for diagnostics).
        score_skew: The score-skew multiplier applied (for
            diagnostics / debug logging).
        ceiling_binding: True if the 36% per-trade ceiling clamped
            this allocation. Useful for surfacing concentrated
            allocations in observability.
    """
    candidate: Dict[str, Any]
    allocated_budget: float
    allocated_pct: float
    score_skew: float
    ceiling_binding: bool


def _normalize_regime(regime: Any) -> str:
    """Coerce regime input to lowercase string key for _REGIME_MULT.

    Accepts RegimeState enum, GlobalRegimeSnapshot, plain string,
    or anything with .state or .name. Matches the resilience pattern
    in RiskBudgetEngine._resolve_regime.
    """
    if regime is None:
        return "normal"
    # Try enum-style .name first (RegimeState.NORMAL.name == "NORMAL")
    name = getattr(regime, "name", None)
    if isinstance(name, str):
        return name.lower()
    # Try .state.value (GlobalRegimeSnapshot pattern)
    state = getattr(regime, "state", None)
    if state is not None:
        sub = getattr(state, "value", None) or getattr(state, "name", None)
        if isinstance(sub, str):
            return sub.lower()
    return str(regime).lower()


def _sum_open_cost_basis(open_positions: Sequence[Dict[str, Any]]) -> float:
    """Sum the cost basis of currently-open positions.

    Reads ``cost_basis`` field (absolute value) from each row. The
    cost_basis field convention in paper_positions is total dollar
    cost for the position (per-contract premium × 100 × quantity);
    this allocator treats it as already-USD without further
    multiplication.

    H10 caveat: caller must ensure open_positions reflects current
    reality. Ghost rows (closed externally but DB not reconciled)
    inflate this sum and shrink the available envelope — under-
    allocation rather than over-allocation, so the failure mode is
    safe but the operator gets fewer fills than expected.
    """
    total = 0.0
    for pos in open_positions or []:
        cb = pos.get("cost_basis")
        if cb is None:
            cb = pos.get("current_value", 0.0)
        try:
            total += abs(float(cb or 0.0))
        except (TypeError, ValueError):
            # Malformed row — skip rather than crash the allocator.
            logger.warning(
                "portfolio_allocator: skipping malformed open_position "
                "row (cost_basis=%r)", cb,
            )
    return total


def _median(values: Sequence[float]) -> float:
    """Median without numpy dep. Returns 0.0 for empty input."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def _score_skew(score: float, median_score: float) -> float:
    """Compute the score-skew multiplier per docs/small_tier_allocation.md.

    Formula: clamp(0.8 + (score - median_score) / 50 × 0.4, 0.8, 1.2).
    Highest score in the candidate set gets the highest multiplier
    (up to 1.2); lowest gets 0.8.
    """
    raw = 0.8 + (score - median_score) / 50.0 * 0.4
    return max(SCORE_SKEW_MIN, min(SCORE_SKEW_MAX, raw))


class PortfolioAllocator:
    """Allocation-aware sizing for small tier.

    Replaces small tier's per-trade ``3% × multipliers`` independent
    sizing with a candidate-set-aware allocator that distributes
    capital across viable candidates in a single cycle.

    See ``docs/small_tier_allocation.md`` for full spec, worked
    examples, and the policy rationale.

    Usage:
        allocator = PortfolioAllocator()
        results = allocator.allocate(
            candidates=scout_results,        # sorted by score desc
            total_equity=1500.0,
            regime="normal",
            open_positions=[],               # current paper_positions
        )
        for result in results:
            # result.candidate retains all original fields
            # result.allocated_budget is the per-trade max_loss budget
            ...
    """

    def __init__(
        self,
        global_envelope_pct: float = GLOBAL_ENVELOPE_PCT,
        per_trade_ceiling_pct: float = PER_TRADE_CEILING_PCT,
        max_concurrent_positions: int = MAX_CONCURRENT_POSITIONS,
    ):
        """Constructor accepts policy overrides for testing only.
        Production callers should use defaults."""
        self.global_envelope_pct = global_envelope_pct
        self.per_trade_ceiling_pct = per_trade_ceiling_pct
        self.max_concurrent_positions = max_concurrent_positions

    def allocate(
        self,
        candidates: List[Dict[str, Any]],
        total_equity: float,
        regime: Any = "normal",
        open_positions: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> List[AllocationResult]:
        """Allocate capital across the candidate set.

        Args:
            candidates: Candidate dicts with at least a ``score``
                field (numeric, 0-100). Sorted by caller, but
                allocator sorts again defensively. Each candidate
                dict is preserved verbatim in the returned
                AllocationResult.candidate.
            total_equity: Total account equity in USD. The 85%
                envelope and 36% per-trade ceiling are both
                percentages of this value.
            regime: Market regime — accepts RegimeState enum, plain
                string ("normal", "elevated", etc.), or
                GlobalRegimeSnapshot.
            open_positions: Currently-open positions, used for
                cost-basis subtraction. Empty / None / [] all
                interpreted as "no open positions."

        Returns:
            List of AllocationResult, one per allocated candidate
            (≤ ``max_concurrent_positions``). Empty list if there
            are no candidates OR available envelope is non-positive.

        Behavior notes:
            - No reduction of existing positions (single-cycle batch).
            - Top-N selection by score; ties broken by order.
            - 36% ceiling is per-trade; allocator does NOT pool
              ceiling-truncated remainder back to other candidates.
            - H7 round-trip safety is NOT checked here; downstream
              gate may drop candidates after allocation.
        """
        if not candidates or total_equity <= 0:
            return []

        regime_key = _normalize_regime(regime)
        regime_mult = _REGIME_MULT.get(regime_key, 1.0)

        envelope_dollars = total_equity * self.global_envelope_pct * regime_mult
        used_dollars = _sum_open_cost_basis(open_positions or [])
        available_envelope = max(0.0, envelope_dollars - used_dollars)

        if available_envelope <= 0:
            logger.info(
                "portfolio_allocator: envelope exhausted "
                "(equity=%.2f, envelope=%.2f, used=%.2f)",
                total_equity, envelope_dollars, used_dollars,
            )
            return []

        # Sort by score desc (defensive — caller should already do this)
        sorted_candidates = sorted(
            candidates,
            key=lambda c: float(c.get("score") or 0.0),
            reverse=True,
        )

        n_candidates = min(len(sorted_candidates), self.max_concurrent_positions)
        if n_candidates == 0:
            return []

        selected = sorted_candidates[:n_candidates]
        scores = [float(c.get("score") or 0.0) for c in selected]
        median_score = _median(scores)

        # Base allocation per slot is a fixed fraction of total equity.
        # The score-skew multiplier then adjusts each candidate's slot
        # individually, and the 36% ceiling clamps. The envelope
        # (with open-position subtraction) is enforced ONLY by capping
        # the per-candidate budget against the available envelope at
        # iteration time — see _budget_for_candidate.
        base_pct_per_slot = self.global_envelope_pct / n_candidates

        results: List[AllocationResult] = []
        remaining_envelope = available_envelope
        for cand in selected:
            score = float(cand.get("score") or 0.0)
            skew = _score_skew(score, median_score)
            raw_pct = base_pct_per_slot * skew
            ceiling_pct = self.per_trade_ceiling_pct
            ceiling_binding = raw_pct >= ceiling_pct
            final_pct = min(raw_pct, ceiling_pct)
            raw_budget = total_equity * final_pct
            # Final guard: don't allocate more than what's left in the
            # available envelope (after open-position subtraction).
            final_budget = min(raw_budget, remaining_envelope)
            if final_budget <= 0:
                # Envelope exhausted by prior allocations + open positions.
                break
            results.append(AllocationResult(
                candidate=cand,
                allocated_budget=final_budget,
                allocated_pct=final_budget / total_equity,
                score_skew=skew,
                ceiling_binding=ceiling_binding,
            ))
            remaining_envelope -= final_budget

        return results


__all__ = [
    "PortfolioAllocator",
    "AllocationResult",
    "GLOBAL_ENVELOPE_PCT",
    "PER_TRADE_CEILING_PCT",
    "MAX_CONCURRENT_POSITIONS",
]
