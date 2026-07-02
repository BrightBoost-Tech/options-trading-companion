"""
Paper Learning Ingest Job Handler

Ingests paper trading outcomes into learning_feedback_loops for validation/streak.

This handler:
1. Reads closed paper_positions within lookback window
2. Fetches closing paper_orders for order metadata and dedup key
3. Fetches linked trade_suggestions for EV (pnl_predicted)
4. Builds trade_closed outcome records with is_paper: true
5. Inserts into learning_feedback_loops with idempotency via (user_id, order_id)

pnl_predicted semantics (normalized to match live ingest):
  - Stores the matched suggestion's EV (expected value) when available,
    mirroring what live ingest records as pnl_predicted.
  - Execution drag (expected slippage from TCM) is stored separately
    in details_json.expected_slippage.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "paper_learning_ingest"

# A4 typed columns added by migration 20260623010000. Listed here so the insert
# can degrade gracefully if the migration has not been applied yet.
_A4_OPTIONAL_COLUMNS = ("entry_iv_rv_spread", "entry_ts", "realized_vol_over_hold")

# A4: minimum number of daily closes over a trade's hold required to compute an
# annualized realized vol. A 1-2 day hold yields <2 returns — meaningless when
# annualized — so we emit NULL rather than garbage. Env-overridable.
A4_MIN_HOLD_BARS = int(os.getenv("A4_MIN_HOLD_BARS", "3"))


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string (or pass through a datetime). None-safe."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _compute_realized_vol_over_hold(
    truth_layer: Any,
    symbol: Optional[str],
    opened_at: Any,
    closed_at: Any,
) -> Optional[float]:
    """A4 "b" half: annualized realized vol (log returns, ×√252, ddof=0) over a
    trade's actual hold window [opened_at, closed_at].

    FAILURE-ISOLATED: returns None on ANY problem (no truth layer, missing
    timestamps, degenerate/inverted hold, fetch error, too-few bars). The caller
    writes None and the outcome record STILL persists with P&L/EV/entry_iv_rv
    intact — rv computation can NEVER break the outcome-write path.
    """
    try:
        if truth_layer is None:
            return None
        if not symbol or symbol == "UNKNOWN":
            return None
        entry_dt = _parse_ts(opened_at)
        exit_dt = _parse_ts(closed_at)
        if entry_dt is None or exit_dt is None or exit_dt <= entry_dt:
            return None
        bars = truth_layer.daily_bars(symbol, entry_dt, exit_dt)
        closes = [
            float(b["close"]) for b in (bars or [])
            if b.get("close") is not None
        ]
        if len(closes) < A4_MIN_HOLD_BARS:
            return None  # too short to annualize meaningfully
        from packages.quantum.analytics.vol_math import realized_vol_log_annualized
        return realized_vol_log_annualized(closes, window=len(closes) - 1)
    except Exception as e:
        logger.info(
            "A4: realized-vol-over-hold compute failed for %s (non-fatal): %s",
            symbol, e,
        )
        return None


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Ingest paper trading outcomes for learning/validation.

    Payload:
        - date: str - Date for idempotency (YYYY-MM-DD)
        - user_id: str|None - Specific user, or all users if None
        - lookback_days: int - How far back to look (default: 7)
    """
    start_time = time.time()
    notes = []
    counts = {
        "users_processed": 0,
        "closed_positions_found": 0,
        "outcomes_created": 0,
        "outcomes_skipped_duplicate": 0,
        "errors": 0,
    }

    target_user_id = payload.get("user_id")
    lookback_days = payload.get("lookback_days", 7)
    target_date = payload.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    logger.info(f"[paper_learning_ingest] Processing user {str(target_user_id or 'all')[:8]}..., lookback={lookback_days}d, target_date={target_date}")

    try:
        client = get_admin_client()

        # Get target users
        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            users_processed = 0
            total_entries = 0
            total_outcomes = 0
            total_skipped = 0
            total_errors = 0

            for uid in active_users:
                try:
                    result = await _ingest_paper_outcomes_for_user(
                        uid, client, lookback_days, target_date
                    )
                    users_processed += 1
                    total_entries += result.get("closed_positions", 0)
                    total_outcomes += result.get("outcomes_created", 0)
                    total_skipped += result.get("skipped_duplicate", 0)

                    if result.get("outcomes_created", 0) > 0:
                        notes.append(
                            f"Created {result['outcomes_created']} paper outcomes for {uid[:8]}..."
                        )

                except Exception as e:
                    total_errors += 1
                    notes.append(f"Failed for {uid[:8]}...: {str(e)}")

            return users_processed, total_entries, total_outcomes, total_skipped, total_errors

        (
            users_processed,
            entries,
            outcomes,
            skipped,
            errors,
        ) = run_async(process_users())

        counts["users_processed"] = users_processed
        counts["closed_positions_found"] = entries
        counts["outcomes_created"] = outcomes
        counts["outcomes_skipped_duplicate"] = skipped
        counts["errors"] = errors

        # Gap-1 (07-02): consecutive-loss streak breaker — tail step so the
        # streak reads TONIGHT's freshly-ingested closes. evaluate_and_trip
        # never raises and is FAIL-CLOSED internally (an evaluation error
        # pauses entries rather than skipping the check); this wrapper only
        # guards the import/plumbing seam so a packaging fault can't fail
        # the ingest job itself.
        try:
            from packages.quantum.risk.streak_breaker import evaluate_and_trip
            streak_breaker = evaluate_and_trip(client)
        except Exception as sb_exc:
            logger.error(f"[STREAK_BREAKER] wrapper failure: {sb_exc}")
            streak_breaker = {"error": str(sb_exc)[:200]}

        timing_ms = (time.time() - start_time) * 1000

        logger.info(f"[paper_learning_ingest] Completed: {counts}")

        return {
            "ok": True,
            "counts": counts,
            "timing_ms": timing_ms,
            "lookback_days": lookback_days,
            "target_date": target_date,
            "streak_breaker": streak_breaker,
            "notes": notes[:20],
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Paper learning ingest job failed: {e}")


async def _ingest_paper_outcomes_for_user(
    user_id: str,
    supabase,
    lookback_days: int,
    target_date: str,
) -> Dict[str, Any]:
    """
    Ingest paper trading outcomes for a single user.

    Starts from paper_positions (the source of truth for closed trades),
    fetches closing orders for metadata, and creates learning_feedback_loops
    records with the position's authoritative realized_pl.

    Returns:
        Dict with counts: {closed_positions: int, outcomes_created: int, skipped_duplicate: int}
    """
    # Compute lookback cutoff
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_iso = cutoff_date.isoformat()

    logger.debug("Starting paper ingest for user %s, lookback_days=%d, cutoff=%s",
                 user_id[:12], lookback_days, cutoff_iso)

    # 1. Start from paper_positions — the source of truth for closed trades.
    #    Previous code started from paper_ledger, but paper_ledger lacks a
    #    user_id column, so that query always failed silently.
    pos_result = supabase.table("paper_positions") \
        .select("id, realized_pl, status, created_at, closed_at, suggestion_id, trace_id, symbol") \
        .eq("user_id", user_id) \
        .eq("status", "closed") \
        .gte("closed_at", cutoff_iso) \
        .execute()

    closed_positions = pos_result.data or []
    logger.debug("Found %d closed positions within lookback", len(closed_positions))

    if not closed_positions:
        return {"closed_positions": 0, "outcomes_created": 0, "skipped_duplicate": 0}

    if logger.isEnabledFor(logging.DEBUG):
        for p in closed_positions:
            logger.debug("  pos=%s symbol=%s suggestion_id=%s closed_at=%s realized_pl=%s",
                         p["id"][:8], p.get("symbol"),
                         str(p.get("suggestion_id", "NULL"))[:8],
                         p.get("closed_at"), p.get("realized_pl"))

    position_ids = [p["id"] for p in closed_positions]

    # 2. Fetch closing orders linked to these positions (for metadata and dedup key).
    orders_result = supabase.table("paper_orders") \
        .select("*") \
        .in_("position_id", position_ids) \
        .eq("status", "filled") \
        .execute()

    all_orders = orders_result.data or []
    logger.debug("Found %d filled orders for %d positions", len(all_orders), len(position_ids))

    # Build map: position_id → closing order (use latest if multiple)
    orders_by_position: Dict[str, Dict] = {}
    for o in all_orders:
        pid = o.get("position_id")
        if pid:
            existing = orders_by_position.get(pid)
            if not existing or (o.get("filled_at") or "") > (existing.get("filled_at") or ""):
                orders_by_position[pid] = o

    logger.debug("Mapped %d positions to closing orders", len(orders_by_position))

    # 2b. Fetch suggestion EVs for pnl_predicted (mirrors live ingest semantics).
    #     Collect suggestion_ids from orders (preferred) and positions (fallback).
    suggestion_ids = set()
    for o in orders_by_position.values():
        sid = o.get("suggestion_id")
        if sid:
            suggestion_ids.add(sid)
    for p in closed_positions:
        sid = p.get("suggestion_id")
        if sid:
            suggestion_ids.add(sid)

    suggestion_meta_map: Dict[str, Dict] = {}
    if suggestion_ids:
        # A4: also pull iv_rv_spread (the entry-time VRP proxy) over the EXISTING
        # suggestion_id join — no new query. The column is added by the pending
        # VRP migration (20260623000000); until that is applied selecting it
        # errors, so we try the extended SELECT and fall back to the legacy
        # column set. A missing iv_rv_spread must NEVER break outcome ingest.
        _base_cols = "id, ev, probability_of_profit, regime, strategy, risk_adjusted_ev, sizing_metadata"
        try:
            sugg_result = supabase.table("trade_suggestions") \
                .select(_base_cols + ", iv_rv_spread") \
                .in_("id", list(suggestion_ids)) \
                .execute()
        except Exception as e:
            logger.info(
                "A4: iv_rv_spread column unavailable on trade_suggestions "
                "(VRP migration not yet applied?) — falling back: %s", e
            )
            sugg_result = supabase.table("trade_suggestions") \
                .select(_base_cols) \
                .in_("id", list(suggestion_ids)) \
                .execute()
        for s in (sugg_result.data or []):
            suggestion_meta_map[s["id"]] = s
        logger.debug("Fetched metadata for %d/%d suggestions", len(suggestion_meta_map), len(suggestion_ids))
    # Backwards-compat alias used below
    suggestion_ev_map: Dict[str, float] = {
        sid: float(meta["ev"]) for sid, meta in suggestion_meta_map.items() if meta.get("ev") is not None
    }

    # 3. Dedup against existing learning records — POSITION-LEVEL (v5-A3).
    # The old key was the closing-order id alone: a position carrying more
    # than one filled close row across runs produced one outcome PER ORDER,
    # each with the FULL position pnl (ADBE f6eee0e9 ×2 / AMD 91d4e119 ×2 —
    # 76.5% of training dollars were dup-counted). A closed position must
    # yield exactly ONE trade_closed outcome. Keys, in order:
    #   (a) suggestion_id — 1:1 with the position (cohort forks carry their
    #       own suggestion ids, so fork outcomes stay distinct by design);
    #   (b) source_event_id (order id) — retained for legacy rows / positions
    #       without a suggestion link.
    order_ids = [o["id"] for o in orders_by_position.values()]
    existing_order_ids: set = set()
    if order_ids:
        existing_result = supabase.table("learning_feedback_loops") \
            .select("source_event_id") \
            .eq("user_id", user_id) \
            .in_("source_event_id", order_ids) \
            .execute()
        existing_order_ids = {r["source_event_id"] for r in (existing_result.data or [])}
        logger.debug("Dedup: %d of %d orders already have LFL records",
                     len(existing_order_ids), len(order_ids))
    else:
        logger.debug("No order_ids to dedup — all positions lack closing orders")

    existing_suggestion_ids: set = set()
    if suggestion_ids:
        try:
            sugg_existing = supabase.table("learning_feedback_loops") \
                .select("suggestion_id") \
                .eq("user_id", user_id) \
                .eq("outcome_type", "trade_closed") \
                .in_("suggestion_id", list(suggestion_ids)) \
                .execute()
            existing_suggestion_ids = {
                r["suggestion_id"] for r in (sugg_existing.data or [])
                if r.get("suggestion_id")
            }
        except Exception as e:
            # Fail toward the legacy (order-id) dedup only — never block ingest.
            logger.warning("Suggestion-level dedup query failed (order-id dedup only): %s", e)

    # Live-vs-simulator dimension (v5-A3, fixed Phase 1): is_paper is derived
    # per-row from the ORDER's execution_mode via _resolve_is_paper (the order
    # is the routing ground truth). The earlier portfolio-membership conjunct
    # was silently dead — the closed-positions query above never selects
    # portfolio_id — so every outcome, live broker fills included, landed
    # is_paper=True. See _resolve_is_paper for the full rationale.

    # 4. Create outcomes for each closed position that has a closing order.
    outcomes_created = 0
    skipped_duplicate = 0
    skipped_no_order = 0

    # A4: market-data client for realized-vol-over-hold (lazy, failure-isolated).
    # If construction fails, truth_layer stays None and the rv helper returns
    # None — outcome ingest is never blocked on market data.
    try:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        truth_layer = MarketDataTruthLayer()
    except Exception as e:
        logger.info("A4: truth layer unavailable — realized_vol_over_hold will be NULL: %s", e)
        truth_layer = None

    for position in closed_positions:
        pos_id_short = position["id"][:8]
        symbol = position.get("symbol", "?")

        order = orders_by_position.get(position["id"])
        if not order:
            skipped_no_order += 1
            logger.debug("SKIP %s (pos=%s): no closing order", symbol, pos_id_short)
            continue

        if order["id"] in existing_order_ids:
            skipped_duplicate += 1
            logger.debug("SKIP %s (pos=%s): dedup — order %s already in LFL",
                         symbol, pos_id_short, order["id"][:8])
            continue

        # Resolve suggestion metadata: prefer order's suggestion_id, fallback to position's
        suggestion_id = order.get("suggestion_id") or position.get("suggestion_id")
        suggestion_ev = suggestion_ev_map.get(suggestion_id) if suggestion_id else None
        suggestion_meta = suggestion_meta_map.get(suggestion_id) if suggestion_id else None

        # Position-level dedup (v5-A3): this position's outcome already exists
        # under ANY close order — skip, even if today's picked order id differs
        # from the one recorded (the cross-run dup mechanism).
        if suggestion_id and suggestion_id in existing_suggestion_ids:
            skipped_duplicate += 1
            logger.info("SKIP %s (pos=%s): dedup — suggestion %s already has a "
                        "trade_closed outcome", symbol, pos_id_short, str(suggestion_id)[:8])
            continue

        # A4: entry-IV (from the suggestion join) + realized-vol-over-hold
        # (computed once, here, at close — never recomputed on read). Both are
        # failure-isolated: a NULL on either never blocks the outcome write.
        entry_iv_rv_spread = (suggestion_meta or {}).get("iv_rv_spread")
        entry_ts = position.get("created_at")  # paper_positions open timestamp == created_at
        realized_vol_over_hold = _compute_realized_vol_over_hold(
            truth_layer, position.get("symbol"), entry_ts, position.get("closed_at")
        )

        outcome = _create_paper_outcome_record(
            user_id, order, target_date, position,
            suggestion_ev=suggestion_ev,
            suggestion_meta=suggestion_meta,
            is_paper=_resolve_is_paper(order),
            entry_iv_rv_spread=entry_iv_rv_spread,
            entry_ts=entry_ts,
            realized_vol_over_hold=realized_vol_over_hold,
        )
        logger.info("INSERT %s (pos=%s): pnl_realized=%s pnl_predicted=%s suggestion=%s",
                     symbol, pos_id_short, outcome["pnl_realized"],
                     outcome.get("pnl_predicted"), str(suggestion_id or "NULL")[:8])

        try:
            _insert_outcome_defensive(supabase, outcome)
            outcomes_created += 1

            # N4 honesty fix: flip the learning_ingested marker on the source
            # position. The column read False "always" because nothing ever set
            # it (audit 2026-06-12 N4 — a Known-Liar dead column); dedup is
            # driven by learning_feedback_loops existence, NOT this flag, so
            # this only restores the marker's meaning. Fail-soft: a marker
            # write must never break ingest.
            try:
                supabase.table("paper_positions").update(
                    {"learning_ingested": True}
                ).eq("id", position["id"]).execute()
            except Exception as _flag_err:
                logger.warning(
                    "learning_ingested marker update failed for pos=%s: %s",
                    pos_id_short, _flag_err,
                )

            # Backfill realized_outcome on policy_decisions if suggestion linked
            if suggestion_id:
                _backfill_policy_decision_outcome(
                    supabase, suggestion_id, position, order,
                )
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                skipped_duplicate += 1
                logger.debug("SKIP %s (pos=%s): DB duplicate constraint", symbol, pos_id_short)
            else:
                logger.error("Failed to insert outcome for %s (pos=%s): %s",
                             symbol, pos_id_short, e)
                raise

    logger.info("Paper ingest done for user %s: %d created, %d deduped, %d no order",
                user_id[:8], outcomes_created, skipped_duplicate, skipped_no_order)

    return {
        "closed_positions": len(closed_positions),
        "outcomes_created": outcomes_created,
        "skipped_duplicate": skipped_duplicate,
    }


def _resolve_is_paper(order: Dict[str, Any]) -> bool:
    """Derive is_paper from the ORDER's execution_mode — the routing ground
    truth: an order reaches the broker iff execution_mode == "alpaca_live"
    (internal_paper / shadow_blocked / None / missing are simulated).

    Deliberately independent of portfolio_id. The prior derivation AND-ed this
    execution_mode test with a ``position.portfolio_id in
    live_routed_portfolio_ids`` membership check, but the closed-positions
    query never SELECTed portfolio_id (see line ~155), so that conjunct was
    always False and EVERY outcome — live broker fills included — landed
    is_paper=True (the v5-A3 contamination: SPY/NFLX/MARA 06-12, QQQ 06-15).
    Keying on the order alone makes the label immune to which columns the
    upstream query happens to select, so the missing-column class cannot
    silently relabel live fills as paper again.
    """
    return (order.get("execution_mode") or "") != "alpaca_live"


def _insert_outcome_defensive(supabase, outcome: Dict) -> None:
    """Insert the outcome row, surviving the pre-migration schema state.

    If the A4 columns (entry_iv_rv_spread / entry_ts / realized_vol_over_hold)
    are not yet present in the DB (migration 20260623010000 not applied), the
    first insert errors on the unknown column; we strip those keys and retry
    ONCE so the core outcome (P&L/EV) still records. Extends A4's
    failure-isolation to schema timing and mirrors the missing-column-retry
    pattern in workflow_orchestrator. Any other error (incl. duplicate) is
    re-raised unchanged for the caller's existing handling.
    """
    try:
        supabase.table("learning_feedback_loops").insert(outcome).execute()
        return
    except Exception as e:
        has_a4 = any(k in outcome for k in _A4_OPTIONAL_COLUMNS)
        names_col = any(c in str(e) for c in _A4_OPTIONAL_COLUMNS)
        if not (has_a4 and names_col):
            raise  # not a missing-A4-column error → caller handles (e.g. duplicate)
        stripped = {k: v for k, v in outcome.items() if k not in _A4_OPTIONAL_COLUMNS}
        logger.warning(
            "A4 columns absent on learning_feedback_loops (migration 20260623010000 "
            "not applied?) — retrying outcome insert without them"
        )
        supabase.table("learning_feedback_loops").insert(stripped).execute()


def _create_paper_outcome_record(
    user_id: str,
    order: Dict,
    target_date: str,
    position: Dict,
    *,
    suggestion_ev: Optional[float] = None,
    suggestion_meta: Optional[Dict] = None,
    is_paper: bool = True,
    entry_iv_rv_spread: Optional[float] = None,
    entry_ts: Optional[str] = None,
    realized_vol_over_hold: Optional[float] = None,
) -> Dict:
    """
    Create a learning_feedback_loops record from a paper order fill.

    IMPORTANT: This creates outcome_type='trade_closed' which is required for
    the learning_trade_outcomes_v3 view to include the record. The view filters
    to only outcome_type in ('trade_closed', 'individual_trade').

    pnl_predicted: sourced from suggestion EV (matching live ingest semantics).
    Execution drag / TCM slippage is stored in details_json.expected_slippage.

    Args:
        user_id: User ID
        order: Paper order dict with fill details
        target_date: Date bucket for idempotency
        position: Linked paper_positions row with authoritative realized_pl
        suggestion_ev: EV from the matched trade_suggestion (if available)

    Returns:
        Dict ready for insertion into learning_feedback_loops
    """
    filled_qty = float(order.get("filled_qty") or 0)
    avg_fill_price = float(order.get("avg_fill_price") or 0)
    requested_price = float(order.get("requested_price") or 0)
    side = order.get("side", "buy")

    # Use realized_pl from the linked paper_positions row.
    # This is the authoritative trade P&L computed by the exit evaluator:
    #   (exit_price - entry_price) * abs(qty) * 100  for long positions
    #   (entry_price - exit_price) * abs(qty) * 100  for short positions
    pnl_realized = float(position.get("realized_pl") or 0.0)

    # Determine win/loss for details_json (outcome_type must be 'trade_closed' for view)
    if pnl_realized > 0:
        pnl_outcome = "win"
    elif pnl_realized < 0:
        pnl_outcome = "loss"
    else:
        pnl_outcome = "breakeven"

    # Extract trace_id and suggestion_id from order
    # suggestion_id is REQUIRED for the learning_trade_outcomes_v3 view join
    trace_id = order.get("trace_id")
    suggestion_id = order.get("suggestion_id")

    # Get symbol from order_json or direct field
    order_json = order.get("order_json") or {}
    symbol = order_json.get("symbol") or order.get("symbol") or "UNKNOWN"

    # Get TCM metrics if present
    tcm = order.get("tcm") or {}
    predicted_fill_price = tcm.get("expected_fill_price")
    fill_probability = tcm.get("fill_probability")
    expected_slippage = tcm.get("expected_slippage")

    return {
        "user_id": user_id,
        "suggestion_id": suggestion_id,  # Required for view join to trade_suggestions
        "trace_id": trace_id,
        "source_event_id": order["id"],
        # CRITICAL: Must be 'trade_closed' for learning_trade_outcomes_v3 view
        "outcome_type": "trade_closed",
        "pnl_realized": pnl_realized,
        # pnl_predicted: suggestion EV, matching live ingest semantics.
        # Previously this stored tcm.expected_slippage (execution drag, not prediction).
        "pnl_predicted": suggestion_ev,
        # v5-A3: live broker fills are no longer mislabeled as paper — the
        # caller resolves routing (live-routed portfolio + alpaca_live
        # execution_mode → False). Default True is the conservative legacy.
        "is_paper": is_paper,
        # Typed segment columns — post_trade_learning builds its
        # (strategy, regime, dte) segment keys from THESE, not details_json;
        # omitting them silently no-oped segment learning (0 typed rows
        # through 07-01). NULL when no suggestion is linked — never fabricated.
        "strategy": (suggestion_meta or {}).get("strategy"),
        "regime": (suggestion_meta or {}).get("regime"),
        "details_json": {
            "order_id": order["id"],
            "position_id": position.get("id"),
            "portfolio_id": order.get("portfolio_id"),
            "symbol": symbol,
            "side": side,
            "order_type": order.get("order_type"),
            "filled_qty": filled_qty,
            "avg_fill_price": avg_fill_price,
            "requested_price": requested_price,
            "requested_qty": order.get("requested_qty"),
            "status": order.get("status"),
            "filled_at": order.get("filled_at"),
            "tcm_fill_probability": fill_probability,
            "tcm_expected_fill_price": predicted_fill_price,
            # Execution drag from TCM — semantically separate from pnl_predicted.
            "expected_slippage": expected_slippage,
            "date_bucket": target_date,
            "pnl_outcome": pnl_outcome,  # win/loss/breakeven for analytics
            "is_paper": is_paper,
            "routing": "live" if not is_paper else "shadow_or_internal",
            "reason_codes": ["paper_trade_close"],
            # Calibration fields — prediction-time snapshot for calibration_service
            "predicted_ev": suggestion_ev,
            "predicted_pop": (suggestion_meta or {}).get("probability_of_profit"),
            "predicted_risk_adjusted_ev": (suggestion_meta or {}).get("risk_adjusted_ev"),
            "regime_at_entry": (suggestion_meta or {}).get("regime"),
            "strategy_at_entry": (suggestion_meta or {}).get("strategy"),
        },
        # A4 typed columns (added by migration _add_a4_outcome_vol_fields). All
        # nullable: any of these may be None (entry IV not yet persisted, or rv
        # un-computable) without affecting the rest of the record. The grading
        # join is entry_iv_rv_spread (IV at entry) vs realized_vol_over_hold (vol
        # that actually occurred), self-contained on the row via entry_ts.
        "entry_iv_rv_spread": entry_iv_rv_spread,
        "entry_ts": entry_ts,
        "realized_vol_over_hold": realized_vol_over_hold,
        # Use position's closed_at so the view's COALESCE(updated_at, created_at)
        # reflects the actual close time, not the ingestion time.
        "updated_at": position.get("closed_at"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _backfill_policy_decision_outcome(
    supabase,
    suggestion_id: str,
    position: Dict,
    order: Dict,
) -> None:
    """
    Backfill realized_outcome on policy_decisions rows linked to this suggestion.

    Called after a closed position is ingested into learning_feedback_loops.
    Updates ALL cohort decision rows for this suggestion (there's one per cohort).
    """
    from packages.quantum.policy_lab.config import is_policy_lab_enabled

    if not is_policy_lab_enabled():
        return

    realized_pl = float(position.get("realized_pl") or 0)
    opened_at = position.get("created_at")
    closed_at = position.get("closed_at")
    close_reason = position.get("close_reason", "")

    # Compute hold_time in hours
    hold_time_hours = None
    if opened_at and closed_at:
        try:
            t_open = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
            t_close = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            hold_time_hours = round((t_close - t_open).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    outcome_payload = {
        "pnl_realized": realized_pl,
        "hold_time_hours": hold_time_hours,
        "exit_reason": close_reason,
        "closed_at": closed_at,
        "symbol": position.get("symbol"),
    }

    try:
        supabase.table("policy_decisions").update({
            "realized_outcome": outcome_payload,
        }).eq("suggestion_id", suggestion_id).execute()

        logger.info(
            f"policy_decision_outcome_backfill: suggestion_id={str(suggestion_id)[:8]}... "
            f"pnl={realized_pl} hold_hours={hold_time_hours} exit={close_reason}"
        )
    except Exception as e:
        # Non-fatal — don't block the learning ingest pipeline
        logger.warning(
            f"policy_decision_outcome_backfill_error: suggestion_id={str(suggestion_id)[:8]}... "
            f"error={e}"
        )
