"""
Promotion gate for paper→micro-live→live readiness evaluation.

Evaluates backtest metrics to determine if a strategy is eligible
for promotion to micro-live or live trading modes.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class PromotionThresholds:
    """Thresholds for promotion eligibility."""

    # Micro-live thresholds (less stringent)
    micro_live_min_sharpe: float = 0.5
    micro_live_max_drawdown: float = 0.25  # 25%
    micro_live_min_trades: int = 20
    micro_live_min_win_rate: float = 0.35
    micro_live_min_stability_score: float = 25.0
    micro_live_min_folds: int = 4  # v7.1: Minimum folds required
    micro_live_max_drawdown_worst: float = 0.25  # v7.1: Worst fold max DD

    # Live thresholds (more stringent)
    live_min_sharpe: float = 1.0
    live_max_drawdown: float = 0.15  # 15%
    live_min_trades: int = 50
    live_min_win_rate: float = 0.45
    live_min_stability_score: float = 50.0
    live_min_pct_positive_folds: float = 0.6  # 60% of folds profitable
    live_min_folds: int = 6  # v7.1: Minimum folds required
    live_max_drawdown_worst: float = 0.18  # v7.1: Worst fold max DD


# Default thresholds
DEFAULT_THRESHOLDS = PromotionThresholds()


def evaluate_promotion_gate(
    metrics: Dict[str, Any],
    run_mode: str,
    thresholds: Optional[PromotionThresholds] = None,
) -> Dict[str, Any]:
    """
    Evaluate if a backtest result is eligible for promotion.

    v7.1 Hardening: Walk-forward is REQUIRED for micro_live/live eligibility.
    Single-run backtests can only reach "paper" tier at best.

    Args:
        metrics: Backtest aggregate metrics dict containing:
            - sharpe: Sharpe ratio
            - max_drawdown: Maximum drawdown (as decimal, e.g., 0.15 = 15%)
            - total_trades: Total number of trades
            - win_rate: Win rate (as decimal, e.g., 0.55 = 55%)
            - stability_score: Walk-forward stability score (0-100)
            - pct_positive_folds: Percentage of profitable folds
            - total_pnl: Total profit/loss
            - fold_count: Number of folds in walk-forward (v7.1)
            - max_drawdown_worst: Worst fold max drawdown (v7.1)
        run_mode: One of "single", "walk_forward", "monte_carlo"
        thresholds: Optional custom thresholds, defaults to DEFAULT_THRESHOLDS

    Returns:
        Dict containing:
            - eligible_micro_live: bool
            - eligible_live: bool
            - promotion_tier: str ("live", "micro_live", "paper", "rejected")
            - promotion_reasons: List[str] explaining the decision
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    reasons: List[str] = []
    micro_live_failures: List[str] = []
    live_failures: List[str] = []

    # Extract metrics with safe defaults
    sharpe = metrics.get("sharpe", 0.0) or 0.0
    max_drawdown = metrics.get("max_drawdown", 1.0) or 1.0
    total_trades = metrics.get("total_trades", 0) or 0
    win_rate = metrics.get("win_rate", 0.0) or 0.0
    stability_score = metrics.get("stability_score", 0.0) or 0.0
    pct_positive_folds = metrics.get("pct_positive_folds", 0.0) or 0.0
    total_pnl = metrics.get("total_pnl", 0.0) or 0.0
    # v7.1: New metrics for hardening
    fold_count = metrics.get("fold_count", 0) or 0
    max_drawdown_worst = metrics.get("max_drawdown_worst", 1.0) or 1.0

    # v7.1: Walk-forward is REQUIRED for micro_live/live eligibility
    requires_walk_forward = run_mode != "walk_forward"
    if requires_walk_forward:
        micro_live_failures.append("requires_walk_forward")
        live_failures.append("requires_walk_forward")

    # Check micro-live eligibility
    if sharpe < thresholds.micro_live_min_sharpe:
        micro_live_failures.append(
            f"sharpe {sharpe:.2f} < {thresholds.micro_live_min_sharpe}"
        )
    if max_drawdown > thresholds.micro_live_max_drawdown:
        micro_live_failures.append(
            f"max_drawdown {max_drawdown:.1%} > {thresholds.micro_live_max_drawdown:.0%}"
        )
    if total_trades < thresholds.micro_live_min_trades:
        micro_live_failures.append(
            f"total_trades {total_trades} < {thresholds.micro_live_min_trades}"
        )
    if win_rate < thresholds.micro_live_min_win_rate:
        micro_live_failures.append(
            f"win_rate {win_rate:.1%} < {thresholds.micro_live_min_win_rate:.0%}"
        )

    # Walk-forward specific checks for micro-live
    if run_mode == "walk_forward":
        if stability_score < thresholds.micro_live_min_stability_score:
            micro_live_failures.append(
                f"stability_score {stability_score:.1f} < {thresholds.micro_live_min_stability_score}"
            )
        # v7.1: Fold count check
        if fold_count < thresholds.micro_live_min_folds:
            micro_live_failures.append(
                f"insufficient_folds: {fold_count} < {thresholds.micro_live_min_folds}"
            )
        # v7.1: Worst fold drawdown check
        if max_drawdown_worst > thresholds.micro_live_max_drawdown_worst:
            micro_live_failures.append(
                f"worst_fold_drawdown_too_high: {max_drawdown_worst:.1%} > {thresholds.micro_live_max_drawdown_worst:.0%}"
            )

    # Check live eligibility (only if micro-live passes)
    if sharpe < thresholds.live_min_sharpe:
        live_failures.append(
            f"sharpe {sharpe:.2f} < {thresholds.live_min_sharpe}"
        )
    if max_drawdown > thresholds.live_max_drawdown:
        live_failures.append(
            f"max_drawdown {max_drawdown:.1%} > {thresholds.live_max_drawdown:.0%}"
        )
    if total_trades < thresholds.live_min_trades:
        live_failures.append(
            f"total_trades {total_trades} < {thresholds.live_min_trades}"
        )
    if win_rate < thresholds.live_min_win_rate:
        live_failures.append(
            f"win_rate {win_rate:.1%} < {thresholds.live_min_win_rate:.0%}"
        )

    # Walk-forward specific checks for live
    if run_mode == "walk_forward":
        if stability_score < thresholds.live_min_stability_score:
            live_failures.append(
                f"stability_score {stability_score:.1f} < {thresholds.live_min_stability_score}"
            )
        if pct_positive_folds < thresholds.live_min_pct_positive_folds:
            live_failures.append(
                f"pct_positive_folds {pct_positive_folds:.1%} < {thresholds.live_min_pct_positive_folds:.0%}"
            )
        # v7.1: Fold count check for live
        if fold_count < thresholds.live_min_folds:
            live_failures.append(
                f"insufficient_folds: {fold_count} < {thresholds.live_min_folds}"
            )
        # v7.1: Worst fold drawdown check for live
        if max_drawdown_worst > thresholds.live_max_drawdown_worst:
            live_failures.append(
                f"worst_fold_drawdown_too_high: {max_drawdown_worst:.1%} > {thresholds.live_max_drawdown_worst:.0%}"
            )

    # Determine eligibility
    eligible_micro_live = len(micro_live_failures) == 0
    eligible_live = eligible_micro_live and len(live_failures) == 0

    # Determine promotion tier
    if eligible_live:
        promotion_tier = "live"
        reasons.append("All live thresholds met")
    elif eligible_micro_live:
        promotion_tier = "micro_live"
        reasons.append("Micro-live thresholds met")
        reasons.extend([f"Live blocked: {f}" for f in live_failures])
    elif total_pnl > 0:
        promotion_tier = "paper"
        reasons.append("Positive PnL but thresholds not met")
        reasons.extend([f"Micro-live blocked: {f}" for f in micro_live_failures])
    else:
        promotion_tier = "rejected"
        reasons.append("Negative PnL or insufficient metrics")
        reasons.extend([f"Blocked: {f}" for f in micro_live_failures])

    return {
        "eligible_micro_live": eligible_micro_live,
        "eligible_live": eligible_live,
        "promotion_tier": promotion_tier,
        "promotion_reasons": reasons,
    }


def compute_param_hash(optimized_params: Optional[Dict[str, Any]]) -> str:
    """
    Compute a hash of the optimized parameters for dedupe purposes.

    Args:
        optimized_params: Dict of optimized parameters from tuning

    Returns:
        SHA256 hex string (64 chars)
    """
    import hashlib
    import json

    if not optimized_params:
        # Return hash of empty dict for consistency
        params_str = "{}"
    else:
        # Sort keys for deterministic ordering
        params_str = json.dumps(optimized_params, sort_keys=True, default=str)

    return hashlib.sha256(params_str.encode()).hexdigest()
