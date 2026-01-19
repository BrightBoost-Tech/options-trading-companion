
import pytest
import numpy as np
import pandas as pd
from packages.quantum.analytics.regime_integration import (
    calculate_regime_vectorized,
    map_market_regime,
    run_historical_scoring,
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES
)
from packages.quantum.analytics.regime_scoring import ScoringEngine, ConvictionTransform

def infer_global_context_shim(trend: str, vol: float):
    # Replicates infer_global_context logic for the test
    # (since I removed the import from historical_simulation, but logic is simple)
    features = {
        "spy_trend": trend.lower(),
        "vix_level": 20.0
    }
    if vol > 0.30: features["vix_level"] = 35.0
    elif vol > 0.20: features["vix_level"] = 25.0
    else: features["vix_level"] = 15.0

    spy_trend = features.get("spy_trend", "neutral")
    vix = features.get("vix_level", 20.0)

    regime = "crab"
    vol_state = "medium"

    if vix > 30.0:
        vol_state = "high"
    elif vix > 20.0:
        vol_state = "medium"
    else:
        vol_state = "low"

    if vol_state == "high":
        regime = "shock"
    elif vol_state == "medium":
        if spy_trend == "down":
            regime = "bear"
        else:
            regime = "crab"
    else:
        if spy_trend == "up":
            regime = "bull"
        elif spy_trend == "down":
            regime = "bear"
        else:
            regime = "crab"

    return {"state": regime, "vol_annual": vol}

def test_regime_vectorized_parity():
    # 1. Generate Random Data
    n = 100
    np.random.seed(42)

    # Trends: UP, DOWN, NEUTRAL
    trends = np.random.choice(["UP", "DOWN", "NEUTRAL"], n)

    # Vols: 0.0 to 0.5
    vols = np.random.uniform(0.0, 0.5, n)

    # RSIs: 0 to 100
    rsis = np.random.uniform(0, 100, n)

    # 2. Run Vectorized
    vec_result = calculate_regime_vectorized(trends, vols, rsis)
    vec_regime = vec_result["regime"]
    vec_conviction = vec_result["conviction"]

    # 3. Run Loop-based (Legacy)
    legacy_regime = []
    legacy_conviction = []

    scoring_engine = ScoringEngine(DEFAULT_WEIGHT_MATRIX, DEFAULT_CATALYST_PROFILES, DEFAULT_LIQUIDITY_SCALAR)
    conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)

    for i in range(n):
        t = trends[i]
        v = vols[i]
        r = rsis[i]

        # Infer context
        ctx = infer_global_context_shim(t, v)

        # Map regime
        reg = map_market_regime(ctx)
        legacy_regime.append(reg)

        # Score
        # Map factors
        t_score = 100.0 if t == "UP" else (0.0 if t == "DOWN" else 50.0)
        v_score = 100.0 if v < 0.15 else (0.0 if v > 0.30 else 50.0)
        r_score = 100.0 if r < 30 else (0.0 if r > 70 else 50.0)

        factors = {"trend": t_score, "volatility": v_score, "value": r_score}

        res = run_historical_scoring(
            symbol_data={"symbol": "TEST", "factors": factors, "liquidity_tier": "top"},
            regime=reg,
            scoring_engine=scoring_engine,
            conviction_transform=conviction_transform,
            universe_median=None
        )
        legacy_conviction.append(res['conviction'])

    legacy_regime = np.array(legacy_regime)
    legacy_conviction = np.array(legacy_conviction)

    # 4. Compare
    # Check Regimes
    np.testing.assert_array_equal(vec_regime, legacy_regime, err_msg="Regime mismatch")

    # Check Convictions
    np.testing.assert_allclose(vec_conviction, legacy_conviction, atol=1e-8, err_msg="Conviction mismatch")

    print("Vectorized parity confirmed!")

if __name__ == "__main__":
    test_regime_vectorized_parity()
