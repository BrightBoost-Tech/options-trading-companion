"""One-beta bucket control + same-run reservation (B1/B2, P0-B, 2026-07-12) —
OBSERVE-FIRST. Governs CONCURRENT defined-risk exposure per correlation bucket,
and reserves budget/exposure as each candidate commits within one executor
cycle (the allocator-overspend fix).

Fourth Option-A observe→enforce application (after #1034 exit-mark, #1116
mark-write, PR-A risk-basis). Flag BUCKET_CONTROL_ENFORCE default OFF: compute
+ log [BUCKET_SHADOW] + fire the #1139-class alarm on a would-block that
PROCEEDS; when armed, reject with an honest bucket_exposure_cap stamp. Honest
basis (max_loss_total) where present; legacy-NULL rows count at premium basis
WITH a logged caveat (H9 — never fabricated).
"""
import os
import logging

logger = logging.getLogger(__name__)

# Beta buckets as DATA (extendable). {SPY,DIA,QQQ,IWM} move together — the
# us_equity_beta bucket (the 2026-06-11/12 3-concurrent-position class); every
# other symbol is its own bucket initially.
_US_EQUITY_BETA = frozenset({"SPY", "DIA", "QQQ", "IWM"})


def bucket_for(ticker) -> str:
    t = (ticker or "").upper().strip()
    if t in _US_EQUITY_BETA:
        return "us_equity_beta"
    return t or "unknown"


def is_bucket_enforce_enabled() -> bool:
    """Behavioral opt-in (§3): ONLY '=1' rejects. Default OFF → observe."""
    return (os.environ.get("BUCKET_CONTROL_ENFORCE") or "").strip() == "1"


def bucket_max_pct() -> float:
    """BUCKET_MAX_PCT of equity per bucket. Default 0.25 — at a ~$2k book one IC
    ≈18% fits; a second same-bucket IC ≈36% does not (so 0.25 allows one IC +
    nothing same-bucket; 0.40 would allow two)."""
    try:
        v = float(os.environ.get("BUCKET_MAX_PCT") or "0.25")
        return v if v > 0 else 0.25
    except (TypeError, ValueError):
        return 0.25


def _risk_from_fields(max_loss_total, cost_basis_total):
    """(usd, is_legacy_premium, is_unknown): honest max_loss_total if present, else
    premium (cost_basis_total) WITH the legacy caveat, else (0.0, True, True) —
    UNKNOWN risk is flagged EXPLICITLY (W3), never silently a $0 that hides missing
    exposure. Callers must treat is_unknown as not-armable, not as zero risk."""
    try:
        if max_loss_total is not None:
            return abs(float(max_loss_total)), False, False
    except (TypeError, ValueError):
        pass
    try:
        if cost_basis_total is not None:
            return abs(float(cost_basis_total)), True, False
    except (TypeError, ValueError):
        pass
    return 0.0, True, True


def position_risk_usd(pos):
    return _risk_from_fields(pos.get("max_loss_total"), pos.get("cost_basis_total"))


def candidate_risk_usd(suggestion):
    """(usd, is_legacy_premium, is_unknown) for a CANDIDATE. Honest max_loss_total
    if the suggestion carries it; else the premium basis (limit×contracts×100);
    else UNKNOWN (0.0, True, True) — flagged, never a silent zero (W3)."""
    ml = suggestion.get("max_loss_total")
    if ml is None:
        ml = (suggestion.get("sizing_metadata") or {}).get("max_loss_total")
    if ml is not None:
        return _risk_from_fields(ml, None)
    oj = suggestion.get("order_json") or {}
    try:
        prem = abs(float(oj.get("limit_price") or 0)) * float(oj.get("contracts") or 0) * 100.0
        if prem > 0:
            return prem, True, False
    except (TypeError, ValueError):
        pass
    return 0.0, True, True


