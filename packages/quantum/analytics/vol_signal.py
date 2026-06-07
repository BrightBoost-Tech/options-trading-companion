"""Stage 1 vol-signal OBSERVE layer — raw components only, zero coupling.

OBSERVATION-ONLY. Assembles a daily snapshot of the in-house synthetic
vol-expansion signal components and logs them to vol_signal_observations,
plus a later backfill of forward outcomes. It changes NO live decision,
touches NO scanner / trading / regime computation, and persists NO
composite score.

WHY SYNTHETIC: literal VIX-family data is not entitled (2026-06-06
feasibility read: I:VIX / VIX9D / VIX3M / VVIX / SKEW / VXN / RVX all
NOT_AUTHORIZED under Stocks Starter + Options Developer). The in-house
equivalents already exist: underlying_iv_points carries daily SPY/QQQ/IWM
IV30 since 2026-02-19 (VIX/VXN/RVX analogs), IVPointService computes
skew_25d and term_slope from SPY chains, and VIX-futures ETPs
(VXX/VIXY/UVXY/SVXY) + cross-asset ETFs fetch under the stocks
entitlement.

NO COMPOSITE SCORE — deliberately. Which components predict vol expansion,
and how to weight them, is DERIVED from this record in the validation
stage. Persisting a weighted score now would bias that analysis (the
external doc hardcoded made-up weights; this layer replaces assertion
with evidence).

FAIL-SOFT, NEVER FABRICATE: a missing input (chain slice, ETP bar, IV
row) leaves its fields NULL and flags the group 'missing' in
input_status — the stale-VIX-20.0 silent-default anti-pattern is exactly
what this design avoids. Mirrors D4's regime_filter_observations pattern
(lenient flag gate, OBS_TABLE, fail-soft observe write) with #1015's
state-stamp convention.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Flag (default OFF) ─────────────────────────────────────────────────────
FLAG_ENV = "VOL_SIGNAL_OBSERVE_ENABLED"
OBS_TABLE = "vol_signal_observations"

# Synthetic IV30 series start (H14 freshness context — percentiles are
# relative to a window this young; history_window_days stamps the depth).
SERIES_START = "2026-02-19"

IV_SYMBOLS = ("SPY", "QQQ", "IWM")
ETP_SYMBOLS = ("VXX", "VIXY", "UVXY", "SVXY")
CROSS_ASSET_SYMBOLS = ("HYG", "TLT", "IEF", "LQD", "UUP")


def is_observe_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


# ── Pure computation helpers ───────────────────────────────────────────────

def percentile_rank(history: List[float], value: float) -> Optional[float]:
    """Fraction of history strictly below `value` (0..1). None on empty."""
    if not history:
        return None
    below = sum(1 for h in history if h < value)
    return below / len(history)


def compute_iv_components(iv_series: List[float]) -> Optional[Dict[str, Optional[float]]]:
    """Level / percentile / 1d / 5d change from an ascending IV30 series.

    The series is the full available history (oldest→newest, last = today).
    Returns None when the series is empty (caller flags the group missing).
    Changes that need more depth than available are None, never defaulted.
    """
    if not iv_series:
        return None
    level = iv_series[-1]
    return {
        "level": level,
        "pctl": percentile_rank(iv_series[:-1], level) if len(iv_series) > 1 else None,
        "chg_1d": (level - iv_series[-2]) if len(iv_series) >= 2 else None,
        "chg_5d": (level - iv_series[-6]) if len(iv_series) >= 6 else None,
    }


def compute_return_components(closes: List[float]) -> Optional[Dict[str, Optional[float]]]:
    """Close / 1d / 5d return from an ascending close series. None on empty."""
    if not closes:
        return None
    last = closes[-1]
    ret_1d = (last / closes[-2] - 1.0) if len(closes) >= 2 and closes[-2] else None
    ret_5d = (last / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else None
    return {"close": last, "ret_1d": ret_1d, "ret_5d": ret_5d}


def compute_rv_20d(spots: List[float]) -> Optional[float]:
    """Annualized 20d realized vol from an ascending spot series (needs 21).
    Same math as the live engine's helper, reimplemented here so this module
    imports nothing from the regime path (import-boundary requirement)."""
    if len(spots) < 21:
        return None
    subset = spots[-21:]
    rets = []
    for i in range(20):
        prev = subset[i]
        rets.append(((subset[i + 1] - prev) / prev) if prev else 0.0)
    mean = sum(rets) / 20.0
    var = sum((r - mean) ** 2 for r in rets) / 20.0
    return (var ** 0.5) * (252 ** 0.5)


# ── Row assembly ───────────────────────────────────────────────────────────

def build_observation(
    *,
    snapshot_ts: str,
    as_of_date: str,
    iv_histories: Dict[str, List[float]],
    spy_skew_25d: Optional[float],
    spy_term_slope: Optional[float],
    etp_closes: Dict[str, List[float]],
    cross_asset_closes: Dict[str, List[float]],
    live_regime_state: Optional[str],
    spy_spots: List[float],
) -> Dict[str, Any]:
    """Assemble one vol_signal_observations row from raw inputs.

    Pure: no I/O. Missing inputs → NULL fields + 'missing' in input_status.
    NO composite score is computed or persisted (validation derives weights
    from this record later — do not add one).
    """
    row: Dict[str, Any] = {
        "snapshot_ts": snapshot_ts,
        "as_of_date": as_of_date,
        "history_window_days": len(iv_histories.get("SPY") or []),
    }
    status: Dict[str, str] = {}

    # Vol levels (synthetic VIX/VXN/RVX analogs)
    for sym in IV_SYMBOLS:
        comp = compute_iv_components(iv_histories.get(sym) or [])
        key = sym.lower()
        if comp is None:
            status[f"{key}_iv30"] = "missing"
            row.update({f"{key}_iv30": None, f"{key}_iv30_pctl": None,
                        f"{key}_iv30_chg_1d": None, f"{key}_iv30_chg_5d": None})
        else:
            status[f"{key}_iv30"] = "live"
            row.update({
                f"{key}_iv30": comp["level"],
                f"{key}_iv30_pctl": comp["pctl"],
                f"{key}_iv30_chg_1d": comp["chg_1d"],
                f"{key}_iv30_chg_5d": comp["chg_5d"],
            })

    # Skew / term (computed from SPY chain by the caller; None = missing)
    row["spy_skew_25d"] = spy_skew_25d
    status["spy_skew_25d"] = "computed" if spy_skew_25d is not None else "missing"
    row["spy_term_slope"] = spy_term_slope
    status["spy_term_slope"] = "computed" if spy_term_slope is not None else "missing"

    # VIX-futures ETP proxies
    for sym in ETP_SYMBOLS:
        comp = compute_return_components(etp_closes.get(sym) or [])
        key = sym.lower()
        if comp is None:
            status[key] = "missing"
            row.update({f"{key}_close": None, f"{key}_ret_1d": None, f"{key}_ret_5d": None})
        else:
            status[key] = "live"
            row.update({f"{key}_close": comp["close"],
                        f"{key}_ret_1d": comp["ret_1d"],
                        f"{key}_ret_5d": comp["ret_5d"]})

    # Cross-asset returns
    for sym in CROSS_ASSET_SYMBOLS:
        comp = compute_return_components(cross_asset_closes.get(sym) or [])
        key = sym.lower()
        if comp is None:
            status[key] = "missing"
            row.update({f"{key}_ret_1d": None, f"{key}_ret_5d": None})
        else:
            status[key] = "live"
            row.update({f"{key}_ret_1d": comp["ret_1d"], f"{key}_ret_5d": comp["ret_5d"]})

    # Regime context (comparison only)
    row["live_regime_state"] = live_regime_state
    status["live_regime_state"] = "live" if live_regime_state else "missing"
    rv = compute_rv_20d(spy_spots or [])
    row["spy_rv_20d"] = rv
    status["spy_rv_20d"] = "computed" if rv is not None else "missing"

    row["input_status"] = status
    return row


# ── Observe write (fail-soft) ──────────────────────────────────────────────

def observe_vol_signal(supabase, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Upsert the observation row (one per as_of_date). Fail-soft: a write
    error is logged and returns None — observation must never raise into
    the host job."""
    try:
        supabase.table(OBS_TABLE).upsert(row, on_conflict="as_of_date").execute()
        return row
    except Exception as e:
        logger.warning("vol_signal observe write failed (fail-soft): %s", e)
        return None


