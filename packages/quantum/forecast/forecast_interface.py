"""
Unified forecast interface consumed by the optimizer and suggestion pipeline.

ForecastBundle: combines return + vol + regime + event for one symbol.
ForecastSet: collection of ForecastBundles for the universe.
Both are JSON-serializable for logging and replay.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packages.quantum.forecast.return_forecast import ReturnForecast
from packages.quantum.forecast.vol_forecast import VolForecast

logger = logging.getLogger(__name__)


@dataclass
class ForecastBundle:
    """
    Complete forecast for a single symbol — consumed by scoring/sizing.

    Combines:
    - Return distribution (mean, std, skew, kurtosis)
    - Vol forecast term structure
    - Regime context snapshot
    - Event context snapshot
    """
    symbol: str
    return_forecast: ReturnForecast
    vol_forecast: VolForecast

    # Context snapshots (for logging — not used in computation)
    regime_snapshot: Dict[str, Any] = field(default_factory=dict)
    event_snapshot: Dict[str, Any] = field(default_factory=dict)

    # Calibration tracking
    predicted_ev: Optional[float] = None
    predicted_pop: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "return_forecast": self.return_forecast.to_dict(),
            "vol_forecast": self.vol_forecast.to_dict(),
            "regime_snapshot": self.regime_snapshot,
            "event_snapshot": self.event_snapshot,
            "predicted_ev": self.predicted_ev,
            "predicted_pop": self.predicted_pop,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ForecastBundle":
        """Reconstruct from serialized dict (for replay)."""
        rf_data = d.get("return_forecast", {})
        vf_data = d.get("vol_forecast", {})

        rf = ReturnForecast(
            symbol=rf_data.get("symbol", d.get("symbol", "")),
            horizon_days=rf_data.get("horizon_days", 30),
            mean=rf_data.get("mean", 0.0),
            std=rf_data.get("std", 0.25),
            skew=rf_data.get("skew", 0.0),
            kurtosis=rf_data.get("kurtosis", 3.0),
        )

        vf = VolForecast(
            symbol=vf_data.get("symbol", d.get("symbol", "")),
            term_structure={int(k): v for k, v in (vf_data.get("term_structure") or {}).items()},
            implied_vol_atm=vf_data.get("implied_vol_atm", 0.0),
            realized_vol_20d=vf_data.get("realized_vol_20d", 0.0),
        )

        return cls(
            symbol=d.get("symbol", ""),
            return_forecast=rf,
            vol_forecast=vf,
            regime_snapshot=d.get("regime_snapshot", {}),
            event_snapshot=d.get("event_snapshot", {}),
            predicted_ev=d.get("predicted_ev"),
            predicted_pop=d.get("predicted_pop"),
        )


@dataclass
class ForecastSet:
    """
    Collection of ForecastBundles for the trading universe.

    Used by the optimizer and suggestion pipeline to access
    forecasts by symbol.
    """
    bundles: Dict[str, ForecastBundle] = field(default_factory=dict)
    as_of_ts: str = ""

    def get(self, symbol: str) -> Optional[ForecastBundle]:
        """Get forecast bundle for a symbol."""
        return self.bundles.get(symbol)

    def symbols(self) -> List[str]:
        """List of symbols with forecasts."""
        return list(self.bundles.keys())

    def add(self, bundle: ForecastBundle) -> None:
        """Add or replace a forecast bundle."""
        self.bundles[bundle.symbol] = bundle

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of_ts": self.as_of_ts,
            "count": len(self.bundles),
            "bundles": {sym: b.to_dict() for sym, b in self.bundles.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ForecastSet":
        """Reconstruct from serialized dict."""
        fs = cls(as_of_ts=d.get("as_of_ts", ""))
        for sym, bdata in (d.get("bundles") or {}).items():
            fs.bundles[sym] = ForecastBundle.from_dict(bdata)
        return fs


# ---------------------------------------------------------------------------
# Convenience: forecast-derived EV and PoP
# ---------------------------------------------------------------------------

def forecast_ev_pop(
    bundle: ForecastBundle,
    max_profit: float,
    max_loss: float,
    breakeven_return: float,
    is_credit: bool = True,
) -> Dict[str, float]:
    """
    Compute EV and PoP from a return forecast distribution.

    This replaces the discrete probability model in opportunity_scorer
    with distribution-integrated values.

    Args:
        bundle: ForecastBundle for the underlying
        max_profit: Maximum profit in dollars
        max_loss: Maximum loss in dollars (positive number)
        breakeven_return: Return at which P&L = 0 (as decimal fraction)
        is_credit: True for credit strategies

    Returns:
        Dict with ev_amount, ev_percent, prob_profit
    """
    rf = bundle.return_forecast

    if is_credit:
        # Credit strategy profits when return stays above breakeven
        pop = rf.prob_above(breakeven_return)
    else:
        # Debit strategy profits when return exceeds breakeven
        pop = rf.prob_above(breakeven_return)

    # Simplified EV using binary outcome model with distribution-derived probability
    # (full integral would require numerical quadrature over payoff × density)
    ev = max_profit * pop - max_loss * (1.0 - pop)

    ev_pct = (ev / max_loss * 100) if max_loss > 0 else 0.0

    return {
        "ev_amount": round(ev, 2),
        "ev_percent": round(ev_pct, 2),
        "prob_profit": round(pop, 4),
    }
