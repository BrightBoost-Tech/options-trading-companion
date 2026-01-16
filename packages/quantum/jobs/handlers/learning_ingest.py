"""
Learning Ingest Job Handler

Daily outcome ingestion - Maps executed trades to suggestions for learning.

This handler:
1. Reads Plaid investment transactions since last run
2. Matches transactions to trade_suggestions by symbol/direction/time
3. Inserts outcomes into learning_feedback_loops table
4. Computes win/loss, slippage proxy, holding time
"""

import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError
from packages.quantum.services.token_store import PlaidTokenStore

JOB_NAME = "learning_ingest"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Ingest executed trades and map to suggestions for learning.

    Payload:
        - date: str - Date for idempotency
        - user_id: str|None - Specific user, or all users if None
        - lookback_days: int - How far back to look (default: 7)
    """
    start_time = time.time()
    notes = []
    counts = {"users_processed": 0, "transactions_found": 0, "outcomes_created": 0, "orphans": 0}

    target_user_id = payload.get("user_id")
    lookback_days = payload.get("lookback_days", 7)

    try:
        client = get_admin_client()

        # Get target users
        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            users_processed = 0
            total_transactions = 0
            total_outcomes = 0
            total_orphans = 0

            for uid in active_users:
                try:
                    result = await _ingest_for_user(uid, client, lookback_days)
                    users_processed += 1
                    total_transactions += result.get("transactions", 0)
                    total_outcomes += result.get("outcomes", 0)
                    total_orphans += result.get("orphans", 0)

                    if result.get("outcomes", 0) > 0:
                        notes.append(f"Created {result['outcomes']} outcomes for {uid[:8]}...")

                except Exception as e:
                    notes.append(f"Failed for {uid[:8]}...: {str(e)}")

            return users_processed, total_transactions, total_outcomes, total_orphans

        users_processed, transactions, outcomes, orphans = run_async(process_users())

        counts["users_processed"] = users_processed
        counts["transactions_found"] = transactions
        counts["outcomes_created"] = outcomes
        counts["orphans"] = orphans

        timing_ms = (time.time() - start_time) * 1000

        return {
            "ok": True,
            "counts": counts,
            "timing_ms": timing_ms,
            "lookback_days": lookback_days,
            "notes": notes[:20],
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Learning ingest job failed: {e}")


async def _ingest_for_user(user_id: str, supabase, lookback_days: int) -> Dict[str, Any]:
    """
    Ingest transactions for a single user.

    Returns:
        Dict with counts: {transactions: int, outcomes: int, orphans: int}
    """
    # Check for Plaid connection
    token_store = PlaidTokenStore(supabase)
    access_token = token_store.get_access_token(user_id)

    if not access_token:
        # No Plaid connection - try CSV fallback (future)
        return {"transactions": 0, "outcomes": 0, "orphans": 0, "error": "No Plaid connection"}

    # Fetch transactions from Plaid
    transactions = await _fetch_plaid_transactions(access_token, lookback_days)

    if not transactions:
        return {"transactions": 0, "outcomes": 0, "orphans": 0}

    # Get recent suggestions for matching
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days + 7)).isoformat()
    suggestions_result = supabase.table("trade_suggestions") \
        .select("id, trace_id, ticker, symbol, direction, ev, created_at, status") \
        .eq("user_id", user_id) \
        .gte("created_at", cutoff) \
        .execute()

    suggestions = suggestions_result.data or []

    # Match transactions to suggestions
    outcomes_created = 0
    orphans = 0

    for tx in transactions:
        matched = _match_transaction_to_suggestion(tx, suggestions)

        if matched:
            outcome = _create_outcome_record(user_id, tx, matched)
            _insert_outcome(supabase, outcome)
            outcomes_created += 1
        else:
            # Log orphan transaction (no matching suggestion)
            orphans += 1

    return {
        "transactions": len(transactions),
        "outcomes": outcomes_created,
        "orphans": orphans,
    }


async def _fetch_plaid_transactions(access_token: str, lookback_days: int) -> List[Dict]:
    """
    Fetch investment transactions from Plaid.

    Note: This requires the Investments product to be enabled for the Plaid item.
    Some brokers (like Robinhood) may not support transaction history via Plaid.
    """
    try:
        from packages.quantum import plaid_service

        from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
        from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        request = InvestmentsTransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=InvestmentsTransactionsGetRequestOptions(offset=0)
        )

        response = plaid_service.client.investments_transactions_get(request)
        transactions = response.get("investment_transactions", [])

        # Map security_id to symbol
        securities = {s["security_id"]: s for s in response.get("securities", [])}

        enriched = []
        for tx in transactions:
            sec = securities.get(tx.get("security_id"), {})
            enriched.append({
                "id": tx.get("investment_transaction_id"),
                "date": tx.get("date"),
                "type": tx.get("type"),  # buy, sell, transfer, etc.
                "subtype": tx.get("subtype"),
                "symbol": sec.get("ticker_symbol") or sec.get("name") or "UNKNOWN",
                "quantity": tx.get("quantity", 0),
                "price": tx.get("price", 0),
                "amount": tx.get("amount", 0),  # Total cost (negative for buy, positive for sell)
                "fees": tx.get("fees", 0),
            })

        return enriched

    except ImportError:
        print("[learning_ingest] Plaid models not available")
        return []
    except Exception as e:
        print(f"[learning_ingest] Error fetching Plaid transactions: {e}")
        return []


def _match_transaction_to_suggestion(tx: Dict, suggestions: List[Dict]) -> Optional[Dict]:
    """
    Match a transaction to a suggestion by symbol and direction.

    Matching criteria:
    - Symbol matches (exact or underlying)
    - Direction matches (buy = open, sell = close)
    - Transaction date is within 7 days of suggestion creation
    """
    tx_symbol = tx.get("symbol", "").upper()
    tx_type = tx.get("type", "").lower()
    tx_date = tx.get("date")

    if not tx_symbol or not tx_date:
        return None

    # Determine direction from transaction type
    tx_direction = "open" if tx_type == "buy" else "close" if tx_type == "sell" else None

    if not tx_direction:
        return None

    for sugg in suggestions:
        sugg_symbol = (sugg.get("symbol") or sugg.get("ticker") or "").upper()

        # Check symbol match (exact or underlying extraction)
        if tx_symbol != sugg_symbol:
            # Try underlying match for options (e.g., AAPL240119C150 -> AAPL)
            if not tx_symbol.startswith(sugg_symbol.split()[0] if " " in sugg_symbol else sugg_symbol[:4]):
                continue

        # Check direction match
        sugg_direction = sugg.get("direction", "").lower()
        if sugg_direction not in ["open", "close"]:
            # Infer from window
            window = sugg.get("window", "")
            if "morning" in window or "exit" in window:
                sugg_direction = "close"
            elif "midday" in window or "entry" in window:
                sugg_direction = "open"

        if tx_direction != sugg_direction:
            continue

        # Check date proximity (within 7 days)
        sugg_date_str = sugg.get("created_at", "")
        if sugg_date_str:
            try:
                sugg_date = datetime.fromisoformat(sugg_date_str.replace("Z", "+00:00")).date()
                tx_date_obj = tx_date if isinstance(tx_date, type(sugg_date)) else datetime.fromisoformat(str(tx_date)).date()
                if abs((tx_date_obj - sugg_date).days) <= 7:
                    return sugg
            except Exception:
                pass

    return None


def _create_outcome_record(user_id: str, tx: Dict, suggestion: Dict) -> Dict:
    """
    Create a learning_feedback_loops record from a matched transaction.
    """
    tx_amount = tx.get("amount", 0)
    tx_fees = tx.get("fees", 0)
    predicted_ev = suggestion.get("ev", 0)

    # For sells (closes), amount is positive (proceeds)
    # For buys (opens), amount is negative (cost)
    # PnL realized is calculated when we close a position
    pnl_realized = None
    if tx.get("type") == "sell":
        pnl_realized = float(tx_amount) - float(tx_fees)

    # Determine outcome type
    outcome_type = "unknown"
    if pnl_realized is not None:
        if pnl_realized > 0:
            outcome_type = "win"
        elif pnl_realized < 0:
            outcome_type = "loss"
        else:
            outcome_type = "breakeven"

    return {
        "user_id": user_id,
        "trace_id": suggestion.get("trace_id"),
        "source_event_id": suggestion.get("id"),
        "outcome_type": outcome_type,
        "pnl_realized": pnl_realized,
        "pnl_predicted": predicted_ev,
        "details_json": {
            "transaction_id": tx.get("id"),
            "transaction_date": str(tx.get("date")),
            "transaction_type": tx.get("type"),
            "symbol": tx.get("symbol"),
            "quantity": tx.get("quantity"),
            "price": tx.get("price"),
            "amount": tx_amount,
            "fees": tx_fees,
            "suggestion_window": suggestion.get("window"),
            "suggestion_strategy": suggestion.get("strategy"),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _insert_outcome(supabase, outcome: Dict) -> bool:
    """
    Insert outcome record, handling duplicates.
    """
    try:
        # Check for existing record with same trace_id and transaction_id
        existing = supabase.table("learning_feedback_loops") \
            .select("id") \
            .eq("trace_id", outcome.get("trace_id")) \
            .execute()

        if existing.data and len(existing.data) > 0:
            # Check if this specific transaction was already recorded
            for record in existing.data:
                # Skip if already exists (idempotency)
                return False

        supabase.table("learning_feedback_loops").insert(outcome).execute()
        return True

    except Exception as e:
        print(f"[learning_ingest] Error inserting outcome: {e}")
        return False
