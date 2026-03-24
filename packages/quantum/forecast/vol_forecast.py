"""
Forward volatility estimate with term structure.

Blends realized vol + implied vol + regime adjustment to produce
horizon-specific volatility forecasts.

Features:
- Term structure: different forecasts for 7d, 14d, 30d, 60d
- Event adjustment: spike forecast around catalysts
- Volatility cone: confidence bands around the forecast
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard horizons
DEFAULT_HORIZONS = [7, 14, 30, 60]


@dataclass
class VolForecast:
    """
    Forward volatility forecast for a single underlying.

    All volatilities are annualized decimals (0.25 = 25%).
    """
    symbol: str

    # Term structure: horizon_days → annualized vol forecast
    term_structure: Dict[int, float] = field(default_factory=dict)

    # Components
    realized_vol_5d: float = 0.0
    realized_vol_20d: float = 0.0
    realized_vol_60d: float = 0.0
    implied_vol_atm: float = 0.0

    # Adjustment factors
    regime_adj: float = 1.0
    event_adj: float = 1.0

    def vol(self, horizon_days: int) -> float:
        """
        Get volatility forecast for a specific horizon.

        Interpolates between term structure points if exact horizon
        is not available.
        """
        if horizon_days in self.term_structure:
            return self.term_structure[horizon_days]

        # Interpolate from nearest available horizons
        horizons = sorted(self.term_structure.keys())
        if not horizons:
            return self.implied_vol_atm or self.realized_vol_20d or 0.25

        if horizon_days <= horizons[0]:
            return self.term_structure[horizons[0]]
        if horizon_days >= horizons[-1]:
            return self.term_structure[horizons[-1]]

        # Linear interpolation
        for i in range(len(horizons) - 1):
            if horizons[i] <= horizon_days <= horizons[i + 1]:
                t = (horizon_days - horizons[i]) / (horizons[i + 1] - horizons[i])
                v1 = self.term_structure[horizons[i]]
                v2 = self.term_structure[horizons[i + 1]]
                return v1 + t * (v2 - v1)

        return self.term_structure[horizons[-1]]

    def vol_cone(self, horizon_days: int, confidence: float = 0.68) -> Tuple[float, float]:
        """
        Confidence interval for forward vol.

        Returns (vol_low, vol_high) representing the confidence band.
        Uses chi-squared distribution property: sample variance is
        chi-squared distributed with n-1 degrees of freedom.

        Simplified: ±20% of point estimate for 68% confidence,
        ±40% for 95% confidence.
        """
        v = self.vol(horizon_days)

        if confidence <= 0.68:
            width = 0.20
        elif confidence <= 0.90:
            width = 0.35
        else:
            width = 0.45

        return (v * (1 - width), v * (1 + width))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "term_structure": {str(k): round(v, 6) for k, v in self.term_structure.items()},
            "realized_vol_5d": round(self.realized_vol_5d, 6),
            "realized_vol_20d": round(self.realized_vol_20d, 6),
            "realized_vol_60d": round(self.realized_vol_60d, 6),
            "implied_vol_atm": round(self.implied_vol_atm, 6),
            "regime_adj": round(self.regime_adj, 4),
            "event_adj": round(self.event_adj, 4),
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_vol_forecast(
    symbol: str,
    realized_vol_5d: float = 0.0,
    realized_vol_20d: float = 0.0,
    realized_vol_60d: float = 0.0,
    implied_vol_atm: float = 0.0,
    iv_term_structure: Optional[List[Dict[str, Any]]] = None,
    regime_vector: Optional[Dict[str, float]] = None,
    event_adjustment: Optional[Dict[str, Any]] = None,
    horizons: Optional[List[int]] = None,
) -> VolForecast:
    """
    Build a vol forecast with term structure.

    Blending logic per horizon:
    - Short term (7d): weight RV_5d heavily (recent momentum)
    - Medium term (14-30d): blend IV_ATM and RV_20d
    - Long term (60d): weight RV_60d and IV contango/backwardation

    Args:
        symbol: Underlying ticker
        realized_vol_*: Realized volatilities at different windows
        implied_vol_atm: ATM implied volatility (from surface or market data)
        iv_term_structure: IV term structure [{dte, atm_iv}] from IVSurface
        regime_vector: Dict from RegimeVector.to_dict()
        event_adjustment: Dict from EventAdjustment.to_dict()
        horizons: Custom horizons to forecast (default: [7, 14, 30, 60])

    Returns:
        VolForecast with term structure populated
    """
    fc = VolForecast(
        symbol=symbol,
        realized_vol_5d=realized_vol_5d,
        realized_vol_20d=realized_vol_20d,
        realized_vol_60d=realized_vol_60d,
        implied_vol_atm=implied_vol_atm,
    )

    horizons = horizons or DEFAULT_HORIZONS

    # Base implied vol by horizon from IV surface term structure
    iv_by_dte: Dict[int, float] = {}
    if iv_term_structure:
        for point in iv_term_structure:
            dte = point.get("dte", 0)
            atm = point.get("atm_iv", 0)
            if dte > 0 and atm > 0:
                iv_by_dte[dte] = atm

    # Regime adjustment
    regime_adj = 1.0
    if regime_vector:
        vol_regime = regime_vector.get("volatility_regime", 0.3)
        regime_adj = 1.0 + max(0, (vol_regime - 0.3)) * 1.5
    fc.regime_adj = round(regime_adj, 4)

    # Event adjustment
    event_adj = 1.0
    if event_adjustment:
        event_adj = max(1.0, event_adjustment.get("confidence_width_multiplier", 1.0))
    fc.event_adj = round(event_adj, 4)

    # Build term structure
    for h in horizons:
        # Get IV for this horizon (interpolate from term structure)
        iv_h = _interpolate_iv_for_dte(h, iv_by_dte) if iv_by_dte else implied_vol_atm

        # Blend with realized vol (horizon-dependent weights)
        if h <= 7:
            # Short term: 40% RV_5d, 30% RV_20d, 30% IV
            rv = realized_vol_5d if realized_vol_5d > 0 else realized_vol_20d
            vol = _blend(rv, realized_vol_20d, iv_h, 0.40, 0.30, 0.30)
        elif h <= 14:
            # Medium-short: 20% RV_5d, 30% RV_20d, 50% IV
            vol = _blend(realized_vol_5d, realized_vol_20d, iv_h, 0.20, 0.30, 0.50)
        elif h <= 30:
            # Medium: 10% RV_5d, 30% RV_20d, 60% IV
            vol = _blend(realized_vol_5d, realized_vol_20d, iv_h, 0.10, 0.30, 0.60)
        else:
            # Long: 0% RV_5d, 20% RV_60d, 80% IV
            rv_long = realized_vol_60d if realized_vol_60d > 0 else realized_vol_20d
            vol = _blend(0, rv_long, iv_h, 0.0, 0.20, 0.80)

        # Apply adjustments
        vol *= regime_adj * event_adj

        # Floor
        vol = max(0.05, vol)

        fc.term_structure[h] = round(vol, 6)

    return fc


def _blend(rv1: float, rv2: float, iv: float, w1: float, w2: float, w3: float) -> float:
    """Weighted blend of vol inputs, skipping zeros."""
    total_weight = 0.0
    total_vol = 0.0

    if rv1 > 0:
        total_weight += w1
        total_vol += w1 * rv1
    if rv2 > 0:
        total_weight += w2
        total_vol += w2 * rv2
    if iv > 0:
        total_weight += w3
        total_vol += w3 * iv

    if total_weight <= 0:
        return 0.25  # fallback

    return total_vol / total_weight


def _interpolate_iv_for_dte(target_dte: int, iv_by_dte: Dict[int, float]) -> float:
    """Interpolate ATM IV for a target DTE from discrete term structure points."""
    if not iv_by_dte:
        return 0.0

    dtes = sorted(iv_by_dte.keys())

    if target_dte <= dtes[0]:
        return iv_by_dte[dtes[0]]
    if target_dte >= dtes[-1]:
        return iv_by_dte[dtes[-1]]

    for i in range(len(dtes) - 1):
        if dtes[i] <= target_dte <= dtes[i + 1]:
            t = (target_dte - dtes[i]) / (dtes[i + 1] - dtes[i])
            return iv_by_dte[dtes[i]] + t * (iv_by_dte[dtes[i + 1]] - iv_by_dte[dtes[i]])

    return iv_by_dte[dtes[-1]]
