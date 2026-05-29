"""D2 Phase 1 — momentum / extended-move signals + candidate EV tempers (pure, log-only).

Addresses the trader's core critique: the system has no "already ran +44-75%"
signal anywhere — EV is computed off current price/IV, the ranker has no run-up
term, and the RSI computed in factors.py is never consumed by selection. This
module computes those signals from the bars the scanner ALREADY fetches and
evaluates candidate EV-tempers that DISCOUNT momentum-following entries.

OBSERVATION-ONLY: signals and tempers are LOGGED, never applied to the real
EV/score/ranking/selection. The promote/calibrate decision is separate and gated
on whether the signal actually predicts realized outcomes.

KEY FRAMING: a momentum signal's correct WEIGHT is unknown a priori. The trader's
critique gives the SIGN (run-up in the trade's direction should discount a
momentum-following entry), not the magnitude. Hard-wiring a guessed weight into
selection is worse than no signal (too aggressive would have rejected F, which
won). The temper magnitudes below are explicit GUESSES, logged so the data can
later show which magnitude — if any — would have helped. H15: the temper reads
the honest EV the ranker uses and logs a would-be ADJUSTED value; the real EV is
untouched.
"""

from typing import Any, Dict, List, Optional

from packages.quantum.analytics.factors import calculate_indicators_vectorized

# Candidate temper magnitudes — GUESSES, to be calibrated against realized
# outcomes later (NOT applied to real selection). Documented so the observed
# data can reveal which, if any, would have helped.
T1_RUNUP_K = 0.5          # haircut per unit of signed 20d run-up (e.g. +20% run → 0.10 haircut)
T1_MAX_HAIRCUT = 0.30
T2_EXTENSION_K = 0.8      # haircut per unit of favorable distance-from-SMA20
T2_MAX_HAIRCUT = 0.30
T3_RSI_HAIRCUT = 0.20     # flat haircut when RSI is extended in the trade's direction
T3_RSI_OVERBOUGHT = 70.0
T3_RSI_OVERSOLD = 30.0


def _pct_change(closes: List[float], lookback: int) -> Optional[float]:
    if len(closes) <= lookback:
        return None
    prior = closes[-1 - lookback]
    if not prior:
        return None
    return closes[-1] / prior - 1.0


def _sma_distance(closes: List[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    window_slice = closes[-window:]
    sma = sum(window_slice) / len(window_slice)
    if not sma:
        return None
    return closes[-1] / sma - 1.0


def direction_from_strategy(strategy: Optional[str]) -> str:
    """Map a strategy name to its directional bias for alignment scoring."""
    s = (strategy or "").upper()
    if "IRON_CONDOR" in s:
        return "neutral"
    # bullish: long calls / call debit / put credit (short put)
    if "LONG_CALL" in s or "CALL_DEBIT" in s or "PUT_CREDIT" in s or "SHORT_PUT" in s:
        return "bullish"
    # bearish: long puts / put debit / call credit (short call)
    if "LONG_PUT" in s or "PUT_DEBIT" in s or "CALL_CREDIT" in s or "SHORT_CALL" in s:
        return "bearish"
    return "neutral"


def compute_momentum_signals(
    closes: List[float],
    direction: str,
) -> Dict[str, Any]:
    """Compute momentum / extended-move signals from the underlying daily closes
    (oldest→newest). Pure; tolerant of short history (fields → None).

    ``signed_run_up_in_direction`` is the 20d run-up signed so POSITIVE means the
    underlying already moved in the trade's favor (a momentum-following entry);
    ``momentum_following`` is the boolean of that.
    """
    closes = [float(c) for c in (closes or []) if c is not None]
    sig: Dict[str, Any] = {
        "direction": direction,
        "bars_available": len(closes),
        "run_up_5d": _pct_change(closes, 5),
        "run_up_10d": _pct_change(closes, 10),
        "run_up_20d": _pct_change(closes, 20),
        "dist_from_sma20": _sma_distance(closes, 20),
        "dist_from_sma50": _sma_distance(closes, 50),
        "rsi": None,
        "signed_run_up_in_direction": None,
        "momentum_following": None,
    }

    if len(closes) >= 15:
        rsi_arr = calculate_indicators_vectorized(closes).get("rsi")
        if rsi_arr is not None and len(rsi_arr) > 0:
            sig["rsi"] = float(rsi_arr[-1])

    sign = {"bullish": 1.0, "bearish": -1.0}.get(direction, 0.0)
    run20 = sig["run_up_20d"]
    if sign != 0.0 and run20 is not None:
        signed = sign * run20
        sig["signed_run_up_in_direction"] = signed
        sig["momentum_following"] = signed > 0  # already moved our way → following
    return sig


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def evaluate_tempers(
    ev: Optional[float],
    score: Optional[float],
    signals: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Compute candidate EV/score tempers (T1-T4) as would-be ADJUSTED values.

    PURE and LOG-ONLY: returns what each temper WOULD do; never mutates ev/score.
    A haircut of h means would_be_ev = ev*(1-h). Tempers only DISCOUNT (never
    boost) — the hypothesis is that momentum-following/over-extended entries are
    worse, not that anything is better.
    """
    ev = float(ev) if ev is not None else None
    score = float(score) if score is not None else None
    direction = signals.get("direction", "neutral")
    sign = {"bullish": 1.0, "bearish": -1.0}.get(direction, 0.0)

    def _apply(haircut: float, driver: str) -> Dict[str, Any]:
        h = _clamp(haircut, 0.0, 1.0)
        return {
            "haircut": round(h, 4),
            "would_be_ev": round(ev * (1 - h), 4) if ev is not None else None,
            "would_be_score": round(score * (1 - h), 4) if score is not None else None,
            "driver": driver,
        }

    # T1 — run-up discount: signed 20d run-up in the trade's direction.
    signed_run = signals.get("signed_run_up_in_direction")
    if signed_run is not None and signed_run > 0:
        t1 = _apply(_clamp(signed_run * T1_RUNUP_K, 0.0, T1_MAX_HAIRCUT),
                    f"run_up_20d_in_direction={signed_run:.3f}")
    else:
        t1 = _apply(0.0, "no_favorable_run_up")

    # T2 — extension discount: favorable distance-from-SMA20.
    dist20 = signals.get("dist_from_sma20")
    if dist20 is not None and sign != 0.0 and (sign * dist20) > 0:
        t2 = _apply(_clamp(abs(dist20) * T2_EXTENSION_K, 0.0, T2_MAX_HAIRCUT),
                    f"dist_from_sma20_in_direction={sign*dist20:.3f}")
    else:
        t2 = _apply(0.0, "not_extended_in_direction")

    # T3 — RSI extended in the trade's direction (overbought bullish / oversold bearish).
    rsi = signals.get("rsi")
    if rsi is not None and (
        (direction == "bullish" and rsi >= T3_RSI_OVERBOUGHT)
        or (direction == "bearish" and rsi <= T3_RSI_OVERSOLD)
    ):
        t3 = _apply(T3_RSI_HAIRCUT, f"rsi_extended={rsi:.1f}")
    else:
        t3 = _apply(0.0, "rsi_not_extended")

    # T4 — combined (1 - product of survivors), capped.
    combined_h = 1.0 - (1 - t1["haircut"]) * (1 - t2["haircut"]) * (1 - t3["haircut"])
    t4 = _apply(_clamp(combined_h, 0.0, 0.5), "combined_T1_T2_T3")

    return {"T1": t1, "T2": t2, "T3": t3, "T4": t4}