class BucketReservations:
    """Same-run reservation: accumulate committed candidates' bucket exposure
    WITHIN one executor cycle so candidate #2 sees #1's reservation."""
    def __init__(self):
        self._by_bucket = {}

    def reserved(self, bucket) -> float:
        return self._by_bucket.get(bucket, 0.0)

    def add(self, bucket, usd):
        try:
            self._by_bucket[bucket] = self._by_bucket.get(bucket, 0.0) + max(0.0, float(usd or 0))
        except (TypeError, ValueError):
            pass


def evaluate_bucket(candidate_ticker, candidate_risk, open_positions,
                    reservations, equity_usd, candidate_unknown=False):
    """Compute bucket exposure + would_block + the W3 not-armable signals. Pure;
    observe-only unless the caller enforces. exposure = Σ(open positions in the
    bucket) + reserved + the candidate, vs BUCKET_MAX_PCT × equity.

    W3 (2026-07-12): UNKNOWN open/candidate risk is COUNTED and surfaced
    (`unknown_risk_present`, `unknown_open_count`), NEVER folded into $0 silently;
    and `equity_readable` (cap>0) is exposed. `not_armable` = unknown risk present
    OR equity unreadable — the state where an ARMED enforcement cannot safely
    decide and must fail-CLOSED (see bucket_enforcement_action). Observe behavior
    is byte-identical (would_block unchanged)."""
    bucket = bucket_for(candidate_ticker)
    open_sum = 0.0
    legacy_any = False
    unknown_open = 0
    for p in open_positions or []:
        if bucket_for(p.get("symbol")) != bucket:
            continue
        v, legacy, unknown = position_risk_usd(p)
        open_sum += v
        legacy_any = legacy_any or (legacy and v > 0)
        if unknown:
            unknown_open += 1
    reserved = reservations.reserved(bucket) if reservations else 0.0
    cand = max(0.0, float(candidate_risk or 0))
    total = open_sum + reserved + cand
    cap = bucket_max_pct() * float(equity_usd or 0)
    would_block = cap > 0 and total > cap
    equity_readable = cap > 0
    unknown_risk_present = bool(candidate_unknown) or unknown_open > 0
    not_armable = unknown_risk_present or not equity_readable
    return {
        "bucket": bucket,
        "open_exposure": round(open_sum, 2),
        "reserved": round(reserved, 2),
        "candidate": round(cand, 2),
        "total_with_candidate": round(total, 2),
        "cap": round(cap, 2),
        "equity": round(float(equity_usd or 0), 2),
        "bucket_max_pct": bucket_max_pct(),
        "would_block": would_block,
        "legacy_premium_basis": legacy_any,
        "unknown_open_count": unknown_open,
        "candidate_unknown": bool(candidate_unknown),
        "unknown_risk_present": unknown_risk_present,
        "equity_readable": equity_readable,
        "not_armable": not_armable,
    }


def bucket_enforcement_action(decision, armed):
    """(action, reason). action ∈ {'block','alarm','proceed'} — the SINGLE
    enforcement seam (testable without driving the executor).

    ARMED: a cap breach → block('bucket_exposure_cap'); a not-armable state
    (unknown risk / unreadable equity) → block('bucket_not_armable_unknown_risk')
    — the W3 NON-NEGOTIABLE: an armed unknown-risk case is NEVER a silent-zero
    proceed. OBSERVE: a cap breach → alarm('bucket_exposure_would_block') +
    proceed; everything else proceeds (the not-armable state is logged in the
    shadow line, no observe-time block)."""
    if armed:
        if decision.get("would_block"):
            return "block", "bucket_exposure_cap"
        if decision.get("not_armable"):
            return "block", "bucket_not_armable_unknown_risk"
        return "proceed", None
    if decision.get("would_block"):
        return "alarm", "bucket_exposure_would_block"
    return "proceed", None


def log_bucket_shadow(decision):
    logger.info("[BUCKET_SHADOW] %s", decision)
