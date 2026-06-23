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


def _vrp_live_enabled() -> bool:
    """Cluster 3 kill switch — gate the live VRP soft down-weight on the
    ranking path. DEFAULT OFF (behavioral / loosening-class change): only an
    explicit truthy value activates it, so an env regression fails to the exact
    pre-Cluster-3 ranking. Read at call time so it can be flipped (and reverted)
    without a redeploy."""
    return os.environ.get("VRP_LIVE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _resolve_vrp_inputs(suggestion: Dict[str, Any]):
    """Pull the VRP inputs (iv_rv_spread, premium_direction) off a suggestion,
    falling back to its internal_cand (present on the in-memory midday path,
    stripped once persisted — the executor reads the persisted top-level
    columns added by the Cluster 3 migration). Returns (iv_rv_spread,
    premium_direction); either may be None when unavailable."""
    cand = suggestion.get("internal_cand") or {}
    spread = suggestion.get("iv_rv_spread")
    if spread is None:
        spread = cand.get("iv_rv_spread")
    direction = suggestion.get("premium_direction") or cand.get("premium_direction")
    return spread, direction


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

    raev = expected_pnl / (marginal_risk * concentration_penalty)

    # ── Cluster 3: VRP soft down-weight (live, flag-gated) ──────────────
    # Reuse the EXISTING vrp_score_multiplier (Cluster 2) — no new math, no new
    # constants. Applies ONLY when:
    #   * VRP_LIVE_ENABLED is truthy (default OFF → byte-identical to today),
    #   * the candidate is a long-debit premium (premium_direction == 'debit';
    #     credit/short-premium/unknown are left untouched),
    #   * iv_rv_spread is available (None → 1.0 no-op; never penalize missing
    #     data — composes with Cluster 1's min-history exclusion),
    #   * raev > 0 (viable candidates only; the -999 filter already returned
    #     above, so a <1.0 multiplier can never flip a reject's sign).
    # MULTIPLIES the rank metric (never adds). Stamps pre/post/multiplier on the
    # suggestion for observability wherever risk_adjusted_ev is recorded.
    if _vrp_live_enabled() and raev > 0:
        iv_rv_spread, premium_direction = _resolve_vrp_inputs(suggestion)
        if premium_direction == "debit" and iv_rv_spread is not None:
            from packages.quantum.analytics.opportunity_scorer import vrp_score_multiplier
            vrp_multiplier = vrp_score_multiplier(iv_rv_spread)
            pre_vrp_rank = raev
            raev = raev * vrp_multiplier
            suggestion["vrp_ranking"] = {
                "iv_rv_spread": round(iv_rv_spread, 4),
                "vrp_multiplier": round(vrp_multiplier, 4),
                "pre_vrp_rank": round(pre_vrp_rank, 6),
                "post_vrp_rank": round(raev, 6),
            }
            if abs(1.0 - vrp_multiplier) >= 0.02:
                logger.info(
                    "[RANKING] VRP down-weight %s — iv_rv_spread=%.4f "
                    "multiplier=%.3f raev %.4f -> %.4f",
                    suggestion.get("ticker") or "?",
                    iv_rv_spread, vrp_multiplier, pre_vrp_rank, raev,
                )

    return raev


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
