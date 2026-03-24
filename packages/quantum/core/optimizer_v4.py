"""
Optimizer V4 — Utility-maximizing portfolio optimizer with risk envelope constraints.

Replaces the score-ranked selection with constrained optimization that:
1. Accepts ForecastSet (return distributions per symbol)
2. Maximizes expected utility (not just EV) subject to risk envelope
3. Uses Kelly-fraction sizing adjusted for forecast confidence
4. Accounts for correlation between candidates
5. Outputs ranked list with optimal contracts per candidate

Objective:
  maximize Σ(kelly_i × utility_i)
  subject to:
    - portfolio delta within limits
    - portfolio vega within limits
    - concentration within limits
    - total risk within budget
    - PDT day trade constraint (when enabled)

Feature flag: OPTIMIZER_V4_ENABLED (default false)
When disabled, the existing SurrogateOptimizer + SmallAccountCompounder run as before.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


def is_optimizer_v4_enabled() -> bool:
    return os.environ.get("OPTIMIZER_V4_ENABLED", "").lower() in ("1", "true")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CandidateInput:
    """One candidate trade for optimization."""
    symbol: str
    strategy: str
    max_profit: float                  # Max profit in dollars (1 contract)
    max_loss: float                    # Max loss in dollars (1 contract, positive)
    collateral: float                  # Buying power per contract
    prob_profit: float                 # P(profit)
    ev_amount: float                   # Expected value in dollars
    score: float = 0.0                 # Opportunity score (0-100)
    forecast_mean: float = 0.0         # Annualized return forecast
    forecast_std: float = 0.25         # Annualized vol forecast
    forecast_confidence: float = 0.5   # 0-1 data quality
    delta_per_contract: float = 0.0    # Portfolio delta contribution
    vega_per_contract: float = 0.0     # Portfolio vega contribution
    theta_per_contract: float = 0.0    # Portfolio theta contribution
    is_same_day: bool = False          # PDT flag

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


@dataclass
class OptimizedPosition:
    """Output: one position with optimal sizing."""
    symbol: str
    strategy: str
    contracts: int
    kelly_fraction: float              # Raw Kelly fraction
    adjusted_fraction: float           # After confidence + correlation adjustment
    expected_utility: float            # Utility contribution
    capital_required: float
    risk_dollars: float                # Max loss × contracts
    rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


@dataclass
class OptimizationResult:
    """Complete optimization output."""
    positions: List[OptimizedPosition] = field(default_factory=list)
    total_capital_used: float = 0.0
    total_risk: float = 0.0
    portfolio_delta: float = 0.0
    portfolio_vega: float = 0.0
    objective_value: float = 0.0
    solver_status: str = ""
    diagnostics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "positions": [p.to_dict() for p in self.positions],
            "total_capital_used": round(self.total_capital_used, 2),
            "total_risk": round(self.total_risk, 2),
            "portfolio_delta": round(self.portfolio_delta, 4),
            "portfolio_vega": round(self.portfolio_vega, 4),
            "objective_value": round(self.objective_value, 4),
            "solver_status": self.solver_status,
            "diagnostics": self.diagnostics,
        }


# ---------------------------------------------------------------------------
# Kelly fraction computation
# ---------------------------------------------------------------------------

def compute_kelly_fraction(
    prob_profit: float,
    max_profit: float,
    max_loss: float,
    confidence: float = 1.0,
) -> float:
    """
    Kelly criterion for binary-outcome option trades.

    For a trade with probability p of winning W and (1-p) of losing L:
      EV = p*W - q*L
      f* = EV / L  (fraction of bankroll to risk)

    This works for credit spreads where W < L and p > 0.5.
    Example: credit spread W=$200, L=$800, p=0.70
      EV = 0.70*200 - 0.30*800 = 140 - 240 = -100 → negative, f=0
    Example: credit spread W=$200, L=$800, p=0.85
      EV = 0.85*200 - 0.15*800 = 170 - 120 = 50
      f = 50/800 = 0.0625 → risk 6.25% of bankroll

    Adjusted: half-Kelly × confidence for real trading.
    """
    if max_loss <= 0 or max_profit <= 0 or prob_profit <= 0:
        return 0.0

    p = min(max(prob_profit, 0.01), 0.99)
    q = 1.0 - p

    ev = p * max_profit - q * max_loss

    if ev <= 0:
        return 0.0

    # Kelly fraction: fraction of bankroll to risk
    kelly = ev / max_loss

    # Half-Kelly scaled by confidence
    adjusted = kelly * 0.5 * max(0.1, min(1.0, confidence))

    # Hard cap at 15% per position
    return min(adjusted, 0.15)


# ---------------------------------------------------------------------------
# Correlation estimation
# ---------------------------------------------------------------------------

def estimate_correlation_penalty(
    candidates: List[CandidateInput],
) -> np.ndarray:
    """
    Estimate pairwise correlation penalty between candidates.

    Simple heuristic: same symbol = 1.0, same sector proxy (first letter) = 0.5, else 0.2
    Returns correlation matrix (n × n).
    """
    n = len(candidates)
    corr = np.eye(n)

    for i in range(n):
        for j in range(i + 1, n):
            if candidates[i].symbol == candidates[j].symbol:
                c = 0.95  # Same name
            elif candidates[i].symbol[:2] == candidates[j].symbol[:2]:
                c = 0.5   # Similar names (rough proxy)
            else:
                c = 0.2   # Default low correlation

            corr[i, j] = c
            corr[j, i] = c

    return corr


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------

def optimize_portfolio_v4(
    candidates: List[CandidateInput],
    available_capital: float,
    risk_budget: float,
    max_portfolio_delta: float = 0.0,
    max_portfolio_vega: float = 0.0,
    max_concentration_pct: float = 0.25,
    pdt_day_trades_remaining: int = 99,
    risk_aversion: float = 2.0,
) -> OptimizationResult:
    """
    Optimize trade selection and sizing using constrained utility maximization.

    Args:
        candidates: List of CandidateInput objects
        available_capital: Deployable capital in dollars
        risk_budget: Max total risk in dollars
        max_portfolio_delta: Portfolio delta limit (0 = no limit)
        max_portfolio_vega: Portfolio vega limit (0 = no limit)
        max_concentration_pct: Max fraction of capital in one name
        pdt_day_trades_remaining: PDT constraint
        risk_aversion: Lambda for variance penalty

    Returns:
        OptimizationResult with sized positions
    """
    result = OptimizationResult()
    n = len(candidates)

    if n == 0 or available_capital <= 0 or risk_budget <= 0:
        result.diagnostics.append("no_candidates_or_capital")
        result.solver_status = "empty"
        return result

    # --- 1. Compute Kelly fractions and utilities ---
    kelly_fracs = np.zeros(n)
    utilities = np.zeros(n)
    max_contracts = np.zeros(n)

    for i, c in enumerate(candidates):
        kelly_fracs[i] = compute_kelly_fraction(
            c.prob_profit, c.max_profit, c.max_loss, c.forecast_confidence,
        )

        # Utility = Kelly-scaled EV (positive when Kelly > 0)
        # Kelly already encodes the EV/risk tradeoff correctly, so utility
        # is simply the rate of geometric growth if we bet kelly_frac.
        # Utility = kelly × EV = growth rate contribution per unit allocated
        ev = c.ev_amount
        utilities[i] = kelly_fracs[i] * max(0, ev) + c.score * 0.01

        # Max contracts by capital and risk
        if c.collateral > 0:
            max_by_capital = available_capital * max_concentration_pct / c.collateral
        else:
            max_by_capital = 10

        if c.max_loss > 0:
            max_by_risk = risk_budget * max_concentration_pct / c.max_loss
        else:
            max_by_risk = 10

        max_contracts[i] = max(0, min(max_by_capital, max_by_risk, 20))

    # --- 2. Correlation penalty ---
    corr_matrix = estimate_correlation_penalty(candidates)

    # --- 3. Optimization ---
    # Decision variable: fraction of capital to allocate to each candidate [0, kelly_i]
    # We optimize continuous fractions then convert to contracts

    def objective(w):
        """Negative utility (minimize)."""
        # Utility: sum of kelly-weighted expected utilities
        util = -np.dot(w, utilities)

        # Correlation penalty: penalize overlapping allocations
        corr_penalty = risk_aversion * 0.5 * w @ corr_matrix @ w * np.mean(np.abs(utilities))

        return util + corr_penalty

    # Constraints
    cons = []

    # Total allocation <= 1.0 (can be less)
    cons.append({"type": "ineq", "fun": lambda w: 1.0 - np.sum(w)})

    # Total risk within budget
    risk_per_unit = np.array([c.max_loss for c in candidates])
    if risk_budget > 0 and np.any(risk_per_unit > 0):
        cons.append({
            "type": "ineq",
            "fun": lambda w: risk_budget - np.dot(w * available_capital / np.maximum(risk_per_unit, 1), risk_per_unit),
        })

    # Greeks constraints — scale w to estimated contracts for greek computation
    # w[i] × capital / collateral[i] ≈ contracts, then × greek_per_contract
    collateral_vec = np.array([max(c.collateral, 1) for c in candidates])

    if max_portfolio_delta > 0:
        delta_vec = np.array([c.delta_per_contract for c in candidates])
        def delta_constraint(w, d=delta_vec, c=collateral_vec, cap=available_capital, lim=max_portfolio_delta):
            contracts_est = w * cap / c
            return lim - abs(np.dot(contracts_est, d))
        cons.append({"type": "ineq", "fun": delta_constraint})

    if max_portfolio_vega > 0:
        vega_vec = np.array([c.vega_per_contract for c in candidates])
        def vega_constraint(w, v=vega_vec, c=collateral_vec, cap=available_capital, lim=max_portfolio_vega):
            contracts_est = w * cap / c
            return lim - abs(np.dot(contracts_est, v))
        cons.append({"type": "ineq", "fun": vega_constraint})

    # PDT: limit same-day candidates
    same_day_mask = np.array([1.0 if c.is_same_day else 0.0 for c in candidates])
    if pdt_day_trades_remaining < 99 and np.sum(same_day_mask) > 0:
        cons.append({
            "type": "ineq",
            "fun": lambda w, m=same_day_mask, r=pdt_day_trades_remaining: (
                r - np.sum(np.where((w > 0.001) & (m > 0), 1, 0))
            ),
        })

    # Bounds: [0, concentration_cap] per candidate, scaled by Kelly attractiveness
    # Kelly determines the ideal max, but we allow up to concentration cap
    bounds = [
        (0.0, max(0.001, min(max_concentration_pct, kelly_fracs[i] * 3)))
        for i in range(n)
    ]

    # Initial guess: Kelly-proportional, summing to ~50% of capacity
    kelly_sum = sum(kelly_fracs) or 1.0
    init = np.array([
        kelly_fracs[i] / kelly_sum * 0.5 * min(1.0, max_concentration_pct * n)
        for i in range(n)
    ])
    # Clip to bounds
    init = np.clip(init, [b[0] for b in bounds], [b[1] for b in bounds])

    # Solve
    try:
        opt = minimize(
            objective, init, method="SLSQP",
            bounds=bounds, constraints=cons,
            options={"maxiter": 500, "ftol": 1e-8},
        )
        result.solver_status = "converged" if opt.success else f"failed:{opt.message}"
        weights = opt.x if opt.success else init
        result.objective_value = -opt.fun if opt.success else 0.0
    except Exception as e:
        logger.warning(f"optimizer_v4_solver_error: {e}")
        result.solver_status = f"error:{str(e)[:50]}"
        weights = init
        result.diagnostics.append(f"solver_error:{e}")

    # --- 4. Convert weights to contracts ---
    positions = []
    total_capital = 0.0
    total_risk = 0.0
    total_delta = 0.0
    total_vega = 0.0

    for i, c in enumerate(candidates):
        w = weights[i]
        if w < 1e-6:
            continue

        # Convert weight to dollar allocation
        alloc_dollars = w * available_capital

        # Convert to contracts
        if c.collateral > 0:
            contracts = int(alloc_dollars / c.collateral)
        elif c.max_loss > 0:
            contracts = int(alloc_dollars / c.max_loss)
        else:
            contracts = 1

        contracts = max(0, min(contracts, int(max_contracts[i])))
        if contracts == 0:
            continue

        cap_required = contracts * c.collateral
        risk = contracts * c.max_loss

        positions.append(OptimizedPosition(
            symbol=c.symbol,
            strategy=c.strategy,
            contracts=contracts,
            kelly_fraction=round(kelly_fracs[i], 4),
            adjusted_fraction=round(w, 4),
            expected_utility=round(utilities[i] * contracts, 2),
            capital_required=round(cap_required, 2),
            risk_dollars=round(risk, 2),
        ))

        total_capital += cap_required
        total_risk += risk
        total_delta += contracts * c.delta_per_contract
        total_vega += contracts * c.vega_per_contract

    # Rank by expected utility
    positions.sort(key=lambda p: p.expected_utility, reverse=True)
    for i, p in enumerate(positions):
        p.rank = i + 1

    result.positions = positions
    result.total_capital_used = round(total_capital, 2)
    result.total_risk = round(total_risk, 2)
    result.portfolio_delta = round(total_delta, 4)
    result.portfolio_vega = round(total_vega, 4)

    logger.info(
        f"optimizer_v4: candidates={n} positions={len(positions)} "
        f"capital={total_capital:.0f}/{available_capital:.0f} "
        f"risk={total_risk:.0f}/{risk_budget:.0f} "
        f"delta={total_delta:.2f} vega={total_vega:.2f} "
        f"status={result.solver_status}"
    )

    return result
