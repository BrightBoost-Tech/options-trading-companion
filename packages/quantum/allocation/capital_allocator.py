"""
Capital Allocation Layer — routes deployable capital across strategy
buckets and symbols based on regime, performance, and opportunity.

Pipeline:
1. Start with deployable capital
2. Subtract current exposure (risk in open positions)
3. Apply regime adjustment (reduce in high-vol)
4. Divide across strategy buckets (weighted by recent performance)
5. Within each bucket, divide across symbols (weighted by opportunity score)
6. Apply concentration limits from risk envelope
7. Output: AllocationPlan with per-symbol per-strategy targets

Layers on top of the existing RiskBudgetEngine and risk_envelope.
Does NOT replace them — provides finer-grained routing.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default strategy bucket weights (sum to 1.0)
DEFAULT_STRATEGY_WEIGHTS: Dict[str, float] = {
    "credit_put_spread": 0.30,
    "credit_call_spread": 0.15,
    "iron_condor": 0.20,
    "debit_call_spread": 0.15,
    "debit_put_spread": 0.10,
    "calendar": 0.10,
}

# Regime multipliers for total deployable fraction
REGIME_DEPLOYMENT_CAPS: Dict[str, float] = {
    "suppressed": 0.50,
    "normal": 0.40,
    "chop": 0.35,
    "rebound": 0.30,
    "elevated": 0.20,
    "shock": 0.05,
}

# Concentration guard defaults
DEFAULT_MAX_SYMBOL_ALLOC_PCT = 0.25   # Max 25% to one name
DEFAULT_MAX_STRATEGY_ALLOC_PCT = 0.40 # Max 40% to one strategy type


def is_allocation_v4_enabled() -> bool:
    """Feature flag for the v4 capital allocator."""
    return os.environ.get("ALLOCATION_V4_ENABLED", "").lower() in ("1", "true")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SymbolAllocation:
    """Allocation target for a single symbol within a strategy bucket."""
    symbol: str
    strategy: str
    max_dollars: float              # Max capital to deploy
    opportunity_score: float = 0.0  # Score that drove the allocation weight
    pct_of_bucket: float = 0.0     # What fraction of the bucket this represents

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "max_dollars": round(self.max_dollars, 2),
            "opportunity_score": round(self.opportunity_score, 2),
            "pct_of_bucket": round(self.pct_of_bucket, 4),
        }


@dataclass
class StrategyBucket:
    """Allocation for one strategy type."""
    strategy: str
    total_dollars: float
    weight: float                    # Original weight before adjustment
    regime_adj_weight: float         # Weight after regime adjustment
    allocations: List[SymbolAllocation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_dollars": round(self.total_dollars, 2),
            "weight": round(self.weight, 4),
            "regime_adj_weight": round(self.regime_adj_weight, 4),
            "symbols": [a.to_dict() for a in self.allocations],
        }


@dataclass
class AllocationPlan:
    """Complete capital allocation across all strategies and symbols."""
    deployable_capital: float
    current_exposure: float
    available_capital: float         # deployable - exposure
    regime_cap: float                # Fraction allowed by regime
    regime_label: str
    total_allocated: float = 0.0

    strategy_buckets: Dict[str, StrategyBucket] = field(default_factory=dict)

    # Quick lookup: symbol → max allocation (summed across strategies)
    symbol_totals: Dict[str, float] = field(default_factory=dict)

    # Diagnostics
    diagnostics: List[str] = field(default_factory=list)

    def get_allocation(self, symbol: str, strategy: str = "") -> float:
        """
        Get max allocation for a symbol, optionally within a strategy.

        If strategy is empty, returns total across all strategies.
        """
        if strategy:
            bucket = self.strategy_buckets.get(strategy)
            if not bucket:
                return 0.0
            for a in bucket.allocations:
                if a.symbol == symbol:
                    return a.max_dollars
            return 0.0
        return self.symbol_totals.get(symbol, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deployable_capital": round(self.deployable_capital, 2),
            "current_exposure": round(self.current_exposure, 2),
            "available_capital": round(self.available_capital, 2),
            "regime_cap": round(self.regime_cap, 4),
            "regime_label": self.regime_label,
            "total_allocated": round(self.total_allocated, 2),
            "strategy_buckets": {k: v.to_dict() for k, v in self.strategy_buckets.items()},
            "symbol_totals": {k: round(v, 2) for k, v in self.symbol_totals.items()},
            "diagnostics": self.diagnostics,
        }


# ---------------------------------------------------------------------------
# Core allocator
# ---------------------------------------------------------------------------

def compute_allocation(
    deployable_capital: float,
    current_positions: Optional[List[Dict]] = None,
    regime_label: str = "normal",
    regime_vector: Optional[Dict[str, float]] = None,
    candidates: Optional[List[Dict]] = None,
    strategy_weights: Optional[Dict[str, float]] = None,
    strategy_performance: Optional[Dict[str, float]] = None,
    max_symbol_alloc_pct: float = DEFAULT_MAX_SYMBOL_ALLOC_PCT,
    max_strategy_alloc_pct: float = DEFAULT_MAX_STRATEGY_ALLOC_PCT,
    policy_config: Optional[Dict[str, Any]] = None,
) -> AllocationPlan:
    """
    Compute capital allocation targets.

    Args:
        deployable_capital: Total deployable capital
        current_positions: List of open position dicts (for exposure calc)
        regime_label: Discrete regime label (normal, elevated, shock, etc.)
        regime_vector: Continuous regime vector dict (from v4 engine)
        candidates: List of opportunity candidates [{symbol, score, strategy}]
        strategy_weights: Override default strategy bucket weights
        strategy_performance: Recent strategy performance {strategy: sharpe_or_winrate}
        max_symbol_alloc_pct: Max fraction of total to one symbol
        max_strategy_alloc_pct: Max fraction of total to one strategy
        policy_config: Policy Lab cohort config overrides

    Returns:
        AllocationPlan with per-symbol per-strategy targets
    """
    plan = AllocationPlan(
        deployable_capital=deployable_capital,
        current_exposure=0.0,
        available_capital=0.0,
        regime_cap=0.0,
        regime_label=regime_label,
    )

    if deployable_capital <= 0:
        plan.diagnostics.append("no_capital")
        return plan

    # --- 1. Current exposure ---
    positions = current_positions or []
    exposure = _compute_current_exposure(positions)
    plan.current_exposure = exposure

    # --- 2. Available capital ---
    available = deployable_capital - exposure
    if available <= 0:
        plan.diagnostics.append("fully_deployed")
        plan.available_capital = 0.0
        return plan
    plan.available_capital = available

    # --- 3. Regime adjustment ---
    regime_cap = _get_regime_cap(regime_label, regime_vector)
    plan.regime_cap = regime_cap

    # Max deployable after regime cap
    max_deploy = deployable_capital * regime_cap
    regime_available = max(0, max_deploy - exposure)
    effective_available = min(available, regime_available)

    if effective_available <= 0:
        plan.diagnostics.append("regime_capped")
        return plan

    # --- 4. Strategy bucket weights ---
    weights = _compute_strategy_weights(
        strategy_weights or DEFAULT_STRATEGY_WEIGHTS,
        regime_label,
        strategy_performance,
        policy_config,
    )

    # --- 5. Distribute across buckets ---
    for strategy, weight in weights.items():
        bucket_dollars = effective_available * weight

        # Concentration cap per strategy
        max_strat = deployable_capital * max_strategy_alloc_pct
        bucket_dollars = min(bucket_dollars, max_strat)

        bucket = StrategyBucket(
            strategy=strategy,
            total_dollars=bucket_dollars,
            weight=(strategy_weights or DEFAULT_STRATEGY_WEIGHTS).get(strategy, 0),
            regime_adj_weight=weight,
        )

        # --- 6. Within bucket, allocate to symbols ---
        if candidates:
            strat_candidates = _filter_candidates_for_strategy(candidates, strategy)
            allocations = _allocate_within_bucket(
                strat_candidates, bucket_dollars, deployable_capital, max_symbol_alloc_pct,
            )
            bucket.allocations = allocations

        plan.strategy_buckets[strategy] = bucket
        plan.total_allocated += bucket_dollars

    # --- 7. Build symbol totals ---
    for bucket in plan.strategy_buckets.values():
        for alloc in bucket.allocations:
            plan.symbol_totals[alloc.symbol] = (
                plan.symbol_totals.get(alloc.symbol, 0) + alloc.max_dollars
            )

    # Apply symbol concentration cap to totals
    max_per_symbol = deployable_capital * max_symbol_alloc_pct
    for sym in plan.symbol_totals:
        if plan.symbol_totals[sym] > max_per_symbol:
            plan.symbol_totals[sym] = max_per_symbol
            plan.diagnostics.append(f"symbol_capped:{sym}")

    logger.info(
        f"capital_alloc: capital={deployable_capital:.0f} exposure={exposure:.0f} "
        f"available={effective_available:.0f} regime={regime_label} "
        f"cap={regime_cap:.2f} allocated={plan.total_allocated:.0f} "
        f"symbols={len(plan.symbol_totals)} buckets={len(plan.strategy_buckets)}"
    )

    return plan


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_current_exposure(positions: List[Dict]) -> float:
    """Sum risk exposure from open positions."""
    total = 0.0
    for pos in positions:
        max_credit = float(pos.get("max_credit") or 0)
        qty = abs(float(pos.get("quantity") or 1))
        entry = float(pos.get("avg_entry_price") or 0)

        if max_credit > 0:
            total += max_credit * qty * 100
        elif entry > 0:
            total += entry * qty * 100
    return total


def _get_regime_cap(regime_label: str, regime_vector: Optional[Dict] = None) -> float:
    """Get deployment cap from regime."""
    # Prefer continuous v4 vector if available
    if regime_vector:
        vol_regime = regime_vector.get("volatility_regime", 0.3)
        # Continuous mapping: vol 0.1 → 50%, vol 0.5 → 30%, vol 0.9 → 5%
        cap = max(0.05, 0.55 - vol_regime * 0.55)
        return cap

    # Fallback to discrete label
    return REGIME_DEPLOYMENT_CAPS.get(regime_label, 0.40)


def _compute_strategy_weights(
    base_weights: Dict[str, float],
    regime_label: str,
    performance: Optional[Dict[str, float]] = None,
    policy_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """
    Compute adjusted strategy weights.

    Adjustments:
    - Regime tilts (e.g., more credit in elevated vol)
    - Performance tilt (slight increase for recent winners)
    - Policy Lab cohort overrides
    """
    weights = dict(base_weights)

    # Regime tilts
    tilts = _regime_tilts(regime_label)
    for strat, tilt in tilts.items():
        if strat in weights:
            weights[strat] *= tilt

    # Performance tilt (max ±20% shift)
    if performance:
        perf_total = sum(abs(v) for v in performance.values()) or 1.0
        for strat, perf in performance.items():
            if strat in weights:
                # Normalize perf to [-1, 1] range, apply small tilt
                norm_perf = perf / perf_total
                weights[strat] *= (1.0 + 0.2 * norm_perf)

    # Policy Lab overrides
    if policy_config:
        # Cohort can specify custom weights
        custom = policy_config.get("strategy_weights")
        if custom and isinstance(custom, dict):
            for strat, w in custom.items():
                if strat in weights:
                    weights[strat] = w

    # Normalize to sum to 1.0
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    return weights


def _regime_tilts(regime_label: str) -> Dict[str, float]:
    """Regime-based strategy weight tilts (multipliers)."""
    tilts = {
        "suppressed": {
            "credit_put_spread": 0.8,
            "credit_call_spread": 0.8,
            "debit_call_spread": 1.3,
        },
        "normal": {},
        "elevated": {
            "credit_put_spread": 1.3,
            "credit_call_spread": 1.2,
            "iron_condor": 1.2,
            "debit_call_spread": 0.6,
        },
        "shock": {
            "credit_put_spread": 0.2,
            "credit_call_spread": 0.2,
            "iron_condor": 0.0,
            "debit_put_spread": 1.5,
        },
        "chop": {
            "iron_condor": 1.4,
            "calendar": 1.3,
            "debit_call_spread": 0.7,
        },
        "rebound": {
            "debit_call_spread": 1.3,
            "credit_put_spread": 1.2,
            "credit_call_spread": 0.6,
        },
    }
    return tilts.get(regime_label, {})


def _filter_candidates_for_strategy(
    candidates: List[Dict],
    strategy: str,
) -> List[Dict]:
    """Filter candidates that could be executed as the given strategy."""
    # If candidates have an explicit strategy type, match it
    # Otherwise, include all (the strategy bucket decides)
    result = []
    for c in candidates:
        c_strat = (c.get("strategy") or c.get("type") or "").lower()
        if not c_strat or strategy.lower() in c_strat or c_strat in strategy.lower():
            result.append(c)
        # Also include high-score candidates regardless of strategy match
        elif float(c.get("score") or 0) >= 80:
            result.append(c)
    return result if result else candidates  # Fallback: all candidates


def _allocate_within_bucket(
    candidates: List[Dict],
    bucket_dollars: float,
    total_capital: float,
    max_symbol_pct: float,
) -> List[SymbolAllocation]:
    """
    Distribute a strategy bucket's capital across symbols.

    Weighted by opportunity score (higher score → more capital).
    Capped by per-symbol concentration limit.
    """
    if not candidates or bucket_dollars <= 0:
        return []

    # Score-weighted allocation
    scored = []
    for c in candidates:
        score = float(c.get("score") or 0)
        symbol = c.get("symbol") or c.get("ticker") or "?"
        strategy = c.get("strategy") or c.get("type") or "unknown"
        if score > 0:
            scored.append((symbol, strategy, score))

    if not scored:
        return []

    total_score = sum(s for _, _, s in scored)
    if total_score <= 0:
        return []

    max_per_symbol = total_capital * max_symbol_pct
    allocations = []

    for symbol, strategy, score in scored:
        weight = score / total_score
        dollars = min(bucket_dollars * weight, max_per_symbol)

        allocations.append(SymbolAllocation(
            symbol=symbol,
            strategy=strategy,
            max_dollars=round(dollars, 2),
            opportunity_score=score,
            pct_of_bucket=round(weight, 4),
        ))

    return allocations
