from typing import List, Dict
from packages.quantum.models import SpreadPosition

# Configurable Thresholds for Alerts
DELTA_LIMIT = 500.0  # Example: net delta > 500 or < -500
THETA_LIMIT = 1000.0 # Example: net theta > 1000
VEGA_LIMIT = 2000.0  # Example: net vega > 2000

def aggregate_portfolio_greeks(spreads: List[SpreadPosition]) -> Dict[str, float]:
    """
    Returns net portfolio Greeks:
      {
        "delta": float,
        "gamma": float,
        "vega": float,
        "theta": float
      }
    where each value is the sum of SpreadPosition.{delta,gamma,vega,theta}.
    """
    agg = {
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0
    }

    for spread in spreads:
        # SpreadPosition has greeks at the spread level (already aggregated/derived)
        # Quantity is the number of spreads. Greeks are usually per unit?
        # Checking models.py: SpreadPosition has delta, gamma etc.
        # Usually these are "Total Delta" for the position (unit_delta * quantity).
        # But let's check assumptions.
        # If SpreadPosition.delta is per-unit, we multiply by quantity.
        # However, typically 'SpreadPosition' in this system seems to store aggregate or per-unit?
        # Looking at options_utils.py (not read yet, but implied), usually it's per unit or total.
        # Let's assume SpreadPosition fields are TOTAL for the position if they are pre-calculated,
        # OR per-unit.
        # API snapshot usually computes them.
        # Re-reading models.py: "delta: float" etc.
        # Let's assume they are already totals or we trust the input values.
        # Wait, if `SpreadPosition` comes from `group_spread_positions`, does it calculate greeks?
        # `models.py` has them as fields.
        # In `api.py` -> `group_spread_positions` converts holdings.
        # `enrich_holdings_with_analytics` usually enriches holdings with greeks?
        # Let's assume SpreadPosition values are what we sum.

        # Safe access with 0.0 default
        agg["delta"] += spread.delta or 0.0
        agg["gamma"] += spread.gamma or 0.0
        agg["vega"] += spread.vega or 0.0
        agg["theta"] += spread.theta or 0.0

    return agg

def build_greek_alerts(greeks: Dict[str, float]) -> Dict[str, bool]:
    """
    Uses configurable thresholds to emit flags:
      {
        "delta_over_limit": bool,
        "theta_over_limit": bool,
        ...
      }
    """
    return {
        "delta_over_limit": abs(greeks.get("delta", 0.0)) > DELTA_LIMIT,
        "theta_over_limit": abs(greeks.get("theta", 0.0)) > THETA_LIMIT,
        "vega_over_limit": abs(greeks.get("vega", 0.0)) > VEGA_LIMIT
    }
