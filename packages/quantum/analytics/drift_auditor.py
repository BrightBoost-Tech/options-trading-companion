import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.services.options_utils import get_contract_multiplier

# --- Configuration Constants ---
LOOKBACK_HOURS = 48
SIZE_VIOLATION_FACTOR = 1.5  # If execution size > 1.5x suggested
MATCH_SIZE_MIN = 0.5         # If execution size < 0.5x suggested, might not be a match?
                             # (Or just loose matching for now, as per prompt [0.5x, 1.5x])
MATCH_SIZE_MAX = 1.5

# Table name for logging drift
DRIFT_LOGS_TABLE = "execution_drift_logs"

def _extract_underlying(symbol: str) -> str:
    """
    Extracts underlying symbol from an option ticker if possible.
    E.g. 'O:SPY230417C00400000' -> 'SPY'
    Or 'SPY 230417 C 400' -> 'SPY'
    Simple heuristic: take first alpha sequence.
    """
    # Remove 'O:' prefix if present (Polygon style)
    if symbol.startswith("O:"):
        symbol = symbol[2:]

    # Match root ticker: 1-5 letters at start
    match = re.match(r"^([A-Z]+)", symbol)
    if match:
        return match.group(1)
    return symbol

def _calculate_notional_size(item: Dict[str, Any]) -> float:
    """
    Calculates rough notional value = quantity * price (or cost).

    For suggestion:
    - uses order_json.quantity (or contracts) * order_json.limit_price * 100 (if option/spread)
    - If limit_price is missing, we might not know value.
    - Or we can use `ev` or specific size fields if available.

    For holding:
    - quantity * current_price * 100 (if option).
    - Plaid usually gives total_value (current_value).
    """

    # 1. Holding (has 'current_value' or 'quantity'/'current_price')
    if "current_value" in item:
        # If explicitly present (snapshot holdings usually have it?)
        # Snapshot structure: holdings list.
        # Check api.py/models: snapshot holding has 'current_price', 'quantity'.
        # Plaid holdings usually have 'institution_value' or we calculate q * p.
        q = float(item.get("quantity", 0))
        p = float(item.get("current_price", 0))

        # Multiplier check. Plaid price is per share.
        # If option, is quantity contracts or shares?
        # Usually Plaid returns contracts for options. So value = q * p * 100.
        # But let's assume `current_value` is the source of truth if available (Plaid computes it).
        # Our `positions` table usually stores q, p.
        # Let's try to infer if it's an option.
        sym = item.get("symbol", "")
        # Use canonical contract multiplier
        multiplier = get_contract_multiplier(sym)
        return q * p * multiplier

    # 2. Suggestion
    # order_json usually has 'limit_price' and 'contracts'/'quantity'.
    order = item.get("order_json", {})
    price = float(order.get("limit_price") or order.get("price") or 0)
    qty = float(order.get("contracts") or order.get("quantity") or 0)

    # Check suggestion for option-ness
    strat = item.get("strategy", "").lower()
    ticker = item.get("ticker", "").lower()
    sym = item.get("symbol", "")

    # Try canonical multiplier first (if specific symbol provided)
    multiplier = get_contract_multiplier(sym)

    # If canonical returned 1 (equity), but strategy implies option, force 100
    # (Suggestions often have underlying ticker as symbol but 'strategy' defines the option nature)
    if multiplier == 1.0:
        is_option_strategy = (
            "spread" in strat or
            "call" in strat or
            "put" in strat or
            "option" in strat or
            "call" in ticker or
            "put" in ticker
        )
        if is_option_strategy:
            multiplier = 100.0

    return qty * price * multiplier