# ── Forward-outcome backfill ───────────────────────────────────────────────

def backfill_forward_outcomes(
    supabase,
    *,
    iv_dates: List[str],
    iv_by_date: Dict[str, float],
    spot_by_date: Dict[str, float],
    book_pl_by_date: Dict[str, float],
) -> int:
    """Fill forward-outcome columns on prior rows once t+1 / t+3 data exists.

    Inputs are SPY series keyed by as_of_date (ascending `iv_dates`), plus
    aggregate book unrealized_pl by snapshot_date (paper_eod_snapshots).
    'Forward 1d/3d' = the 1st/3rd AVAILABLE trading-day row after as_of_date
    (trading-day semantics by row order, not calendar arithmetic).

    A row is stamped forwards_filled_at only when the 3d horizon is
    resolvable, so partially-fillable rows are retried next run rather than
    frozen half-empty. Returns the number of rows updated; fail-soft.
    """
    updated = 0
    try:
        pending = supabase.table(OBS_TABLE) \
            .select("id, as_of_date") \
            .is_("forwards_filled_at", "null") \
            .execute()
        rows = list(getattr(pending, "data", None) or [])
    except Exception as e:
        logger.warning("vol_signal backfill scan failed (fail-soft): %s", e)
        return 0

    date_index = {d: i for i, d in enumerate(iv_dates)}

    for obs in rows:
        d0 = str(obs.get("as_of_date"))
        i0 = date_index.get(d0)
        if i0 is None:
            continue
        if i0 + 3 >= len(iv_dates):
            continue  # 3d horizon not yet available — retry next run
        d1, d3 = iv_dates[i0 + 1], iv_dates[i0 + 3]

        patch: Dict[str, Any] = {"forwards_filled_at": "now()"}
        iv0, iv1, iv3 = iv_by_date.get(d0), iv_by_date.get(d1), iv_by_date.get(d3)
        patch["vol_forward_1d"] = (iv1 - iv0) if (iv0 is not None and iv1 is not None) else None
        patch["vol_forward_3d"] = (iv3 - iv0) if (iv0 is not None and iv3 is not None) else None

        s0, s1, s3 = spot_by_date.get(d0), spot_by_date.get(d1), spot_by_date.get(d3)
        patch["spy_forward_1d"] = (s1 / s0 - 1.0) if (s0 and s1) else None
        patch["spy_forward_3d"] = (s3 / s0 - 1.0) if (s0 and s3) else None

        b0, b1 = book_pl_by_date.get(d0), book_pl_by_date.get(d1)
        patch["book_forward_1d"] = (b1 - b0) if (b0 is not None and b1 is not None) else None

        try:
            supabase.table(OBS_TABLE).update(patch).eq("id", obs["id"]).execute()
            updated += 1
        except Exception as e:
            logger.warning("vol_signal backfill update failed for %s (fail-soft): %s",
                           obs.get("id"), e)
    return updated
