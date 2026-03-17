"""
Paper Learning Ingest Job Handler

Ingests paper trading outcomes into learning_feedback_loops for validation/streak.

This handler:
1. Reads closed paper_positions within lookback window
2. Fetches closing paper_orders for order metadata and dedup key
3. Builds trade_closed outcome records with is_paper: true
4. Inserts into learning_feedback_loops with idempotency via (user_id, order_id)
"""

import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "paper_learning_ingest"


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

        timing_ms = (time.time() - start_time) * 1000

        return {
            "ok": True,
            "counts": counts,
            "timing_ms": timing_ms,
            "lookback_days": lookback_days,
            "target_date": target_date,
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

    # 1. Start from paper_positions — the source of truth for closed trades.
    #    Previous code started from paper_ledger, but paper_ledger lacks a
    #    user_id column, so that query always failed silently.
    pos_result = supabase.table("paper_positions") \
        .select("id, realized_pl, status, closed_at, suggestion_id, trace_id, symbol") \
        .eq("user_id", user_id) \
        .eq("status", "closed") \
        .gte("closed_at", cutoff_iso) \
        .execute()

    closed_positions = pos_result.data or []

    if not closed_positions:
        return {"closed_positions": 0, "outcomes_created": 0, "skipped_duplicate": 0}

    position_ids = [p["id"] for p in closed_positions]
    positions_by_id = {p["id"]: p for p in closed_positions}

    # 2. Fetch closing orders linked to these positions (for metadata and dedup key).
    orders_result = supabase.table("paper_orders") \
        .select("*") \
        .in_("position_id", position_ids) \
        .eq("status", "filled") \
        .execute()

    # Build map: position_id → closing order (use latest if multiple)
    orders_by_position: Dict[str, Dict] = {}
    for o in (orders_result.data or []):
        pid = o.get("position_id")
        if pid:
            # If multiple filled orders for same position, keep the latest
            existing = orders_by_position.get(pid)
            if not existing or (o.get("filled_at") or "") > (existing.get("filled_at") or ""):
                orders_by_position[pid] = o

    # 3. Collect order_ids for dedup check against existing learning records.
    order_ids = [o["id"] for o in orders_by_position.values()]
    existing_order_ids: set = set()
    if order_ids:
        existing_result = supabase.table("learning_feedback_loops") \
            .select("source_event_id") \
            .eq("user_id", user_id) \
            .in_("source_event_id", order_ids) \
            .execute()
        existing_order_ids = {r["source_event_id"] for r in (existing_result.data or [])}

    # 4. Create outcomes for each closed position that has a closing order.
    outcomes_created = 0
    skipped_duplicate = 0

    for position in closed_positions:
        order = orders_by_position.get(position["id"])
        if not order:
            # No closing order found — position may have been closed by a
            # direct DB update or migration. Skip silently.
            continue

        if order["id"] in existing_order_ids:
            skipped_duplicate += 1
            continue

        outcome = _create_paper_outcome_record(user_id, order, target_date, position)

        try:
            supabase.table("learning_feedback_loops").insert(outcome).execute()
            outcomes_created += 1
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                skipped_duplicate += 1
            else:
                raise

    return {
        "closed_positions": len(closed_positions),
        "outcomes_created": outcomes_created,
        "skipped_duplicate": skipped_duplicate,
    }


def _create_paper_outcome_record(
    user_id: str, order: Dict, target_date: str, position: Dict,
) -> Dict:
    """
    Create a learning_feedback_loops record from a paper order fill.

    IMPORTANT: This creates outcome_type='trade_closed' which is required for
    the learning_trade_outcomes_v3 view to include the record. The view filters
    to only outcome_type in ('trade_closed', 'individual_trade').

    Args:
        user_id: User ID
        order: Paper order dict with fill details
        target_date: Date bucket for idempotency
        position: Linked paper_positions row with authoritative realized_pl

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

    return {
        "user_id": user_id,
        "suggestion_id": suggestion_id,  # Required for view join to trade_suggestions
        "trace_id": trace_id,
        "source_event_id": order["id"],
        # CRITICAL: Must be 'trade_closed' for learning_trade_outcomes_v3 view
        "outcome_type": "trade_closed",
        "pnl_realized": pnl_realized,
        "pnl_predicted": tcm.get("expected_slippage"),
        "is_paper": True,
        "details_json": {
            "order_id": order["id"],
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
            "date_bucket": target_date,
            "pnl_outcome": pnl_outcome,  # win/loss/breakeven for analytics
            "is_paper": True,
            "reason_codes": ["paper_trade_close"],
        },
        # Use position's closed_at so the view's COALESCE(updated_at, created_at)
        # reflects the actual close time, not the ingestion time.
        "updated_at": position.get("closed_at"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
