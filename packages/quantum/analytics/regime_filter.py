"""D4 regime_filter — cross-asset regime read from EXISTING proxies.

OBSERVATION-ONLY. Computes a rates+credit (TLT/HYG) cross-asset regime read and
LOGS what it WOULD throttle/size vs what the live regime engine (v3) actually
decided this cycle. It does NOT change any live regime classification, throttle,
or sizing — that graduation is a separate future decision, gated on this
observation showing agreement with reality on logged data.

VIX is EXCLUDED by design (Step-0 gate). The live regime path does not consume a
fresh VIX: regime_engine_v3 uses no VIX; market_features.vix_level is seed-only
(no production writer); the only VIX fetch is a best-effort `I:VIX` call in the
portfolio optimizer that silently defaults to 20.0 and likely lacks Polygon index
entitlement. A regime signal on a stale VIX is worse than none, so this build
uses the live rates+credit proxies only and records VIX as absent. (Adding a
live VIX dimension is a separate decision; do not infer it from the stale field.)

FLAGGED ASSUMPTIONS: every weight/threshold/scale below is a GUESSED magnitude
(like the D2 momentum tempers), surfaced in `assumptions` and logged for
calibration against the observation record — NOT asserted correct. The whole
point of observation-first is to calibrate these before the signal ever acts.
"""

import os
from typing import Any, Dict, List, Optional

# ── Flag (default OFF) ─────────────────────────────────────────────────────
FLAG_ENV = "REGIME_FILTER_OBSERVE_ENABLED"
OBS_TABLE = "regime_filter_observations"


def is_observe_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


# ── FLAGGED ASSUMPTIONS (guessed magnitudes — to calibrate, not asserted) ──
ASSUMPTIONS: Dict[str, Any] = {
    # proxy → stress conversion (z-like; baselines/scales are guesses)
    "rates_move_scale_5d": 0.02,    # |TLT 5d return| of 2% ≈ 1 stress unit
    "credit_move_scale_5d": 0.015,  # HYG 5d return of -1.5% ≈ 1 credit-stress unit
    "proxy_rv_baseline": 0.10,      # annualized proxy RV neutral
    "proxy_rv_scale": 0.05,         # each 5% RV above baseline ≈ 1 unit
    # combine weights (credit-led: HYG drawdowns historically lead risk-off)
    "w_credit": 0.55,
    "w_rates": 0.45,
    # map combined stress z → risk_score (same 0-100 scale + thresholds as v3)
    "risk_score_center": 50.0,
    "risk_score_per_z": 16.6,
    "thresholds": {"suppressed": 20, "elevated": 60, "shock": 80},
    # would-be sizing scaler per state (borrowed from v3's scaler_map)
    "scaler_map": {"SUPPRESSED": 1.2, "NORMAL": 1.0, "CHOP": 0.9,
                   "ELEVATED": 0.7, "REBOUND": 0.8, "SHOCK": 0.5},
    "vix": "EXCLUDED_not_live (Step-0 gate); rates+credit-only fallback",
}


def _closes(basket_data: Dict[str, Any], sym: str) -> List[float]:
    bars = basket_data.get(sym) or []
    return [float(b["close"]) for b in bars if isinstance(b, dict) and b.get("close") is not None]


def _clip(x: float, lo: float = -3.0, hi: float = 3.0) -> float:
    return max(lo, min(hi, x))


