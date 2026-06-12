"""Layer-1 exit mark-sanity gate — OBSERVE-ONLY, asymmetric, fail-safe.

At a mark-derived exit fire (target_profit / stop_loss), this corroborates
the mark the monitor ACTED ON against the ACHIEVABLE close computed from the
executable side of live two-sided leg quotes (sell→bid, buy→ask). It writes
one verdict row to exit_mark_corroboration_observations and changes NOTHING:
no exit-path branch reads the verdict, and `would_suppress` is a logged
hypothesis, never an action. The flag-on and flag-off exit behavior is
byte-identical.

WHY (2026-06-08): the 13:30:02Z first-post-open pass fired
intraday_target_profit on a phantom opening-auction mark (+$325) the NFLX
position never held — the achievable close was ~−$36 (P85 bid 4.28 − P79
ask 1.38 = 2.90 net vs 3.08 entry, one leg quoting 0.0). The phantom-profit
limit staged ABOVE the real market and harmlessly expired. We want to learn
whether mark-corroboration reliably catches these opening transients BEFORE
ever letting it suppress a fire.

INVARIANTS:
1. OBSERVE-ONLY — writes a row, nothing else; no exit branch reads it.
2. FAIL-SAFE — the whole computation is wrapped; ANY error lets the exit
   proceed unchanged (observe_exit_mark never raises; the monitor call site
   also wraps it). A gate bug can never stop a protective exit.
3. ASYMMETRIC — would_suppress may be TRUE only for target_profit. For
   stop_loss it is ALWAYS false: a real adverse move sees a genuinely low
   mark and wide/one-sided quotes — structurally identical to a phantom —
   so suppressing on "uncorroborated mark" would gag the protection exactly
   when needed. The loss side is Layer-2's fill problem, never a suppression
   target.
4. NEVER FABRICATE — missing/one-sided leg quotes are recorded explicitly
   (which legs, what was missing); absence is not silently treated as
   corroborated. For target_profit an incomplete two-sided quote is the
   PRIMARY uncorroborated condition.

NO score, NO weights — raw components + verdict, same philosophy as the
other observe layers.

STAGE-2 (2026-06-12): a separate ENFORCE flag now exists —
EXIT_MARK_SANITY_ENFORCE_ENABLED (default OFF, lenient truthy parse). When
ON, the monitor call site suppresses a TARGET_PROFIT force-close whose
observation row says would_suppress=true (the row is still written — the
suppression is the evidence trail). The asymmetry is enforced TWICE:
compute_corroboration never sets would_suppress for stop_loss (invariant 3),
AND the call-site branch only fires for target_profit. stop_loss and the
date-derived exits are untouchable by this flag. With the flag OFF (or on
any corroboration error — would_suppress is forced False on the error
path), behavior is byte-identical to Stage-1 observe-only.

Evidence basis for Stage-2: the 06-12 13:30Z QQQ condor fire — triggering
mark −0.65 (+$96) vs achievable −7.60 (−$599) on a degenerate C750 quote
(bid 0.76 / ask 14.09) — re-scores under the 06-12 price normalization to
divergence_frac ≈ 0.914 → would_suppress=divergence_exceeded. The close it
staged was unfillable and watchdog-cancelled 5 minutes later; enforcement
exists so the next one is never staged.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from packages.quantum.risk.mark_math import compute_current_value, finalize_mark

logger = logging.getLogger(__name__)

FLAG_ENV = "EXIT_MARK_SANITY_OBSERVE_ENABLED"
ENFORCE_FLAG_ENV = "EXIT_MARK_SANITY_ENFORCE_ENABLED"
OBS_TABLE = "exit_mark_corroboration_observations"

# Only mark-derived exits are corroborated. expiration_day / dte_threshold are
# date-derived (a quote can't make a calendar date a phantom) and never logged.
GATED_EXIT_TYPES = ("target_profit", "stop_loss")

# ⚠️ PROVISIONAL — TO BE CALIBRATED from the observed divergence_frac
# distribution once rows accumulate. This is a PLACEHOLDER, not a validated
# threshold: it only populates would_suppress in the OBSERVE record and is
# NEVER enforced. Do not treat this number as tuned. Stage-2 enforcement must
# re-derive it from data showing would_suppress fires only on opening
# transients and never on a real target.
PROVISIONAL_DIVERGENCE_FRAC_TOLERANCE = 0.10

# suppress_reason enum
_REASON_QUOTE_INCOMPLETE = "quote_incomplete"
_REASON_DIVERGENCE_EXCEEDED = "divergence_exceeded"
_REASON_CORROBORATED_ALLOW = "corroborated_allow"
_REASON_STOP_LOSS_NEVER = "stop_loss_never_suppress"
_REASON_CORROBORATION_ERROR = "corroboration_error"


def is_observe_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def is_enforce_enabled() -> bool:
    """Stage-2 flag — lenient truthy parse, default OFF. Behavioral opt-in:
    absent/empty/anything-else → Stage-1 observe-only behavior exactly."""
    return os.environ.get(ENFORCE_FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def _leg_action(leg: Dict[str, Any]) -> str:
    return str(leg.get("action") or leg.get("side") or "buy").lower()


def _leg_occ(leg: Dict[str, Any]) -> str:
    return leg.get("occ_symbol") or leg.get("symbol") or ""


def _spread_width(legs: List[Dict[str, Any]]) -> Optional[float]:
    """max strike − min strike across legs; None for single-leg / no strikes."""
    strikes = []
    for leg in legs:
        if isinstance(leg, dict) and leg.get("strike") is not None:
            try:
                strikes.append(float(leg["strike"]))
            except (TypeError, ValueError):
                pass
    if len(strikes) < 2:
        return None
    return max(strikes) - min(strikes)


def compute_corroboration(
    *,
    exit_type: str,
    triggering_mark: Optional[float],
    triggering_implied_pl: Optional[float],
    quantity: Any,
    avg_entry_price: Any,
    legs: List[Dict[str, Any]],
    leg_quotes: Dict[str, Dict[str, Any]],
    tolerance: float = PROVISIONAL_DIVERGENCE_FRAC_TOLERANCE,
) -> Dict[str, Any]:
    """Pure verdict computation. Never raises for ordinary data shapes.

    `leg_quotes` is keyed by each leg's OCC symbol → {bid, ask, last}. The
    achievable close uses the EXECUTABLE side (long leg → sell to close → bid;
    short leg → buy to close → ask) and reuses the monitor's own
    compute_current_value / finalize_mark, so signs match the trigger exactly
    (this reproduces the broker's achievable −$36 on the NFLX case).

    Returns the row fields minus identity/timestamp. would_suppress is
    asymmetric: stop_loss is ALWAYS false.
    """
    legs = [l for l in (legs or []) if isinstance(l, dict)]

    # Per-leg quote record + completeness — NEVER fabricated.
    legs_quotes: List[Dict[str, Any]] = []
    quote_complete = bool(legs)
    action_by_occ: Dict[str, str] = {}
    for leg in legs:
        occ = _leg_occ(leg)
        action = _leg_action(leg)
        action_by_occ[occ] = action
        q = leg_quotes.get(occ) or {}
        bid = q.get("bid")
        ask = q.get("ask")
        try:
            bid_f = float(bid) if bid is not None else 0.0
        except (TypeError, ValueError):
            bid_f = 0.0
        try:
            ask_f = float(ask) if ask is not None else 0.0
        except (TypeError, ValueError):
            ask_f = 0.0
        is_long = action in ("buy", "long")
        executable_side = "bid" if is_long else "ask"
        executable_price = bid_f if is_long else ask_f
        missing = []
        if bid_f <= 0:
            missing.append("bid")
        if ask_f <= 0:
            missing.append("ask")
        if missing:
            quote_complete = False
        legs_quotes.append({
            "occ": occ,
            "action": action,
            "position_side": "long" if is_long else "short",
            "bid": bid_f if bid_f > 0 else None,
            "ask": ask_f if ask_f > 0 else None,
            "last": q.get("last"),
            "executable_side": executable_side,
            "executable_price": executable_price if executable_price > 0 else None,
            "missing": missing,
        })

    # Achievable close from the executable side, via the monitor's mark math.
    def _executable_for(occ: str) -> Optional[float]:
        q = leg_quotes.get(occ) or {}
        is_long = action_by_occ.get(occ, "buy") in ("buy", "long")
        raw = q.get("bid") if is_long else q.get("ask")
        try:
            val = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            val = 0.0
        return val if val > 0 else None

    achievable_close = None
    achievable_implied_pl = None
    if legs:
        # failed_legs makes compute_current_value all-or-nothing: if ANY
        # priceable leg lacks an executable price it returns None (we do not
        # fabricate a partial close from only the legs that quoted).
        _failed: List[str] = []
        achievable_value = compute_current_value(
            legs, _executable_for, quantity, failed_legs=_failed
        )
        if achievable_value is not None:
            achievable_close, achievable_implied_pl = finalize_mark(
                quantity, avg_entry_price, achievable_value
            )

    spread_width = _spread_width(legs)

    divergence_abs = None
    if triggering_implied_pl is not None and achievable_implied_pl is not None:
        divergence_abs = float(triggering_implied_pl) - float(achievable_implied_pl)

    # 06-12 normalization fix: the original denominator was _spread_width
    # (max strike − min strike — 115 for the QQQ condor), which scored the
    # 06-12 13:30Z fire — triggering mark −0.65 vs achievable −7.60, a 7×
    # mark divergence with implied P&L +$96 vs −$599 — at 0.060 and verdict
    # 'corroborated_allow'. A divergence is a PRICE disagreement; normalize
    # by the price (|achievable_close|, floored so near-worthless spreads
    # don't divide by ~0), never by the strike geometry. Yesterday's row
    # re-scores to |−0.65 − (−7.60)| / 7.60 ≈ 0.914 → would_suppress under
    # any sane tolerance. spread_width stays recorded for reference only.
    # Observe-only is unchanged: this fixes the measurement, not the policy.
    divergence_frac = None
    if triggering_mark is not None and achievable_close is not None:
        try:
            _floor = float(os.environ.get("MARK_DIVERGENCE_DENOM_FLOOR", "0.10"))
        except ValueError:
            _floor = 0.10
        _denom = max(abs(float(achievable_close)), _floor)
        divergence_frac = (float(triggering_mark) - float(achievable_close)) / _denom

    # Verdict — ASYMMETRIC.
    if exit_type == "stop_loss":
        would_suppress = False
        suppress_reason = _REASON_STOP_LOSS_NEVER
    elif exit_type == "target_profit":
        if not quote_complete:
            # PRIMARY uncorroborated condition for profit-taking (the NFLX
            # 0.0-leg case). A profit-take on an incomplete two-sided quote is
            # deliberately treated as uncorroborated — safe, since a phantom
            # profit limit can't fill anyway.
            would_suppress = True
            suppress_reason = _REASON_QUOTE_INCOMPLETE
        elif divergence_frac is not None and abs(divergence_frac) > tolerance:
            would_suppress = True
            suppress_reason = _REASON_DIVERGENCE_EXCEEDED
        else:
            would_suppress = False
            suppress_reason = _REASON_CORROBORATED_ALLOW
    else:
        # Should not happen (call site gates to GATED_EXIT_TYPES); be safe.
        would_suppress = False
        suppress_reason = _REASON_CORROBORATED_ALLOW

    return {
        "exit_type": exit_type,
        "triggering_mark": _num(triggering_mark),
        "triggering_implied_pl": _num(triggering_implied_pl),
        "legs_quotes": legs_quotes,
        "quote_complete": quote_complete,
        "achievable_close": _num(achievable_close),
        "achievable_implied_pl": _num(achievable_implied_pl),
        "divergence_abs": _num(divergence_abs),
        "divergence_frac": _num(divergence_frac),
        "spread_width": _num(spread_width),
        "provisional_tolerance": tolerance,
        "would_suppress": would_suppress,
        "suppress_reason": suppress_reason,
        "corroboration_error": None,
    }


def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fetch_leg_quotes(legs: List[Dict[str, Any]], snapshot_fn: Callable) -> Dict[str, Dict[str, Any]]:
    """Live per-leg quotes from the SAME source staging uses
    (MarketDataTruthLayer.snapshot_many — single quote source of truth; this
    is a fresh call to that one provider, not a second feed). Returns {occ →
    {bid, ask, last}}; missing/zero values are preserved, never fabricated."""
    occs = [_leg_occ(l) for l in legs if isinstance(l, dict) and _leg_occ(l)]
    if not occs:
        return {}
    snaps = snapshot_fn(occs) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for occ in occs:
        snap = snaps.get(occ) or {}
        q = snap.get("quote", snap) if isinstance(snap, dict) else {}
        out[occ] = {"bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last")}
    return out


def executable_close_estimate(
    position_like: Dict[str, Any], snapshot_fn: Optional[Callable] = None
) -> Dict[str, Any]:
    """Executable-side (long→sell at bid, short→buy at ask) close estimate
    for a position-shaped dict — the SAME computation the gate corroborates
    with, exposed for the internal-fill path (#1017 class: shadow fills must
    not book the optimistic mid when the executable side is known).

    Returns {achievable_close, achievable_implied_pl, quote_complete,
    legs_quotes}. achievable_close is None when any priceable leg lacks an
    executable side (all-or-nothing — never a partial fabrication). May
    raise on quote-fetch failure; the caller owns the fallback decision."""
    legs = position_like.get("legs") or []
    if snapshot_fn is None:
        from packages.quantum.services.market_data_truth_layer import (
            MarketDataTruthLayer,
        )
        snapshot_fn = MarketDataTruthLayer().snapshot_many
    leg_quotes = _fetch_leg_quotes(legs, snapshot_fn)
    v = compute_corroboration(
        exit_type="target_profit",  # verdict fields unused by this caller
        triggering_mark=None,
        triggering_implied_pl=None,
        quantity=position_like.get("quantity"),
        avg_entry_price=position_like.get("avg_entry_price"),
        legs=legs,
        leg_quotes=leg_quotes,
    )
    return {
        "achievable_close": v["achievable_close"],
        "achievable_implied_pl": v["achievable_implied_pl"],
        "quote_complete": v["quote_complete"],
        "legs_quotes": v["legs_quotes"],
    }


def observe_exit_mark(
    supabase,
    *,
    position: Dict[str, Any],
    exit_type: str,
    triggering_mark: Optional[float],
    triggering_implied_pl: Optional[float],
    job_run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    snapshot_fn: Optional[Callable] = None,
) -> Optional[Dict[str, Any]]:
    """Fully fail-safe observe entrypoint. Computes the corroboration verdict
    for a mark-derived exit fire and writes one row. NEVER raises — any error
    (quote fetch, math, DB write) is caught and recorded as a
    corroboration_error row (would_suppress forced False) so the calling
    monitor's exit always proceeds unchanged.

    Returns the written row dict, or None on the deepest failure. Only
    target_profit / stop_loss are accepted; anything else is ignored.
    """
    if exit_type not in GATED_EXIT_TYPES:
        return None

    base_identity = {
        "job_run_id": job_run_id,
        "user_id": user_id,
        "position_id": position.get("id") if isinstance(position, dict) else None,
        "symbol": position.get("symbol") if isinstance(position, dict) else None,
    }
    try:
        legs = position.get("legs") or []
        if snapshot_fn is None:
            from packages.quantum.services.market_data_truth_layer import (
                MarketDataTruthLayer,
            )
            snapshot_fn = MarketDataTruthLayer().snapshot_many
        leg_quotes = _fetch_leg_quotes(legs, snapshot_fn)
        verdict = compute_corroboration(
            exit_type=exit_type,
            triggering_mark=triggering_mark,
            triggering_implied_pl=triggering_implied_pl,
            quantity=position.get("quantity"),
            avg_entry_price=position.get("avg_entry_price"),
            legs=legs,
            leg_quotes=leg_quotes,
        )
        row = {**base_identity, **verdict}
    except Exception as e:
        # Fail-open record: an error must NOT claim a suppression and must NOT
        # break the exit. would_suppress=False per the asymmetric invariant.
        logger.warning(
            "[EXIT_MARK_SANITY] corroboration failed (non-fatal, observe-only): %s", e
        )
        row = {
            **base_identity,
            "exit_type": exit_type,
            "would_suppress": False,
            "suppress_reason": _REASON_CORROBORATION_ERROR,
            "corroboration_error": str(e)[:500],
        }

    try:
        supabase.table(OBS_TABLE).insert(row).execute()
    except Exception as e:
        logger.warning("[EXIT_MARK_SANITY] observe write failed (non-fatal): %s", e)
        return None
    return row
