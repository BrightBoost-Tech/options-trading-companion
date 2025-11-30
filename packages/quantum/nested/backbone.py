from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import os
from supabase import create_client, Client

# Reuse or recreate the Supabase client helper to avoid circular imports with adapters
def _get_supabase_client() -> Optional[Client]:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None

@dataclass
class GlobalContext:
    global_regime: str               # e.g. "bull", "bear", "crab", "shock"
    market_volatility_state: str     # e.g. "low", "medium", "high"
    global_risk_scaler: float        # in [0.5, 1.0] typically

from datetime import datetime, timedelta

# Simple Global Cache
_MACRO_CACHE = {
    "last_updated": None,
    "features": None
}

def compute_macro_features(service: Any) -> Dict[str, Any]:
    """
    Construct macro/market features.
    Accepts 'service' which should be an instance of PolygonService (duck-typed).
    Includes in-memory caching (5 mins) to prevent high latency on every request.
    """
    global _MACRO_CACHE
    now = datetime.now()

    # Check Cache (5 minute TTL)
    if _MACRO_CACHE["features"] and _MACRO_CACHE["last_updated"]:
        if (now - _MACRO_CACHE["last_updated"]) < timedelta(minutes=5):
            return _MACRO_CACHE["features"]

    features = {
        "spy_trend": "neutral",
        "vix_level": 20.0,
        "market_breadth": 0.5
    }

    if not service:
        return features

    try:
        # 1. SPY Trend
        features["spy_trend"] = service.get_trend("SPY").lower()

        # 2. VIX Level
        # Try fetching I:VIX (Index) or just VIX
        # Fallback to a proxy if needed or just accept failure
        try:
            # Try to get 5 days of VIX data to find latest
            vix_data = service.get_historical_prices("I:VIX", days=5)
            if vix_data and vix_data.get('prices'):
                features["vix_level"] = float(vix_data['prices'][-1])
        except Exception:
            # If I:VIX fails, maybe try just VIX (sometimes mapped)
            # Or just leave default 20.0
            pass

        # Update Cache
        _MACRO_CACHE["features"] = features
        _MACRO_CACHE["last_updated"] = now

    except Exception as e:
        print(f"L2 Backbone: Error computing macro features: {e}")

    return features

def infer_global_context(features: Dict[str, Any]) -> GlobalContext:
    """
    Rule-based inference of global regime.
    """
    spy_trend = features.get("spy_trend", "neutral")
    vix = features.get("vix_level", 20.0)

    regime = "crab"
    vol_state = "medium"
    scaler = 1.0

    # 1. Determine Volatility State
    if vix > 30.0:
        vol_state = "high"
    elif vix > 20.0:
        vol_state = "medium"
    else:
        vol_state = "low"

    # 2. Determine Regime & Scaler
    if vol_state == "high":
        regime = "shock"
        scaler = 0.6  # Severe risk reduction
    elif vol_state == "medium":
        if spy_trend == "down":
            regime = "bear"
            scaler = 0.8
        else:
            regime = "crab"
            scaler = 0.9
    else:
        # Low Vol
        if spy_trend == "up":
            regime = "bull"
            scaler = 1.0
        elif spy_trend == "down":
            regime = "bear" # Low vol bear? Possible slow bleed
            scaler = 0.85
        else:
            regime = "crab"
            scaler = 0.95

    return GlobalContext(
        global_regime=regime,
        market_volatility_state=vol_state,
        global_risk_scaler=scaler
    )

def log_global_context(ctx: GlobalContext) -> None:
    """
    Insert a row into nested_regimes.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return

    try:
        data = {
            "regime": ctx.global_regime,
            "volatility_state": ctx.market_volatility_state,
            "risk_scaler": ctx.global_risk_scaler
            # created_at is usually auto-generated
        }
        supabase.table("nested_regimes").insert(data).execute()
    except Exception as e:
        print(f"L2 Backbone: Failed to log context: {e}")
