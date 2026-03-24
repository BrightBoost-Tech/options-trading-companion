"""
Utility-based scoring for Policy Lab cohort comparison.

Replaces the naive total_pl streak with a multi-factor utility function
that penalizes drawdowns, tail risk, execution slippage, and concentration.

utility = realized_pnl - drawdown_penalty - tail_risk_penalty
          - slippage_penalty - concentration_penalty

The posterior probability that challenger > default uses a Bayesian
normal comparison of daily utility distributions.
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Penalty weights (tunable)
# ---------------------------------------------------------------------------

DRAWDOWN_WEIGHT = 2.0        # penalize large drawdowns heavily
TAIL_RISK_WEIGHT = 1.5       # penalize expected shortfall
SLIPPAGE_WEIGHT = 1.0        # penalize excess execution slippage
CONCENTRATION_WEIGHT = 0.5   # penalize overconcentration in one symbol


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CohortDailyMetrics:
    """Metrics for one cohort on one trading day."""
    cohort_id: str
    cohort_name: str
    trade_date: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    expected_shortfall: float = 0.0
    execution_quality: float = 0.0     # actual_slippage - expected_slippage
    calibration_quality: float = 0.0   # correlation(predicted_ev, realized)
    trade_count: int = 0
    win_rate: Optional[float] = None
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    regime_at_close: str = ""
    symbols_traded: Optional[List[str]] = None
    max_single_symbol_pct: float = 0.0
    total_risk: float = 0.0


@dataclass
class CohortScore:
    """Scored result for a cohort over a trailing window."""
    cohort_id: str
    cohort_name: str
    utility: float
    realized_pnl: float
    drawdown_penalty: float
    tail_risk_penalty: float
    slippage_penalty: float
    concentration_penalty: float
    max_drawdown_pct: float
    expected_shortfall: float
    execution_quality: float
    calibration_quality: float
    trade_count: int
    trading_days: int
    daily_utilities: List[float]


# ---------------------------------------------------------------------------
# Utility computation
# ---------------------------------------------------------------------------

def compute_daily_utility(m: CohortDailyMetrics) -> float:
    """
    Compute utility for a single cohort-day.

    utility = realized_pnl
              - max_drawdown_pct * DRAWDOWN_WEIGHT
              - expected_shortfall * TAIL_RISK_WEIGHT
              - execution_slippage * SLIPPAGE_WEIGHT
              - concentration * CONCENTRATION_WEIGHT
    """
    drawdown_penalty = abs(m.max_drawdown_pct) * DRAWDOWN_WEIGHT
    tail_risk_penalty = abs(m.expected_shortfall) * TAIL_RISK_WEIGHT
    slippage_penalty = abs(m.execution_quality) * SLIPPAGE_WEIGHT
    concentration_penalty = m.max_single_symbol_pct * m.total_risk * CONCENTRATION_WEIGHT

    utility = (
        m.realized_pnl
        - drawdown_penalty
        - tail_risk_penalty
        - slippage_penalty
        - concentration_penalty
    )
    return utility


def score_cohort_window(
    daily_metrics: List[CohortDailyMetrics],
) -> Optional[CohortScore]:
    """
    Score a cohort over a trailing window of daily metrics.

    Returns None if no data.
    """
    if not daily_metrics:
        return None

    first = daily_metrics[0]
    daily_utils = []

    total_realized = 0.0
    total_drawdown_penalty = 0.0
    total_tail_penalty = 0.0
    total_slippage_penalty = 0.0
    total_concentration_penalty = 0.0
    total_trades = 0
    worst_drawdown = 0.0
    worst_es = 0.0

    exec_qualities = []
    cal_qualities = []

    for m in daily_metrics:
        u = compute_daily_utility(m)
        daily_utils.append(u)

        total_realized += m.realized_pnl
        total_drawdown_penalty += abs(m.max_drawdown_pct) * DRAWDOWN_WEIGHT
        total_tail_penalty += abs(m.expected_shortfall) * TAIL_RISK_WEIGHT
        total_slippage_penalty += abs(m.execution_quality) * SLIPPAGE_WEIGHT
        total_concentration_penalty += m.max_single_symbol_pct * m.total_risk * CONCENTRATION_WEIGHT
        total_trades += m.trade_count
        worst_drawdown = min(worst_drawdown, -abs(m.max_drawdown_pct))
        worst_es = min(worst_es, -abs(m.expected_shortfall))

        if m.execution_quality != 0:
            exec_qualities.append(m.execution_quality)
        if m.calibration_quality != 0:
            cal_qualities.append(m.calibration_quality)

    total_utility = sum(daily_utils)
    avg_exec = sum(exec_qualities) / len(exec_qualities) if exec_qualities else 0.0
    avg_cal = sum(cal_qualities) / len(cal_qualities) if cal_qualities else 0.0

    return CohortScore(
        cohort_id=first.cohort_id,
        cohort_name=first.cohort_name,
        utility=round(total_utility, 2),
        realized_pnl=round(total_realized, 2),
        drawdown_penalty=round(total_drawdown_penalty, 2),
        tail_risk_penalty=round(total_tail_penalty, 2),
        slippage_penalty=round(total_slippage_penalty, 2),
        concentration_penalty=round(total_concentration_penalty, 2),
        max_drawdown_pct=round(worst_drawdown, 4),
        expected_shortfall=round(worst_es, 4),
        execution_quality=round(avg_exec, 4),
        calibration_quality=round(avg_cal, 4),
        trade_count=total_trades,
        trading_days=len(daily_metrics),
        daily_utilities=daily_utils,
    )


# ---------------------------------------------------------------------------
# Bayesian posterior: P(challenger > default)
# ---------------------------------------------------------------------------

def posterior_probability_better(
    challenger_utils: List[float],
    default_utils: List[float],
) -> float:
    """
    Compute P(challenger_mean_utility > default_mean_utility) using
    a Bayesian normal comparison.

    Models daily utility as N(mu, sigma^2) per cohort. After observing
    N days, we compare the posterior distributions of the means.

    For two normal samples with known variance approximated by sample
    variance, P(mu_c > mu_d) = Phi(delta / se_delta) where:
    - delta = mean_c - mean_d
    - se_delta = sqrt(var_c/n_c + var_d/n_d)
    - Phi = standard normal CDF

    Returns probability in [0, 1]. Returns 0.5 if insufficient data.
    """
    if len(challenger_utils) < 2 or len(default_utils) < 2:
        return 0.5  # Insufficient data — no opinion

    try:
        from scipy.stats import norm
    except ImportError:
        logger.warning("scipy not available — falling back to manual CDF approximation")
        return _approx_posterior(challenger_utils, default_utils)

    n_c = len(challenger_utils)
    n_d = len(default_utils)

    mean_c = sum(challenger_utils) / n_c
    mean_d = sum(default_utils) / n_d

    var_c = sum((x - mean_c) ** 2 for x in challenger_utils) / max(n_c - 1, 1)
    var_d = sum((x - mean_d) ** 2 for x in default_utils) / max(n_d - 1, 1)

    se_delta = math.sqrt(var_c / n_c + var_d / n_d)

    if se_delta < 1e-12:
        # No variance — use simple comparison
        return 1.0 if mean_c > mean_d else 0.0

    z = (mean_c - mean_d) / se_delta
    return float(norm.cdf(z))


def _approx_posterior(
    challenger_utils: List[float],
    default_utils: List[float],
) -> float:
    """Fallback posterior computation without scipy using Abramowitz & Stegun."""
    n_c = len(challenger_utils)
    n_d = len(default_utils)

    mean_c = sum(challenger_utils) / n_c
    mean_d = sum(default_utils) / n_d

    var_c = sum((x - mean_c) ** 2 for x in challenger_utils) / max(n_c - 1, 1)
    var_d = sum((x - mean_d) ** 2 for x in default_utils) / max(n_d - 1, 1)

    se_delta = math.sqrt(var_c / n_c + var_d / n_d)

    if se_delta < 1e-12:
        return 1.0 if mean_c > mean_d else 0.0

    z = (mean_c - mean_d) / se_delta

    # Abramowitz & Stegun approximation for standard normal CDF
    if z < -8:
        return 0.0
    if z > 8:
        return 1.0
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    p = d * math.exp(-z * z / 2.0) * (
        t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    )
    return 1.0 - p if z > 0 else p
