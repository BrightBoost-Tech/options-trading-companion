"""Shadow-to-expiry THESIS TRACKER (I5, 2026-07-11) — OBSERVE-ONLY daily job.

Every tracked closed position (live_eligible + shadow_only cohorts) has its
ENTRY THESIS followed to its ORIGINAL expiry and scored hit/miss against the
underlying's price there — independent of fills / P&L. This converts every
force-close into a completed counterfactual and turns the provisional ~78%
spot-score into a standing number. Writes position_thesis_outcomes only;
alerts nothing, modulates nothing.

Idempotent: a terminal verdict (hit/miss) is never re-scored; in_progress
(expiry date not yet reached) and unknown (price source failed) are re-scored
each run. The scheduled post-close run treats same-day expiry as terminal-eligible
so Friday expiries do not wait through the weekend. Born under the F-A4-1 typed-outcome contract: a position that cannot be
scored raises counts.errors → the runner records the job PARTIAL, never
green-on-vacuum.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone, date, time
from zoneinfo import ZoneInfo

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.analytics.thesis_scoring import score_thesis, classify_structure

JOB_NAME = "thesis_tracker"

_TRACKED_ROUTING = ("live_eligible", "shadow_only")

# F-A3-4 D2/D3: the population headline splits on EXECUTION_MODE — the closing
# order's actual routing — NEVER routing_mode (which is only cohort eligibility).
#   alpaca_live    = broker-filled live
#   alpaca_paper   = paper-account era
#   internal_paper = internal / shadow fill
# A missing / unrecognized execution_mode is isolated under a distinct
# unknown bucket, never folded into a live one.
_EXECUTION_MODES = ("alpaca_live", "alpaca_paper", "internal_paper")
_UNKNOWN_EXECUTION = "unknown_execution_mode"
_UNKNOWN_ROUTING = "unknown_routing"
_OUTCOME_KEYS = ("hit", "miss", "in_progress", "unknown")


def _norm_execution_mode(v) -> str:
    """A stored execution_mode → its population bucket. Missing / unrecognized →
    unknown_execution_mode, NEVER a live bucket: routing eligibility is not
    broker execution (F-A3-4 D2)."""
    return v if v in _EXECUTION_MODES else _UNKNOWN_EXECUTION


def _norm_routing_mode(v) -> str:
    return v if v in _TRACKED_ROUTING else _UNKNOWN_ROUTING


def _blank_tally() -> Dict[str, int]:
    return {k: 0 for k in _OUTCOME_KEYS}


def _finalize_tally(t: Dict[str, int]) -> Dict[str, Any]:
    """hit/miss/in_progress/unknown + derived scored (=hit+miss); hit_rate is
    present ONLY when scored > 0 (never a divide-by-zero or a fabricated 0.0)."""
    scored = t["hit"] + t["miss"]
    out = {"hit": t["hit"], "miss": t["miss"], "scored": scored,
           "in_progress": t["in_progress"], "unknown": t["unknown"]}
    if scored > 0:
        out["hit_rate"] = round(t["hit"] / scored, 4)
    return out


def _summarize_population(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full stored-population headline from position_thesis_outcomes rows (each
    carrying thesis_outcome + execution_mode + routing_mode).

    The live/paper/internal split keys on EXECUTION_MODE, never routing_mode: a
    routing_mode='live_eligible' row whose closing order filled internally or in
    the paper account is NOT broker-live — it is counted under its execution
    bucket. Pooled totals live ONLY under `pooled_all_modes`, never labeled
    'live'. Cross-tabs expose routing×execution so eligibility and execution are
    read apart (F-A3-4 D3)."""
    by_exec: Dict[str, Dict[str, int]] = {m: _blank_tally() for m in _EXECUTION_MODES}
    by_exec[_UNKNOWN_EXECUTION] = _blank_tally()
    by_cross: Dict[str, Dict[str, int]] = {}
    pooled = _blank_tally()

    for r in rows:
        outcome = r.get("thesis_outcome")
        if outcome not in _OUTCOME_KEYS:
            outcome = "unknown"  # any stray verdict counts as unscored, never scored
        em = _norm_execution_mode(r.get("execution_mode"))
        rm = _norm_routing_mode(r.get("routing_mode"))
        by_exec[em][outcome] += 1
        pooled[outcome] += 1
        by_cross.setdefault(f"{rm}/{em}", _blank_tally())[outcome] += 1

    return {
        "population_by_execution_mode": {
            m: _finalize_tally(t) for m, t in by_exec.items()
        },
        "population_by_routing_x_execution": {
            k: _finalize_tally(t) for k, t in sorted(by_cross.items())
        },
        "pooled_all_modes": _finalize_tally(pooled),
        "total_rows": len(rows),
    }


_MARKET_TZ = ZoneInfo("America/New_York")
_EXPIRY_TERMINAL_AFTER = time(16, 15)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_is_terminal_eligible(expiry: date, as_of: datetime) -> bool:
    """Past expiries are ready; same-day expiry is ready only post-close.

    The 16:15 ET guard prevents a manual pre-close run from grading an
    incomplete same-day daily bar. It is deliberately later than regular
    options close and still resolves early-close sessions that same day.
    """
    market_now = as_of.astimezone(_MARKET_TZ)
    if expiry < market_now.date():
        return True
    return (
        expiry == market_now.date()
        and market_now.time().replace(tzinfo=None) >= _EXPIRY_TERMINAL_AFTER
    )


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
    as_of = _utc_now()
    today = as_of.astimezone(_MARKET_TZ).date()

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
        elif not _expiry_is_terminal_eligible(expiry, as_of):
            outcome, U, basis, price_basis = "in_progress", None, f"expiry {expiry.isoformat()} not yet reached", "in_progress"
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

    # ── Full stored-population headline (F-A3-4 D3) ──────────────────────────
    # DISTINCT from the current-run mutation counts above: query the COMPLETE
    # position_thesis_outcomes table and split by EXECUTION_MODE (broker-live vs
    # paper vs internal), never routing eligibility. A summary-fetch failure
    # increments counts.errors → the runner records PARTIAL, but the upserts
    # above are PRESERVED (they already committed row-by-row).
    population: Optional[Dict[str, Any]] = None
    try:
        pop_rows = client.table("position_thesis_outcomes") \
            .select("thesis_outcome, execution_mode, routing_mode") \
            .execute().data or []
        population = _summarize_population(pop_rows)
    except Exception as e:
        print(f"[{JOB_NAME}] population summary fetch failed: {e}", flush=True)
        counts["errors"] += 1

    # F-A4-1 typed contract: counts.errors > 0 → runner records PARTIAL.
    return {
        "status": "ok",
        "counts": {"errors": counts["errors"]},
        # (1) current-run mutation counts — only rows upserted THIS run.
        "current_run": counts,
        "thesis": counts,  # back-compat alias (pre-F-A3-4 key)
        # (2) full stored-population headline — None iff the summary fetch failed
        # (counts.errors already incremented → job PARTIAL).
        "population": population,
        "scored": scored,
    }
