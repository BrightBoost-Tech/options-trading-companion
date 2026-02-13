"""
Paper Learning Ingest Job Handler

Ingests paper trading outcomes into learning_feedback_loops for validation/streak.

This handler:
1. Reads paper_ledger rows within lookback window
2. Builds trade_closed outcome records with is_paper: true
3. Inserts into learning_feedback_loops with idempotency via (user_id, order_id)
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
        "ledger_entries_found": 0,
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
                    total_entries += result.get("ledger_entries", 0)
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
        counts["ledger_entries_found"] = entries
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

    Reads paper_ledger entries of type FILL within lookback window,
    joins with paper_orders to get order details, and creates
    learning_feedback_loops records.

    Returns:
        Dict with counts: {ledger_entries: int, outcomes_created: int, skipped_duplicate: int}
    """
    # Compute lookback cutoff
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_iso = cutoff_date.isoformat()

    # Fetch paper_ledger entries of type FILL for this user
    ledger_result = supabase.table("paper_ledger") \
        .select("*") \
        .eq("user_id", user_id) \
        .in_("event_type", ["fill", "FILL", "partial_fill", "PARTIAL_FILL"]) \
        .gte("created_at", cutoff_iso) \
        .execute()

    ledger_entries = ledger_result.data or []

    if not ledger_entries:
        return {"ledger_entries": 0, "outcomes_created": 0, "skipped_duplicate": 0}

    # Extract order_ids from ledger entries
    order_ids = []
    for entry in ledger_entries:
        order_id = entry.get("order_id")
        if order_id:
            order_ids.append(order_id)

    # Dedupe order_ids
    order_ids = list(set(order_ids))

    if not order_ids:
        return {"ledger_entries": len(ledger_entries), "outcomes_created": 0, "skipped_duplicate": 0}

    # Fetch corresponding paper_orders
    orders_result = supabase.table("paper_orders") \
        .select("*") \
        .in_("id", order_ids) \
        .execute()

    orders = {o["id"]: o for o in (orders_result.data or [])}

    # Check existing outcomes to avoid duplicates
    existing_result = supabase.table("learning_feedback_loops") \
        .select("source_event_id") \
        .eq("user_id", user_id) \
        .in_("source_event_id", order_ids) \
        .execute()

    existing_order_ids = {r["source_event_id"] for r in (existing_result.data or [])}

    # Create outcomes
    outcomes_created = 0
    skipped_duplicate = 0

    for order_id in order_ids:
        if order_id in existing_order_ids:
            skipped_duplicate += 1
            continue

        order = orders.get(order_id)
        if not order:
            continue

        # Only process filled orders
        if order.get("status") not in ("filled", "partial"):
            continue

        outcome = _create_paper_outcome_record(user_id, order, target_date)

        try:
            supabase.table("learning_feedback_loops").insert(outcome).execute()
            outcomes_created += 1
        except Exception as e:
            # Check if it's a duplicate key error (idempotency)
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                skipped_duplicate += 1
            else:
                raise

    return {
        "ledger_entries": len(ledger_entries),
        "outcomes_created": outcomes_created,
        "skipped_duplicate": skipped_duplicate,
    }


def _create_paper_outcome_record(user_id: str, order: Dict, target_date: str) -> Dict:
    """
    Create a learning_feedback_loops record from a paper order fill.

    Args:
        user_id: User ID
        order: Paper order dict with fill details
        target_date: Date bucket for idempotency

    Returns:
        Dict ready for insertion into learning_feedback_loops
    """
    filled_qty = float(order.get("filled_qty") or 0)
    avg_fill_price = float(order.get("avg_fill_price") or 0)
    requested_price = float(order.get("requested_price") or 0)
    side = order.get("side", "buy")

    # Calculate PnL for closing orders
    # For paper trading, we compute slippage as the difference between
    # requested price and fill price
    if side in ("sell", "sell_to_close"):
        # Closing a long: positive if fill > requested
        pnl_realized = (avg_fill_price - requested_price) * filled_qty
    else:
        # Opening or closing short: negative if fill > requested
        pnl_realized = (requested_price - avg_fill_price) * filled_qty

    # Determine outcome type
    if pnl_realized > 0:
        outcome_type = "win"
    elif pnl_realized < 0:
        outcome_type = "loss"
    else:
        outcome_type = "breakeven"

    # Extract trace_id from order if present
    trace_id = order.get("trace_id")

    # Get symbol from order_json or direct field
    order_json = order.get("order_json") or {}
    symbol = order_json.get("symbol") or order.get("symbol") or "UNKNOWN"

    # Get TCM metrics if present
    tcm = order.get("tcm") or {}
    predicted_fill_price = tcm.get("expected_fill_price")
    fill_probability = tcm.get("fill_probability")

    return {
        "user_id": user_id,
        "trace_id": trace_id,
        "source_event_id": order["id"],
        "outcome_type": outcome_type,
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
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