def _is_match(suggestion: Dict[str, Any], holding: Dict[str, Any]) -> bool:
    """
    Determines if a suggestion matches a holding roughly.
    """
    # 1. Symbol Match
    s_sym = suggestion.get("symbol") or suggestion.get("ticker", "")
    h_sym = holding.get("symbol", "")

    # Normalize
    s_root = _extract_underlying(s_sym)
    h_root = _extract_underlying(h_sym)

    if s_root != h_root:
        return False

    # 2. Direction Match (Optional but good)
    # Suggestion: 'buy', 'long', 'sell', 'short'
    # Holding: Quantity > 0 is usually long.
    s_dir = suggestion.get("direction", "").lower()
    h_qty = float(holding.get("quantity", 0))

    # If suggestion is 'close', we might not find a holding (unless partial).
    # Drift auditor usually checks for entries.
    # If suggestion was 'buy'/'long', we expect positive quantity.
    if s_dir in ["buy", "long"] and h_qty < 0:
        return False
    if s_dir in ["sell", "short"] and h_qty > 0:
        # Plaid might show short as negative quantity?
        # If we shorted, we have a position.
        pass

    # 3. Size Band Match
    # "Notional size within a configurable band"
    s_val = _calculate_notional_size(suggestion)
    h_val = _calculate_notional_size(holding)

    if s_val == 0:
        return True # Cannot compare size, assume match if symbol matches

    ratio = h_val / s_val
    if ratio < MATCH_SIZE_MIN or ratio > MATCH_SIZE_MAX:
        # If size is way off, is it the same trade?
        # Maybe partial fill?
        # For 'disciplined_execution', we want it close.
        # But if it exists, it's likely the execution of that plan.
        # If ratio > 1.5, we will flag as size_violation LATER.
        # But is it a match? Yes, it's the same asset.
        pass

    return True

