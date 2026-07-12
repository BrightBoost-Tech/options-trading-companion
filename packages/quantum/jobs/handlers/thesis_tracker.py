"""Shadow-to-expiry THESIS TRACKER (I5, 2026-07-11) — OBSERVE-ONLY daily job.

Every tracked closed position (live_eligible + shadow_only cohorts) has its
ENTRY THESIS followed to its ORIGINAL expiry and scored hit/miss against the
underlying's price there — independent of fills / P&L. This converts every
force-close into a completed counterfactual and turns the provisional ~78%
spot-score into a standing number. Writes position_thesis_outcomes only;
alerts nothing, modulates nothing.

Idempotent: a terminal verdict (hit/miss) is never re-scored; in_progress
(expiry not yet passed) and unknown (price source failed) are re-scored each
run. Born under the F-A4-1 typed-outcome contract: a position that cannot be
scored raises counts.errors → the runner records the job PARTIAL, never
green-on-vacuum.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone, date

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.analytics.thesis_scoring import score_thesis, classify_structure

JOB_NAME = "thesis_tracker"

_TRACKED_ROUTING = ("live_eligible", "shadow_only")


def _parse_date(v) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


def _underlying_at_expiry(truth, symbol: str, expiry: date):
    """(close, price_basis, bar_date) for the underlying at the ORIGINAL expiry.

    F-A9-THESIS-BASIS (2026-07-12): a TERMINAL thesis verdict must never hide that
    it was graded off a stale bar. price_basis discloses the source:
      'expiry_close'       — the exact expiry-date bar (authoritative),
      'fallback_prior_bar' — the last bar within 7d ON/BEFORE expiry (holiday/gap),
      None                 — no bar found (caller scores unknown; H9 non-fabricated).
    Returns (None, None, None) on empty/failure."""
    try:
        start = datetime(expiry.year, expiry.month, expiry.day, tzinfo=timezone.utc) - timedelta(days=7)
        end = datetime(expiry.year, expiry.month, expiry.day, tzinfo=timezone.utc) + timedelta(days=1)
        bars = truth.daily_bars(symbol, start, end)
        if not bars:
            return None, None, None
        exp_str = expiry.isoformat()
        exact = [b for b in bars if b.get("date") == exp_str and b.get("close") is not None]
        if exact:
            return float(exact[-1]["close"]), "expiry_close", exp_str
        # holiday / no bar on the exact date → last bar on or before expiry
        on_or_before = [b for b in bars if b.get("date") and b["date"] <= exp_str and b.get("close") is not None]
        if on_or_before:
            last = on_or_before[-1]
            return float(last["close"]), "fallback_prior_bar", last.get("date")
        return None, None, None
    except Exception:
        return None, None, None


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    print(f"[{JOB_NAME}] Starting thesis scoring.", flush=True)
    client = get_admin_client()
    today = datetime.now(timezone.utc).date()

    # 1. Tracked cohort closed positions (join for routing_mode).
    pos_rows = client.table("paper_positions") \
        .select("id, user_id, symbol, nearest_expiry, created_at, closed_at, "
                "close_reason, realized_pl, legs, portfolio_id") \
        .eq("status", "closed") \
        .execute().data or []

    # routing_mode per portfolio (tracked cohorts only)
    port_rows = client.table("paper_portfolios") \
        .select("id, routing_mode") \
        .in_("routing_mode", list(_TRACKED_ROUTING)) \
        .execute().data or []
    routing_by_port = {p["id"]: p["routing_mode"] for p in port_rows}
    tracked = [p for p in pos_rows if p.get("portfolio_id") in routing_by_port]

    # 2. Terminal verdicts already recorded — never re-score (idempotent).
    scored_rows = client.table("position_thesis_outcomes") \
        .select("position_id, thesis_outcome") \
        .in_("thesis_outcome", ["hit", "miss"]) \
        .execute().data or []
    terminal = {r["position_id"] for r in scored_rows}

    # 3. Closing-order execution_mode (live vs paper/internal) for the split.
    pos_ids = [p["id"] for p in tracked]
    exec_by_pos: Dict[str, str] = {}
    if pos_ids:
        ord_rows = client.table("paper_orders") \
            .select("position_id, execution_mode, filled_at") \
            .in_("position_id", pos_ids) \
            .eq("status", "filled") \
            .execute().data or []
        for o in ord_rows:
            pid = o.get("position_id")
            if pid and (pid not in exec_by_pos or (o.get("filled_at") or "") > exec_by_pos.get(pid + "_at", "")):
                exec_by_pos[pid] = o.get("execution_mode")
                exec_by_pos[pid + "_at"] = o.get("filled_at") or ""

    from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
    try:
        truth = MarketDataTruthLayer()
    except Exception as e:
        print(f"[{JOB_NAME}] truth layer unavailable: {e}", flush=True)
        truth = None

    counts = {"tracked": len(tracked), "hit": 0, "miss": 0,
              "in_progress": 0, "unknown": 0, "errors": 0, "upserts": 0}

    for pos in tracked:
        pid = pos["id"]
        if pid in terminal:
            continue
        expiry = _parse_date(pos.get("nearest_expiry"))
        legs = pos.get("legs") or []

        if expiry is None:
            outcome, U, basis, price_basis = "unknown", None, "no original expiry on position", "no_expiry"
        elif expiry >= today:
            outcome, U, basis, price_basis = "in_progress", None, f"expiry {expiry.isoformat()} not yet passed", "in_progress"
        else:
            if truth:
                U, price_basis, price_date = _underlying_at_expiry(truth, pos.get("symbol"), expiry)
            else:
                U, price_basis, price_date = None, None, None
            outcome, basis = score_thesis(legs, U)
            # F-A9: surface the price source in the human basis (the disclosure).
            if U is None:
                price_basis = "unknown"
            elif price_basis == "fallback_prior_bar":
                basis = f"{basis} [price: fallback_prior_bar@{price_date}]"
            else:
                basis = f"{basis} [price: expiry_close]"

        row = {
            "position_id": pid,
            "user_id": pos.get("user_id"),
            "symbol": pos.get("symbol"),
            "routing_mode": routing_by_port.get(pos.get("portfolio_id")),
            "execution_mode": exec_by_pos.get(pid),
            "structure": classify_structure(legs),
            "original_expiry": expiry.isoformat() if expiry else None,
            "entry_date": (_parse_date(pos.get("created_at")).isoformat()
                           if _parse_date(pos.get("created_at")) else None),
            "close_reason": pos.get("close_reason"),
            "realized_pl": pos.get("realized_pl"),
            "underlying_at_expiry": U,
            "price_basis": price_basis,  # F-A9: which price source graded this row
            "thesis_outcome": outcome,
            "thesis_basis": basis,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            client.table("position_thesis_outcomes").upsert(
                row, on_conflict="position_id"
            ).execute()
            counts["upserts"] += 1
        except Exception as e:
            print(f"[{JOB_NAME}] upsert failed pos={str(pid)[:8]}: {e}", flush=True)
            counts["errors"] += 1
            continue

        if outcome in ("hit", "miss"):
            counts[outcome] += 1
        elif outcome == "in_progress":
            counts["in_progress"] += 1
        else:  # unknown — a position that COULD score (expiry passed) but the
            # price/structure couldn't resolve. Unscorable → PARTIAL, re-tried.
            counts["unknown"] += 1
            counts["errors"] += 1

    scored = counts["hit"] + counts["miss"]
    print(f"[{JOB_NAME}] Done. tracked={counts['tracked']} scored={scored} "
          f"(hit={counts['hit']} miss={counts['miss']}) in_progress={counts['in_progress']} "
          f"unknown={counts['unknown']} errors={counts['errors']}", flush=True)

    # F-A4-1 typed contract: counts.errors > 0 → runner records PARTIAL.
    return {
        "status": "ok",
        "counts": {"errors": counts["errors"]},
        "thesis": counts,
        "scored": scored,
    }
