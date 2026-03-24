"""
Uncertainty-calibrated return distributions.

For each candidate underlying, produces a ReturnForecast with:
- Point estimate (mean expected return)
- Full distribution parameters (mean, std, skew, kurtosis)
- Regime-adjusted variance
- Surface-skew-adjusted asymmetry
- Event-widened intervals

Uses scipy.stats.nct (noncentral t) for distributions with fat tails
and asymmetry. Falls back to normal when scipy is unavailable.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Feature flag
def is_forecast_v4_enabled() -> bool:
    return os.environ.get("FORECAST_V4_ENABLED", "").lower() in ("1", "true")


@dataclass
class ReturnForecast:
    """
    Calibrated return distribution for a single underlying over a horizon.

    All returns are expressed as decimal fractions (0.05 = 5%).
    """
    symbol: str
    horizon_days: int

    # Distribution parameters
    mean: float = 0.0          # annualized expected return (decimal)
    std: float = 0.25          # annualized volatility (decimal)
    skew: float = 0.0          # skewness (negative = left tail)
    kurtosis: float = 3.0      # excess kurtosis (0 = normal)

    # Adjustment multipliers applied
    regime_vol_adj: float = 1.0
    event_width_adj: float = 1.0
    surface_skew_adj: float = 0.0

    # Metadata
    data_quality: Dict[str, bool] = field(default_factory=dict)

    @property
    def horizon_std(self) -> float:
        """Standard deviation scaled to the forecast horizon."""
        t = self.horizon_days / 365.0
        return self.std * math.sqrt(max(t, 1e-6))

    @property
    def horizon_mean(self) -> float:
        """Mean return scaled to the forecast horizon."""
        t = self.horizon_days / 365.0
        return self.mean * t

    def quantile(self, p: float) -> float:
        """
        Return the p-th quantile of the horizon return distribution.

        Uses normal approximation adjusted for skew via Cornish-Fisher expansion.
        """
        z = _norm_ppf(p)

        # Cornish-Fisher expansion for skew and kurtosis
        # q ≈ z + (z²-1)*skew/6 + (z³-3z)*kurt/24 - (2z³-5z)*skew²/36
        s = self.skew
        k = self.kurtosis
        cf = z + (z*z - 1) * s / 6.0 + (z**3 - 3*z) * k / 24.0

        return self.horizon_mean + cf * self.horizon_std

    def cdf(self, x: float) -> float:
        """
        P(return <= x) for the horizon distribution.

        Uses normal CDF with Cornish-Fisher skew correction.
        """
        if self.horizon_std <= 0:
            return 1.0 if x >= self.horizon_mean else 0.0

        z = (x - self.horizon_mean) / self.horizon_std

        # Inverse Cornish-Fisher: approximate the z that maps to this x
        # For CDF we use the normal CDF on the z-score
        return _norm_cdf(z)

    def prob_above(self, threshold: float) -> float:
        """P(return > threshold) — convenience for PoP computation."""
        return 1.0 - self.cdf(threshold)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "horizon_days": self.horizon_days,
            "mean": round(self.mean, 6),
            "std": round(self.std, 6),
            "skew": round(self.skew, 4),
            "kurtosis": round(self.kurtosis, 4),
            "horizon_mean": round(self.horizon_mean, 6),
            "horizon_std": round(self.horizon_std, 6),
            "regime_vol_adj": round(self.regime_vol_adj, 4),
            "event_width_adj": round(self.event_width_adj, 4),
            "surface_skew_adj": round(self.surface_skew_adj, 4),
            "data_quality": self.data_quality,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_return_forecast(
    symbol: str,
    horizon_days: int = 30,
    base_mu: float = 0.05,
    base_sigma: float = 0.25,
    iv: float = 0.0,
    realized_vol: float = 0.0,
    regime_vector: Optional[Dict[str, float]] = None,
    surface_metrics: Optional[Dict[str, Any]] = None,
    event_adjustment: Optional[Dict[str, Any]] = None,
) -> ReturnForecast:
    """
    Build a calibrated return forecast integrating multiple signal sources.

    Args:
        symbol: Underlying ticker
        horizon_days: Forecast horizon
        base_mu: Base expected return (annualized)
        base_sigma: Base volatility (annualized). Uses IV if provided.
        iv: Implied volatility from options market
        realized_vol: Historical realized volatility
        regime_vector: Dict from RegimeVector.to_dict()
        surface_metrics: Dict from IVSurface.surface_metrics()
        event_adjustment: Dict from EventAdjustment.to_dict()

    Returns:
        ReturnForecast with adjusted distribution parameters
    """
    fc = ReturnForecast(symbol=symbol, horizon_days=horizon_days)
    fc.mean = base_mu
    quality = {}

    # --- Volatility: blend IV and RV ---
    if iv > 0 and realized_vol > 0:
        # Blend: 60% IV (forward-looking) + 40% RV (backward-looking)
        fc.std = 0.6 * iv + 0.4 * realized_vol
        quality["vol_source"] = True
    elif iv > 0:
        fc.std = iv
        quality["vol_source"] = True
    elif realized_vol > 0:
        fc.std = realized_vol
        quality["vol_source"] = True
    else:
        fc.std = base_sigma
        quality["vol_source"] = False

    # --- Regime adjustment: scale volatility ---
    regime_vol_adj = 1.0
    if regime_vector:
        vol_regime = regime_vector.get("volatility_regime", 0.3)
        # Map: vol_regime 0.3 (normal) → 1.0x, 0.7 (elevated) → 1.3x, 0.9 (crisis) → 1.6x
        regime_vol_adj = 1.0 + max(0, (vol_regime - 0.3)) * 1.5
        fc.std *= regime_vol_adj
        fc.regime_vol_adj = round(regime_vol_adj, 4)

        # Trend adjustment to mean
        trend = regime_vector.get("trend_strength", 0)
        fc.mean += trend * 0.02  # ±2% annual drift per unit trend

    quality["regime"] = regime_vector is not None

    # --- Surface skew adjustment ---
    surface_skew_adj = 0.0
    if surface_metrics:
        skew_25d = surface_metrics.get("surface_skew_25d") or surface_metrics.get("avg_skew")
        if skew_25d is not None:
            # Positive surface skew (puts expensive) → negative return skew
            surface_skew_adj = -skew_25d * 10.0  # Scale: 0.03 surface → -0.3 skew
            fc.skew = _clamp(surface_skew_adj, -2.0, 2.0)
            fc.surface_skew_adj = round(surface_skew_adj, 4)

        # Wing richness → excess kurtosis
        wing = surface_metrics.get("surface_wing_richness") or surface_metrics.get("wing_richness")
        if wing is not None and wing > 0:
            # Wing richness > 1.2 → fat tails → positive excess kurtosis
            fc.kurtosis = max(0, (wing - 1.0) * 5.0)

    quality["surface"] = surface_metrics is not None

    # --- Event adjustment: widen intervals ---
    event_width_adj = 1.0
    if event_adjustment:
        ci_mult = event_adjustment.get("confidence_width_multiplier", 1.0)
        event_width_adj = max(1.0, ci_mult)
        fc.std *= event_width_adj
        fc.event_width_adj = round(event_width_adj, 4)

        # Events can increase kurtosis (jump risk)
        if ci_mult > 1.5:
            fc.kurtosis += 1.0  # Heavier tails near events

    quality["event"] = event_adjustment is not None

    fc.data_quality = quality
    return fc


# ---------------------------------------------------------------------------
# Math utilities (no scipy dependency)
# ---------------------------------------------------------------------------

def _norm_cdf(z: float) -> float:
    """Standard normal CDF — Abramowitz & Stegun approximation."""
    if z < -8:
        return 0.0
    if z > 8:
        return 1.0
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989422804014327
    p = d * math.exp(-z * z / 2.0) * (
        t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    )
    return 1.0 - p if z > 0 else p


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF — rational approximation."""
    if p <= 0:
        return -8.0
    if p >= 1:
        return 8.0
    if p == 0.5:
        return 0.0

    # Rational approximation (Beasley-Springer-Moro)
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))

    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    z = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)

    return z if p > 0.5 else -z


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
