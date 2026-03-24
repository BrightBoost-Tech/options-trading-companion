"""
Surface feature extraction for the opportunity scoring engine.

Extracts quantitative features from an IVSurface that can be passed
to the opportunity scorer as part of market_ctx. These features capture
information that single-point IV or IV rank cannot:

- iv_rank_surface: IV rank using the full surface (not just ATM)
- skew_zscore: current skew relative to rolling history
- term_slope: front-month vs back-month ATM IV ratio
- wing_richness: OTM put IV vs OTM call IV asymmetry
- surface_change_1d: how much the surface moved since prior snapshot
"""

import logging
import math
from typing import Any, Dict, List, Optional

from packages.quantum.surfaces.iv_surface import IVSurface

logger = logging.getLogger(__name__)

# History buffers for z-score computation (symbol → list of values)
_skew_history: Dict[str, List[float]] = {}
_atm_iv_history: Dict[str, List[float]] = {}
_surface_snapshot_history: Dict[str, Dict[str, float]] = {}

HISTORY_WINDOW = 30  # rolling window for z-score


def extract_surface_features(
    surface: IVSurface,
    iv_percentile_data: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Extract a flat dict of surface features suitable for passing to
    the opportunity scorer's market_ctx.

    Args:
        surface: IVSurface object (already built and arb-free)
        iv_percentile_data: Optional dict with historical IV data for
                           computing iv_rank_surface. Keys: iv_52w_high, iv_52w_low.

    Returns:
        Dict of features (all prefixed with 'surface_' to avoid collisions):
        - surface_atm_iv_front: front-month ATM IV
        - surface_atm_iv_back: back-month ATM IV
        - surface_term_slope: front/back ratio (>1 = backwardation, <1 = contango)
        - surface_skew_25d: 25-delta skew for front month
        - surface_skew_zscore: current skew vs 30-day rolling z-score
        - surface_wing_richness: put wing / call wing IV ratio
        - surface_iv_rank: IV rank using surface ATM (0-100)
        - surface_change_1d: absolute change in front ATM IV vs prior snapshot
        - surface_num_expiries: number of valid expiry slices
        - surface_is_valid: whether the surface is arb-free
    """
    metrics = surface.surface_metrics()
    term = surface.term_structure()
    symbol = surface.symbol

    features: Dict[str, Any] = {
        "surface_atm_iv_front": metrics.get("atm_iv_front"),
        "surface_atm_iv_back": metrics.get("atm_iv_back"),
        "surface_term_slope": metrics.get("term_slope"),
        "surface_wing_richness": metrics.get("wing_richness"),
        "surface_num_expiries": metrics.get("num_expiries", 0),
        "surface_is_valid": metrics.get("is_valid", False),
    }

    # --- Skew (front month) ---
    front_expiry = term[0]["expiry"] if term else None
    skew_25d = surface.skew(front_expiry) if front_expiry else None
    features["surface_skew_25d"] = round(skew_25d, 4) if skew_25d is not None else None

    # --- Skew z-score (rolling) ---
    features["surface_skew_zscore"] = None
    if skew_25d is not None:
        history = _skew_history.setdefault(symbol, [])
        history.append(skew_25d)
        if len(history) > HISTORY_WINDOW:
            history[:] = history[-HISTORY_WINDOW:]
        if len(history) >= 5:
            features["surface_skew_zscore"] = round(_zscore(skew_25d, history), 4)

    # --- IV Rank (surface-based) ---
    features["surface_iv_rank"] = None
    atm_front = metrics.get("atm_iv_front")
    if atm_front is not None:
        if iv_percentile_data:
            iv_high = iv_percentile_data.get("iv_52w_high", 0)
            iv_low = iv_percentile_data.get("iv_52w_low", 0)
            if iv_high > iv_low:
                rank = (atm_front - iv_low) / (iv_high - iv_low) * 100
                features["surface_iv_rank"] = round(max(0, min(100, rank)), 1)
        else:
            # Fallback: use rolling ATM history
            history = _atm_iv_history.setdefault(symbol, [])
            history.append(atm_front)
            if len(history) > HISTORY_WINDOW:
                history[:] = history[-HISTORY_WINDOW:]
            if len(history) >= 5:
                low = min(history)
                high = max(history)
                if high > low:
                    rank = (atm_front - low) / (high - low) * 100
                    features["surface_iv_rank"] = round(max(0, min(100, rank)), 1)

    # --- Surface change (1-day) ---
    features["surface_change_1d"] = None
    if atm_front is not None:
        prev = _surface_snapshot_history.get(symbol, {}).get("atm_iv_front")
        if prev is not None:
            features["surface_change_1d"] = round(atm_front - prev, 4)
        _surface_snapshot_history[symbol] = {"atm_iv_front": atm_front}

    return features


def _zscore(value: float, history: List[float]) -> float:
    """Compute z-score of value relative to history."""
    n = len(history)
    if n < 2:
        return 0.0
    mean = sum(history) / n
    variance = sum((x - mean) ** 2 for x in history) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 1e-8
    return (value - mean) / std