def audit_plan_vs_execution(
    user_id: str,
    snapshot: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    supabase: Any,
) -> None:
    """
    Compare the latest portfolio snapshot (REALITY) with recent suggestions (PLAN)
    and emit journal-style tags indicating execution discipline.
    """
    if not snapshot:
        # Even if suggestions are empty, we might check for impulse trades if holdings exist
        # But if snapshot is empty/None, we can't do anything.
        return

    holdings = snapshot.get("holdings", [])

    # Convert dates for filtering if needed, but caller passes 'recent' suggestions

    logs_to_insert = []

    # Track which holdings are accounted for by suggestions
    matched_holding_indices = set()

    # 1. Check Suggestions -> Holdings (Did we execute the plan?)
    if suggestions:
        for sugg in suggestions:
            # Skip if suggestion is not an entry (e.g. is an exit suggestion)
            # We only audit entries for "impulse vs discipline".
            # If suggestion is 'close', and we don't have it, that's disciplined (we closed it).
            # But finding "impulse trade" requires finding new positions.
            # Let's focus on: Suggestion (Buy) -> Position exists? -> Disciplined.

            direction = sugg.get("direction", "").lower()
            if "close" in direction:
                continue

            # Find matching holding
            match_found = False
            for idx, h in enumerate(holdings):
                if _is_match(sugg, h):
                    match_found = True
                    matched_holding_indices.add(idx)

                    # Check Size Violation
                    s_val = _calculate_notional_size(sugg)
                    h_val = _calculate_notional_size(h)

                    tag = "disciplined_execution"
                    details = {
                        "suggestion_id": sugg.get("id"),
                        "symbol": h.get("symbol"),
                        "suggested_size": s_val,
                        "actual_size": h_val
                    }

                    if s_val > 0 and h_val > s_val * SIZE_VIOLATION_FACTOR:
                        tag = "size_violation"

                    # Deduplicate? If we already logged this suggestion?
                    # The auditor runs on every sync. We might duplicate logs.
                    # Ideally we check if we already logged this suggestion_id.
                    # But for now, we just emit. Downstream/UI can dedupe or we use unique constraints.
                    # We can add a unique key on (suggestion_id, tag) if needed.
                    # Or query existing logs.
                    # For simplicity in this phase, we insert.

                    logs_to_insert.append({
                        "user_id": user_id,
                        "symbol": h.get("symbol"),
                        "tag": tag,
                        "details_json": details,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })

                    # Phase 7: Log Learning Loop Entry (Optional)
                    # "Suggestion + Optimizer State" -> "Actual Execution Outcome"
                    # If we have suggestion_id/trace_id, link it.
                    try:
                        trace_id = sugg.get("order_json", {}).get("context", {}).get("trace_id")
                        if trace_id:
                            # We found a trace_id. Log to learning_feedback_loops.
                            # We don't have realized PnL yet (entry just happened).
                            # We log the 'event' of execution. Later exits will update PnL.
                            # For now, we can just ensure the link exists or log a 'disciplined_entry' event.

                            # However, 'learning_feedback_loops' expects an outcome.
                            # Maybe we wait for exit? Or log entry as 'disciplined_entry' outcome type?
                            # Prompt says: "audit_plan_vs_execution: ... optionally log a learning_feedback_loops row"
                            # outcome_type: 'disciplined_execution'

                            learning_data = {
                                "source_event_id": None, # Could be suggestion ID if UUID
                                "trace_id": trace_id,
                                "user_id": user_id,
                                "outcome_type": tag, # 'disciplined_execution' or 'size_violation'
                                "pnl_realized": None,
                                "pnl_predicted": sugg.get("ev"), # Use EV as predicted PnL proxy
                                "drift_tags": [tag],
                                "details_json": details
                            }
                            supabase.table("learning_feedback_loops").insert(learning_data).execute()
                    except Exception as le:
                        print(f"Learning Loop Log Error: {le}")

                    break

            if not match_found:
                # Suggestion made but not found in holdings.
                # "Missed execution"? Or maybe just not filled yet.
                # We don't log "missed" per spec, only "disciplined", "impulse", "size".
                pass

    # 2. Check Holdings -> Suggestions (Was this an impulse trade?)
    # "If a position exists with no matching suggestion -> Impulse Trade"

    for idx, h in enumerate(holdings):
        if idx in matched_holding_indices:
            continue

        # Unmatched.
        # Check if it's likely a trade we care about (e.g. not CASH/USD)
        sym = h.get("symbol", "").upper()
        if "USD" in sym or "CASH" in sym:
            continue

        # Log as impulse
        logs_to_insert.append({
            "user_id": user_id,
            "symbol": h.get("symbol"),
            "tag": "impulse_trade",
            "details_json": {
                "actual_size": _calculate_notional_size(h),
                "message": "Position held without recent suggestion"
            },
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    # 3. Batch Insert with Deduplication
    if logs_to_insert:
        try:
            # Fetch recent logs to deduplicate
            # We look back 24h to avoid spamming the same event repeatedly
            dedup_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

            existing_res = supabase.table(DRIFT_LOGS_TABLE)\
                .select("tag, symbol, details_json")\
                .eq("user_id", user_id)\
                .gte("created_at", dedup_cutoff)\
                .execute()

            existing_logs = existing_res.data or []

            # Create a set of signatures for existing logs
            # Signature: (tag, symbol, suggestion_id_if_any)
            existing_signatures = set()
            for log in existing_logs:
                details = log.get("details_json") or {}
                sugg_id = details.get("suggestion_id")
                # For impulse trades, suggestion_id is None. Signature: (impulse_trade, symbol, None)
                # For disciplined/size, Signature: (tag, symbol, suggestion_id)
                sig = (log.get("tag"), log.get("symbol"), sugg_id)
                existing_signatures.add(sig)

            # Filter logs_to_insert
            final_insert = []
            for item in logs_to_insert:
                details = item.get("details_json") or {}
                sugg_id = details.get("suggestion_id")
                sig = (item.get("tag"), item.get("symbol"), sugg_id)

                if sig not in existing_signatures:
                    final_insert.append(item)
                    # Add to local set to deduplicate within this batch too (e.g. if loop produced dupes)
                    existing_signatures.add(sig)

            if final_insert:
                supabase.table(DRIFT_LOGS_TABLE).insert(final_insert).execute()

        except Exception as e:
            # Table might not exist yet? Or other error.
            print(f"DriftAuditor Error: Failed to insert logs: {e}")