def _proxy_read(closes: List[float], move_scale: float) -> Optional[Dict[str, float]]:
    """Direction + velocity read for one proxy ETF. None if insufficient data."""
    if len(closes) < 21:
        return None
    ret_5d = (closes[-1] / closes[-6]) - 1.0 if len(closes) >= 6 else 0.0
    sma20 = sum(closes[-20:]) / 20.0
    dist_sma = (closes[-1] - sma20) / sma20 if sma20 else 0.0
    rets = [(closes[i] / closes[i - 1]) - 1.0 for i in range(len(closes) - 20, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    rv = (var ** 0.5) * (252 ** 0.5)
    return {"return_5d": ret_5d, "dist_sma": dist_sma, "rv": rv,
            "move_z": ret_5d / move_scale if move_scale else 0.0}


def compute_regime_filter(basket_data: Dict[str, Any]) -> Dict[str, Any]:
    """PURE cross-asset regime read from TLT (rates) + HYG (credit). Maps to the
    SAME vocabulary the live throttle uses (a RegimeState + a 0.5–1.2 would-be
    sizing scaler + would-be HOLD), so the observation is directly comparable.

    Returns the raw proxy reads, the would-be classification/scaler/hold, the
    cross-asset risk score, the VIX status (absent), and the flagged assumptions.
    Insufficient proxy data → applicable=False (recorded N/A, never an error)."""
    A = ASSUMPTIONS
    rates = _proxy_read(_closes(basket_data, "TLT"), A["rates_move_scale_5d"])
    credit = _proxy_read(_closes(basket_data, "HYG"), A["credit_move_scale_5d"])
    if rates is None or credit is None:
        return {"applicable": False, "reason": "insufficient_TLT_or_HYG_bars",
                "vix_status": "absent_not_live", "assumptions": A}

    # Stress is risk-OFF: TLT moving fast (either way) = rates stress; HYG FALLING
    # = credit stress. RV above baseline adds stress for both. (FLAGGED guesses.)
    rates_stress = _clip(abs(rates["move_z"]) + max(0.0, (rates["rv"] - A["proxy_rv_baseline"]) / A["proxy_rv_scale"]))
    credit_stress = _clip((-credit["move_z"]) + max(0.0, (credit["rv"] - A["proxy_rv_baseline"]) / A["proxy_rv_scale"]))
    combined_z = A["w_credit"] * credit_stress + A["w_rates"] * rates_stress

    risk_score = max(0.0, min(100.0, A["risk_score_center"] + combined_z * A["risk_score_per_z"]))
    t = A["thresholds"]
    if risk_score < t["suppressed"]:
        state = "SUPPRESSED"
    elif risk_score < t["elevated"]:
        state = "NORMAL"
    elif risk_score < t["shock"]:
        state = "ELEVATED"
    else:
        state = "SHOCK"
    scaler = A["scaler_map"].get(state, 1.0)
    return {
        "applicable": True,
        "rates_read": rates, "credit_read": credit,
        "vix_status": "absent_not_live",
        "rates_stress": rates_stress, "credit_stress": credit_stress,
        "cross_asset_risk_score": risk_score,
        "regime_filter_state": state,
        "would_be_scaler": scaler,
        "would_be_hold": state == "SHOCK",
        "assumptions": A,
    }


def observe_regime_filter(
    supabase, basket_data: Dict[str, Any],
    live_state: Any, live_risk_score: float, live_scaler: float, as_of_ts,
) -> Optional[Dict[str, Any]]:
    """Compute the regime_filter and LOG would-be (filter) vs actual (live v3)
    to OBS_TABLE. Records only — changes NO live decision. Fail-soft: a logging
    error must never affect the live regime cycle. Returns the row written (or
    None)."""
    rf = compute_regime_filter(basket_data)
    live_state_str = getattr(live_state, "value", str(live_state))
    live_hold = live_state_str == "SHOCK"
    if not rf.get("applicable"):
        row = {
            "cycle_ts": getattr(as_of_ts, "isoformat", lambda: str(as_of_ts))(),
            "rf_applicable": False, "rf_reason": rf.get("reason"),
            "vix_status": rf.get("vix_status"),
            "live_state": live_state_str, "live_risk_score": float(live_risk_score),
            "live_scaler": float(live_scaler), "live_would_hold": live_hold,
            "diverged": None, "assumptions": rf.get("assumptions"),
        }
    else:
        diverged = (rf["regime_filter_state"] != live_state_str) or (rf["would_be_hold"] != live_hold)
        row = {
            "cycle_ts": getattr(as_of_ts, "isoformat", lambda: str(as_of_ts))(),
            "rf_applicable": True,
            "rf_state": rf["regime_filter_state"],
            "rf_scaler": rf["would_be_scaler"],
            "rf_would_hold": rf["would_be_hold"],
            "cross_asset_risk_score": rf["cross_asset_risk_score"],
            "rates_return_5d": rf["rates_read"]["return_5d"],
            "rates_rv": rf["rates_read"]["rv"],
            "credit_return_5d": rf["credit_read"]["return_5d"],
            "credit_rv": rf["credit_read"]["rv"],
            "vix_status": rf["vix_status"],
            "live_state": live_state_str,
            "live_risk_score": float(live_risk_score),
            "live_scaler": float(live_scaler),
            "live_would_hold": live_hold,
            "diverged": diverged,
            "assumptions": rf["assumptions"],
        }
    try:
        supabase.table(OBS_TABLE).insert(row).execute()
    except Exception:
        return None  # fail-soft: logging must never break the live cycle
    return row
