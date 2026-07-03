"""Gap-3(a) — shadow-ledger promotion-time normalization (2026-07-03).

Champion promotion compared a REAL book to a 100%-fill fiction: shadow
cohorts fill synthetically at 5–17× live size (twin magnitudes ran 3–45×;
SOFI shadow −1,044.48 vs live twin −40) and fill every order, while the
live book fills ~1/3 (measured: 17 of 55 live orders as of 2026-07-03; the
NFLX watchdog-cancel class). This module normalizes the comparison basis
at PROMOTION READ TIME ONLY — `policy_daily_scores` ledger rows are never
mutated (move-don't-lose):

1. PER-CONTRACT: every dollar field is divided by the cohort's contract
   exposure attributable to that trade_date (both sides — this is the
   comparison basis, not a penalty).
2. FILL-DISCOUNT: challenger (shadow-only) rows are scaled by the MEASURED
   live fill rate — the expected contribution a real book would have
   captured. Symmetric by design (gains AND losses scale: it is a
   probability-of-existence model, not a haircut). The champion (live
   book) is NEVER discounted.

Flag `SHADOW_PROMOTION_NORMALIZATION_ENABLED` — measurement-basis
correction (the #1052 class, not a loosening): default-ON; only explicit
falsy disables. `SHADOW_FILL_DISCOUNT` is a MEASURED constant (default
0.31 = 17/55 live fills at derivation time) — re-derive from live
fill-rate data as volume grows; never hand-tuned.

Consumed ONLY by policy_lab.evaluator.check_promotion (governance);
no trading path imports this module (test-pinned).
"""

import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FALSY = ("0", "false", "no", "off")

# Dollar-denominated fields on policy_daily_scores rows. Percent/quality
# fields (max_drawdown_pct, win_rate, execution_quality, ...) are already
# scale-free and are deliberately untouched — the rollback check reads
# max_drawdown_pct and must see the same number it always saw.
DOLLAR_FIELDS = (
    "realized_pnl",
    "unrealized_pnl",
    "expected_shortfall",
    "avg_winner",
    "avg_loser",
)


def is_enabled() -> bool:
    raw = (os.getenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED") or "").strip().lower()
    return raw not in _FALSY


def fill_discount() -> float:
    """Measured live fill rate (17/55 = 0.309 at derivation, 2026-07-03)."""
    try:
        v = float(os.getenv("SHADOW_FILL_DISCOUNT", "0.31"))
        return v if 0.0 < v <= 1.0 else 0.31
    except (TypeError, ValueError):
        return 0.31


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        if "T" in s or " " in s:
            return datetime.fromisoformat(s.replace(" ", "T", 1)).date()
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def daily_contract_divisor(
    positions: List[Dict[str, Any]], trade_date: Any
) -> float:
    """Contract exposure attributable to `trade_date` for one cohort.

    A position counts toward a date when it was OPEN during it or CLOSED on
    it: created_at::date <= d AND (closed_at is NULL OR closed_at::date >= d).
    Divisor floors at 1.0 — a day with no attributable positions divides by
    one (identity), never fabricates a scale (H9)."""
    d = _to_date(trade_date)
    if d is None:
        return 1.0
    total = 0.0
    for p in positions:
        opened = _to_date(p.get("created_at"))
        closed = _to_date(p.get("closed_at"))
        if opened is None or opened > d:
            continue
        if closed is not None and closed < d:
            continue
        try:
            total += abs(float(p.get("quantity") or 0))
        except (TypeError, ValueError):
            continue
    return total if total >= 1.0 else 1.0


def normalize_promotion_rows(
    rows: List[Dict[str, Any]],
    positions_by_cohort: Dict[str, List[Dict[str, Any]]],
    champion_id: str,
) -> List[Dict[str, Any]]:
    """Return NORMALIZED COPIES of policy_daily_scores rows for promotion
    scoring. Inputs are never mutated (the caller's rows stay ledger-true).

    Per-contract division applies to every cohort (comparison basis);
    the fill-discount multiplies challenger (non-champion) rows only.
    Disabled flag → the original list, byte-identical.
    """
    if not is_enabled():
        return rows
    discount = fill_discount()
    out: List[Dict[str, Any]] = []
    for r in rows:
        cid = r.get("cohort_id")
        divisor = daily_contract_divisor(
            positions_by_cohort.get(cid, []), r.get("trade_date")
        )
        scale = (1.0 / divisor) * (1.0 if cid == champion_id else discount)
        nr = dict(r)
        for f in DOLLAR_FIELDS:
            if r.get(f) is not None:
                try:
                    nr[f] = float(r[f]) * scale
                except (TypeError, ValueError):
                    pass  # unparseable → leave as-is, never fabricate
        out.append(nr)
    return out


def fetch_cohort_positions(
    supabase: Any, cohort_ids: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """One read of the cohorts' positions for divisor math. Deliberately
    UNFILTERED by date: a position opened before the promotion window but
    still open inside it carries exposure (the per-day attribution happens
    in daily_contract_divisor). Cohort position sets are small.

    Failure → {} which makes every divisor 1.0 (per-contract normalization
    degrades to identity while the discount still applies) — logged as a
    WARNING so the degradation is visible, never silent."""
    by_cohort: Dict[str, List[Dict[str, Any]]] = {}
    try:
        res = (
            supabase.table("paper_positions")
            .select("cohort_id, quantity, created_at, closed_at")
            .in_("cohort_id", cohort_ids)
            .execute()
        )
        for p in res.data or []:
            by_cohort.setdefault(p.get("cohort_id"), []).append(p)
    except Exception as e:
        logger.warning(
            f"[PROMOTION_NORM] cohort position fetch failed — per-contract "
            f"divisors degrade to 1.0 this eval (discount still applies): {e}"
        )
    return by_cohort
