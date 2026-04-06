"""
Canonical Risk-Adjusted EV Ranking

Single ranking metric used across the entire pipeline:

    risk_adjusted_ev = expected_pnl_after_costs / (marginal_risk * concentration_penalty)

Where:
    expected_pnl_after_costs = EV - expected_slippage - expected_fees
    marginal_risk            = max_loss * correlation_factor_to_existing_portfolio
    concentration_penalty    = 1.0 + (existing_exposure_to_symbol / total_budget)

Feature flag: CANONICAL_RANKING_ENABLED (default "1")
Small-account filter: MIN_EDGE_AFTER_COSTS (default "$15")
"""

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CANONICAL_RANKING_ENABLED = os.environ.get("CANONICAL_RANKING_ENABLED", "1") == "1"
MIN_EDGE_AFTER_COSTS = float(os.environ.get("MIN_EDGE_AFTER_COSTS", "15"))
DEFAULT_FEE_PER_CONTRACT = 0.65  # typical options commission per contract


def compute_risk_adjusted_ev(
    suggestion: Dict[str, Any],
    existing_positions: List[Dict[str, Any]],
    portfolio_budget: float,
    fee_per_contract: float = DEFAULT_FEE_PER_CONTRACT,
) -> float:
    """
    Canonical ranking metric for the entire pipeline.

    Returns risk_adjusted_ev: higher = better opportunity.
    Returns -999 if expected edge after costs is below MIN_EDGE_AFTER_COSTS.
    """
    ev = float(suggestion.get("ev") or 0)
    sizing = suggestion.get("sizing_metadata") or {}
    contracts = int(sizing.get("contracts") or 1)

    # ── Expected P&L after costs ────────────────────────────────────
    expected_slippage = _estimate_slippage(suggestion)
    expected_fees = fee_per_contract * contracts * 2  # open + close legs
    expected_pnl = ev - expected_slippage - expected_fees

    # ── Small-account hard filter ───────────────────────────────────
    if expected_pnl < MIN_EDGE_AFTER_COSTS:
        ticker = suggestion.get("ticker") or "?"
        logger.info(
            f"[RANKING] Filtered {ticker}: net_edge=${expected_pnl:.2f} "
            f"below minimum ${MIN_EDGE_AFTER_COSTS:.2f}"
        )
        return -999.0

    # ── Marginal risk with correlation adjustment ───────────────────
    max_loss = float(sizing.get("max_loss_total") or 0)
    correlation_factor = _compute_correlation_factor(suggestion, existing_positions)
    marginal_risk = max(abs(max_loss) * correlation_factor, 1.0)

    # ── Concentration penalty ───────────────────────────────────────
    symbol = suggestion.get("ticker")
    existing_exposure = sum(
        abs(float(p.get("max_credit") or p.get("max_loss") or 0)
            * float(p.get("quantity") or 0) * 100)
        for p in existing_positions
        if p.get("symbol") == symbol
    )
    concentration_penalty = 1.0 + (existing_exposure / max(portfolio_budget, 1.0))

    return expected_pnl / (marginal_risk * concentration_penalty)


def _estimate_slippage(suggestion: Dict[str, Any]) -> float:
    """Estimate slippage from TCM data or sizing metadata."""
    sizing = suggestion.get("sizing_metadata") or {}
    tcm = suggestion.get("tcm") or {}

    # Prefer TCM estimate, fall back to sizing metadata
    slippage = tcm.get("expected_slippage") or sizing.get("expected_slippage") or 0
    slippage = float(slippage)
    if slippage == 0:
        # Floor: 5% of EV covers residual bid-ask drag beyond directional pricing
        ev = float(suggestion.get("ev") or 0)
        slippage = abs(ev) * 0.05 if ev != 0 else 0
    return slippage


def _compute_correlation_factor(
    suggestion: Dict[str, Any],
    existing_positions: List[Dict[str, Any]],
) -> float:
    """
    Correlation factor: how much additional risk does this position add?
    1.0 = uncorrelated (new symbol), 2.0 = already have exposure.
    """
    symbol = suggestion.get("ticker")
    same_symbol_count = sum(
        1 for p in existing_positions if p.get("symbol") == symbol
    )
    if same_symbol_count > 0:
        return 2.0
    # TODO: sector/beta correlation when data is available
    return 1.0


def rank_suggestions_canonical(
    suggestions: List[Dict[str, Any]],
    existing_positions: List[Dict[str, Any]],
    portfolio_budget: float,
    fee_per_contract: float = DEFAULT_FEE_PER_CONTRACT,
) -> List[Dict[str, Any]]:
    """
    Score and sort suggestions by risk_adjusted_ev (descending).

    Mutates each suggestion to add risk_adjusted_ev field.
    Returns the same list, sorted.
    """
    for s in suggestions:
        raev = compute_risk_adjusted_ev(
            s, existing_positions, portfolio_budget, fee_per_contract
        )
        s["risk_adjusted_ev"] = round(raev, 6)

    suggestions.sort(key=lambda s: s.get("risk_adjusted_ev", -999), reverse=True)
    return suggestions
