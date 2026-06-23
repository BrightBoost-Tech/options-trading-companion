"""Volatility math — single source of truth for realized vol.

Cluster 1 standardised realized vol on LOG returns ln(P_t/P_{t-1}), annualised
×√252, population std (ddof=0). That logic previously lived only inside
``RegimeEngineV3._calculate_realized_volatility`` and was hardcoded to a 20-day
trailing window. A4 needs the same basis over an ARBITRARY hold window, so the
math is extracted here once and reused by both callers — no duplicated math, no
basis drift.
"""

import math
from typing import List, Optional

TRADING_DAYS_PER_YEAR = 252
# √252 — identical to the literal constant Cluster 1 used in regime_engine_v3.
_ANNUALIZER = math.sqrt(TRADING_DAYS_PER_YEAR)


def realized_vol_log_annualized(
    closes: List[float],
    window: Optional[int] = None,
) -> Optional[float]:
    """Annualised realized volatility from a close-price series.

    Basis (matches Cluster 1 exactly): log returns ln(P_t/P_{t-1}), population
    standard deviation (ddof=0), annualised ×√252.

    Args:
        closes: ascending close-price series (oldest → newest).
        window: number of RETURNS to use (needs ``window + 1`` prices). When
            None, uses the whole series (``len(closes) - 1`` returns) — this is
            the A4 hold-window case. Default-None keeps existing 20-day callers
            byte-identical when they pass ``window=20``.

    Returns:
        Annualised vol (decimal), or None when there are too few prices to form
        at least two returns (a 1-day hold can't yield a meaningful estimate).
        Non-positive prices contribute a 0.0 return (log undefined) rather than
        raising.
    """
    if not closes or len(closes) < 2:
        return None

    if window is None:
        window = len(closes) - 1
    # Need at least two returns for a population variance to mean anything.
    if window < 2 or len(closes) < window + 1:
        return None

    subset = closes[-(window + 1):]
    rets = []
    for i in range(window):
        c_prev = subset[i]
        c_curr = subset[i + 1]
        if c_prev <= 0 or c_curr <= 0:
            rets.append(0.0)
        else:
            rets.append(math.log(c_curr / c_prev))

    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n  # ddof=0 (population)
    return math.sqrt(var) * _ANNUALIZER
