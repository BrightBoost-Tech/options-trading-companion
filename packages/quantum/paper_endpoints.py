from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime, timezone, timedelta
import logging
import uuid
import os
import time

from packages.quantum.security import get_current_user
from packages.quantum.models import TradeTicket, OptionLeg
from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE
from packages.quantum.strategy_registry import STRATEGY_REGISTRY, infer_strategy_key_from_suggestion
from packages.quantum.market_data import PolygonService
from packages.quantum.strategy_profiles import CostModelConfig
from packages.quantum.services.options_utils import parse_option_symbol

# Execution V3
from packages.quantum.execution.transaction_cost_model import TransactionCostModel
from packages.quantum.execution.pnl_attribution import PnlAttribution
from packages.quantum.services.paper_execution_service import PaperExecutionService
from packages.quantum.services.paper_ledger_service import PaperLedgerService, PaperLedgerEventType

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, emit_trade_event, TradeEventName
from packages.quantum.services.analytics_service import AnalyticsService
from packages.quantum.agents.agents.post_trade_review_agent import PostTradeReviewAgent

router = APIRouter()
logger = logging.getLogger(__name__)


def _fetch_quote_with_retry(
    poly: PolygonService,
    symbol: str,
    max_retries: int = 3,
    base_delay: float = 0.5
) -> Optional[Dict[str, Any]]:
    """
    Fetch a quote from Polygon with exponential backoff retry.

    v4-L1F Optimization: Prevents transient API failures from causing
    missing quotes during order staging/processing.

    Args:
        poly: PolygonService instance
        symbol: The symbol to fetch quote for
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds between retries (default: 0.5)

    Returns:
        Quote dict on success, None on failure after all retries
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return poly.get_recent_quote(symbol)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 0.5, 1.0, 2.0
                logger.warning(
                    f"Polygon quote fetch failed for {symbol} (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"Polygon quote fetch failed for {symbol} after {max_retries} attempts: {e}"
                )
    return None


# Expected leg counts per strategy type — unknown strategies pass through without validation
STRATEGY_LEG_COUNTS = {
    "long_call": 1, "long_put": 1, "naked_call": 1, "naked_put": 1,
    "vertical_spread": 2, "credit_spread": 2, "debit_spread": 2,
    "vertical_call": 2, "vertical_put": 2,
    "credit_call_spread": 2, "credit_put_spread": 2,
    "debit_call_spread": 2, "debit_put_spread": 2,
    "call_spread": 2, "put_spread": 2,
    "butterfly": 3,
    "condor": 4, "iron_condor": 4, "iron_butterfly": 4,
}


def _validate_order_legs(ticket: TradeTicket) -> None:
    """
    Validate that all option legs have required fields before order creation.

    Checks:
    1. Every call/put leg has non-null strike and expiry
    2. Every call/put leg has an OCC-format symbol
    3. Leg count matches strategy_type when strategy is known

    Raises ValueError with descriptive message on failure.
    """
    # Check strategy-to-leg-count match
    strategy = ticket.strategy_type
    if strategy and strategy in STRATEGY_LEG_COUNTS:
        expected = STRATEGY_LEG_COUNTS[strategy]
        actual = len(ticket.legs)
        if actual != expected:
            raise ValueError(
                f"Strategy '{strategy}' requires {expected} legs but got {actual}"
            )

    # Check each option leg has required fields
    for i, leg in enumerate(ticket.legs):
        if leg.type in ("call", "put"):
            if leg.strike is None:
                raise ValueError(
                    f"Leg {i} ({leg.symbol}) missing strike — "
                    f"cannot create order without strike price"
                )
            if leg.expiry is None:
                raise ValueError(
                    f"Leg {i} ({leg.symbol}) missing expiry — "
                    f"cannot create order without expiration date"
                )
            if not leg.symbol or not (leg.symbol.startswith("O:") or len(leg.symbol) > 10):
                raise ValueError(
                    f"Leg {i} has non-OCC symbol '{leg.symbol}' — "
                    f"options legs require OCC format (e.g., O:META260417C00500000)"
                )


def _resolve_quote_symbol(ticket_data: Dict[str, Any]) -> str:
    """
    Resolve the OCC options contract symbol for quote fetching.

    The ticket's top-level 'symbol' field stores the underlying ticker (e.g., "META").
    Polygon requires the full OCC symbol (e.g., "O:META260417C00500000") for options quotes.
    This helper extracts the first leg's symbol when it's an options contract.

    Args:
        ticket_data: TradeTicket dict or order_json dict with 'symbol' and 'legs' keys

    Returns:
        OCC symbol if available (e.g., "O:META260417C00500000"), else underlying ticker
    """
    legs = ticket_data.get("legs", [])
    if legs:
        first_leg_sym = legs[0].get("symbol", "") if isinstance(legs[0], dict) else getattr(legs[0], "symbol", "")
        if first_leg_sym and (first_leg_sym.startswith("O:") or len(first_leg_sym) > 10):
            return first_leg_sym
    underlying = ticket_data.get("symbol", "UNKNOWN")
    logger.warning(
        f"No OCC symbol found in legs for {underlying} — falling back to underlying ticker. "
        f"Quote will be stock NBBO, not options."
    )
    return underlying


def get_supabase():
    # Lazy import to avoid circular imports; use the canonical backend module path.
    from packages.quantum.api import supabase_admin
    return supabase_admin

def get_analytics_service():
    # Lazy import to avoid circular imports; use the canonical backend module path.
    from packages.quantum.api import analytics_service
    return analytics_service


def _is_pgrst204_order_type_error(exc: Exception) -> bool:
    """
    Check if exception is a PGRST204 schema cache error for order_type column.

    PostgREST intermittently returns PGRST204 when schema cache is stale.
    This helper detects the specific error to allow targeted retry.
    """
    err_str = str(exc).lower()
    # Check for PGRST204 code AND order_type column reference
    is_pgrst204 = "pgrst204" in err_str
    mentions_order_type = "order_type" in err_str
    mentions_schema_cache = "schema cache" in err_str or "could not find" in err_str
    return is_pgrst204 and mentions_order_type and mentions_schema_cache


class StageOrderRequest(BaseModel):
    ticket: TradeTicket
    portfolio_id: Optional[str] = None  # if null, use/create default

class PaperCloseRequest(BaseModel):
    position_id: str

class BatchStageRequest(BaseModel):
    suggestion_ids: List[str]

@router.post("/paper/order/stage")
def stage_order_endpoint(
    req: StageOrderRequest,
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    analytics = get_analytics_service()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    order_id = _stage_order_internal(supabase, analytics, user_id, req.ticket, req.portfolio_id)
    return {"status": "staged", "order_id": order_id}

@router.post("/inbox/stage-batch")
def stage_batch_endpoint(
    req: BatchStageRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Stages multiple suggestions into paper orders in one request.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    if not req.suggestion_ids:
        return {"staged": [], "failed": []}

    # Fetch all suggestions
    try:
        s_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").in_("id", req.suggestion_ids).eq("user_id", user_id).execute()
        suggestions = s_res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch suggestions: {e}")

    staged_results = []
    failed_results = []

    # Map for easy lookup
    suggestions_map = {s["id"]: s for s in suggestions}

    for s_id in req.suggestion_ids:
        suggestion = suggestions_map.get(s_id)
        if not suggestion:
            failed_results.append({"suggestion_id": s_id, "error": "Suggestion not found or not owned by user"})
            continue

        # Idempotency Check
        current_status = suggestion.get("status")
        if current_status == "staged":
            # Check if order actually exists
            existing_order = supabase.table("paper_orders").select("id").eq("suggestion_id", s_id).execute()
            if existing_order.data:
                # Already successfully staged
                staged_results.append({"suggestion_id": s_id, "order_id": existing_order.data[0]["id"]})
                continue
            else:
                # Inconsistent state: marked staged but no order. treat as failure to be safe, or allow re-stage?
                # Prompt says: fail with specific error
                failed_results.append({"suggestion_id": s_id, "error": "already staged but no paper order found"})
                continue

        if current_status != "pending":
            failed_results.append({"suggestion_id": s_id, "error": f"Status is {current_status}, expected pending"})
            continue

        try:
            # Convert to Ticket
            ticket = _suggestion_to_ticket(suggestion)

            # Stage Order
            order_id = _stage_order_internal(
                supabase,
                analytics,
                user_id,
                ticket,
                portfolio_id_arg=None, # Default portfolio
                suggestion_id_override=s_id # Ensure linking
            )

            # Update Suggestion Status - STRICTLY status only
            supabase.table(TRADE_SUGGESTIONS_TABLE).update({
                "status": "staged"
            }).eq("id", s_id).execute()

            staged_results.append({"suggestion_id": s_id, "order_id": order_id})

        except Exception as e:
            logging.error(f"Failed to stage suggestion {s_id}: {e}")
            failed_results.append({"suggestion_id": s_id, "error": str(e)})

    return {
        "staged": staged_results,
        "failed": failed_results,
        "staged_count": len(staged_results),
        "failed_ids": [f["suggestion_id"] for f in failed_results]
    }

@router.post("/paper/order/process")
def process_orders_endpoint(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user), # Optional: restrict to admin or allow user to trigger their own
):
    # This processes orders for ALL users if run by system, but here let's process for the calling user
    # Or, if this is meant to be a cron hook, it might need a secret key.
    # The requirement says "internal task", so maybe we allow it for the user context.

    supabase = get_supabase()
    analytics = get_analytics_service()

    # Process synchronously for immediate feedback in this MVP phase, or queue
    # For better UX, we'll do sync for now, but return count

    result = _process_orders_for_user(supabase, analytics, user_id)
    return {
        "status": "processed",
        "count": result["processed"],
        "errors": result["errors"] if result["errors"] else None
    }


@router.post("/paper/execute")
def execute_paper_trade(
    req: StageOrderRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Legacy wrapper / Immediate Mode:
    Stages the order then immediately processes it.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Stage
    order_id = _stage_order_internal(supabase, analytics, user_id, req.ticket, req.portfolio_id)

    # 2. Process Immediately (scoped to this order for efficiency?)
    # We'll just run the user process loop, it should pick up this order.
    _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

    # 3. Fetch result
    order_res = supabase.table("paper_orders").select("*").eq("id", order_id).single().execute()
    order = order_res.data

    if not order:
        raise HTTPException(status_code=500, detail="Order lost after processing")

    # Return similar shape to v1 for compatibility
    # Need to fetch portfolio and position
    portfolio_res = supabase.table("paper_portfolios").select("*").eq("id", order["portfolio_id"]).single().execute()
    portfolio = portfolio_res.data

    # Find position if it exists
    # We don't easily know the position ID unless we link it.
    # But we can query by strategy key from ticket
    strategy_key = _derive_strategy_key(req.ticket)
    position_res = supabase.table("paper_positions").select("*").eq("portfolio_id", order["portfolio_id"]).eq("strategy_key", strategy_key).execute()
    position = position_res.data[0] if position_res.data else None

    return {
        "status": order["status"],
        "portfolio": portfolio,
        "order": order,
        "position": position
    }

@router.post("/paper/close")
def close_paper_position(
    req: PaperCloseRequest,
    user_id: str = Depends(get_current_user),
):
    """
    V3 Close: Stages a closing order linked to the position, then processes it.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Lookup position
    pos_res = supabase.table("paper_positions").select("*").eq("id", req.position_id).single().execute()
    if not pos_res.data:
        raise HTTPException(status_code=404, detail="Position not found")
    position = pos_res.data

    # Verify ownership
    port_res = supabase.table("paper_portfolios").select("user_id").eq("id", position["portfolio_id"]).single().execute()
    if not port_res.data or port_res.data["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # 2. Create Closing Ticket
    # Invert direction. If we hold +1 quantity, we sell 1.
    qty = float(position["quantity"])
    side = "sell" if qty > 0 else "buy" # Simplification for now (assuming long holds positive qty)

    # Construct Ticket
    ticket = TradeTicket(
        symbol=position["symbol"],
        quantity=abs(qty),
        order_type="market", # Default close to market for now
        strategy_type=position.get("strategy_key", "").split("_")[-1],
        source_engine="manual_close",
        legs=[
            {"symbol": position["symbol"], "action": side, "quantity": abs(qty)}
        ]
    )

    # 3. Stage Closing Order
    # Reuse trace_id from position
    trace_id_override = position.get("trace_id")
    # Also pass suggestion_id as source_ref for full context lookup
    if position.get("suggestion_id"):
        ticket.source_ref_id = position.get("suggestion_id")

    order_id = _stage_order_internal(
        supabase,
        analytics,
        user_id,
        ticket,
        position["portfolio_id"],
        position_id=req.position_id,
        trace_id_override=trace_id_override
    )

    # 4. Process
    _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

    # 5. Fetch result order
    order_res = supabase.table("paper_orders").select("*").eq("id", order_id).single().execute()
    order = order_res.data

    if order and order["status"] == "filled":
        # Attribution Logic is handled inside _process_orders_for_user upon fill
        pass

    return {
        "status": order["status"] if order else "unknown",
        "order_id": order_id
    }

# --- Internal Helpers ---

def _suggestion_to_ticket(suggestion: Dict[str, Any]) -> TradeTicket:
    """
    Converts a suggestion dict (from DB) into a TradeTicket for staging.
    """
    order_json = suggestion.get("order_json", {})

    # 1. Determine Strategy Type
    strategy_type = suggestion.get("strategy") or suggestion.get("strategy_type") or "custom"

    # 2. Determine Symbol (Underlying)
    # Prefer top-level ticker, then order_json underlying, then first leg underlying
    symbol = suggestion.get("ticker") or order_json.get("underlying")

    legs_data = order_json.get("legs", [])

    # If no symbol yet, try to parse from first leg
    if not symbol and legs_data:
        first_leg_sym = legs_data[0].get("symbol")
        parsed = parse_option_symbol(first_leg_sym)
        if parsed:
            symbol = parsed.get("underlying")
        else:
            symbol = first_leg_sym # Fallback

    if not symbol:
        symbol = "UNKNOWN"

    # 3. Determine Quantity (Spreads)
    # Midday usually has 'contracts' in order_json
    # Morning usually has quantity per leg
    quantity = int(order_json.get("contracts", 1))
    if quantity <= 0:
        # Fallback to first leg quantity
        if legs_data:
            quantity = int(legs_data[0].get("quantity", 1))
        else:
            quantity = 1

    # 4. Construct Legs
    option_legs = []

    # Determine side logic
    # Morning: side="close_spread" top level. Legs have holding side. We must INVERT.
    # Midday: legs have side="buy"/"sell". We use AS IS.

    top_side = order_json.get("side", "")
    is_closing_spread = top_side == "close_spread" or suggestion.get("direction") == "close"

    for l in legs_data:
        l_sym = l.get("symbol")
        l_qty = int(l.get("quantity", 1))
        l_side = l.get("side", "buy").lower()

        if is_closing_spread:
            # Invert side
            # If holding is long (buy), we sell. If short (sell), we buy.
            # Usually side in leg describes the holding?
            # "side": "long" -> action="sell"
            # "side": "short" -> action="buy"
            if l_side in ["long", "buy"]:
                action = "sell"
            elif l_side in ["short", "sell"]:
                action = "buy"
            else:
                action = "sell" # Default close to sell?
        else:
            # Opening (Midday)
            # "side": "buy" -> action="buy"
            # "side": "sell" -> action="sell"
            action = l_side if l_side in ["buy", "sell"] else "buy"

        # Parse type/expiry/strike
        parsed = parse_option_symbol(l_sym)
        if parsed:
            l_type = "call" if parsed["type"] == "C" else "put"
            l_strike = parsed["strike"]
            l_expiry = parsed["expiry"]
        else:
            l_type = "stock" # or other
            l_strike = None
            l_expiry = None

        option_legs.append(OptionLeg(
            symbol=l_sym,
            action=action,
            type=l_type,
            strike=l_strike,
            expiry=l_expiry,
            quantity=l_qty
        ))

    # 5. Limit Price
    limit_price = order_json.get("limit_price")
    order_type = "limit" if limit_price else "market"
    if limit_price:
        limit_price = float(limit_price)

    ticket = TradeTicket(
        source_engine=suggestion.get("window", "manual"), # use window as engine proxy
        source_ref_id=suggestion.get("id"),
        strategy_type=strategy_type,
        symbol=symbol,
        legs=option_legs,
        order_type=order_type,
        limit_price=limit_price,
        quantity=quantity,
        conviction_score=suggestion.get("probability_of_profit"), # approximate mapping
        expected_value=suggestion.get("ev"),
        # regime_context=suggestion.get("regime", {}) # string vs dict mismatch potential, skip for now
    )

    return ticket

def _derive_strategy_key(ticket: TradeTicket) -> str:
    mock_suggestion = {
        "strategy_type": ticket.strategy_type,
        "strategy": ticket.strategy_type,
    }
    normalized_strat = infer_strategy_key_from_suggestion(mock_suggestion)
    if normalized_strat == "unknown":
        normalized_strat = "custom"
    return f"{ticket.symbol}_{normalized_strat}"

def _get_or_create_portfolio(supabase, user_id, portfolio_id=None):
    if portfolio_id:
        res = supabase.table("paper_portfolios").select("*").eq("id", portfolio_id).eq("user_id", user_id).single().execute()
        if res.data:
            return res.data
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Default
    existing = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).order("created_at", desc=False).limit(1).execute()
    if existing.data:
        return existing.data[0]

    # Create
    new_port = supabase.table("paper_portfolios").insert({
        "user_id": user_id,
        "name": "Main Paper",
        "cash_balance": 100000.0,
        "net_liq": 100000.0
    }).execute()
    if not new_port.data:
        raise HTTPException(status_code=500, detail="Failed to create portfolio")
    return new_port.data[0]

def _stage_order_internal(supabase, analytics, user_id, ticket: TradeTicket, portfolio_id_arg=None, position_id=None, trace_id_override=None, suggestion_id_override=None):
    portfolio = _get_or_create_portfolio(supabase, user_id, portfolio_id_arg)
    portfolio_id = portfolio["id"]

    # Resolve Context
    suggestion_id = suggestion_id_override
    trace_id = trace_id_override

    # Metadata for telemetry
    model_version = None
    features_hash = None
    strategy = None
    window = None
    regime = None

    if ticket.source_ref_id and not suggestion_id:
        suggestion_id = str(ticket.source_ref_id)

    if suggestion_id:
        # Fetch suggestion context
        try:
             s_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("id", suggestion_id).single().execute()
             if s_res.data:
                 s_data = s_res.data
                 # Prefer suggestion's trace_id unless overridden (which shouldn't happen usually if linked)
                 if not trace_id:
                     trace_id = s_data.get("trace_id")

                 model_version = s_data.get("model_version")
                 features_hash = s_data.get("features_hash")
                 strategy = s_data.get("strategy")
                 window = s_data.get("window")
                 regime = s_data.get("regime")
        except:
            pass

    if not trace_id:
        trace_id = str(uuid.uuid4())

    # Validate legs before proceeding — rejects orders with null strike/expiry
    # or strategy/leg count mismatch (e.g., condor with 1 leg)
    _validate_order_legs(ticket)

    # Fetch Quote (v4-L1F: with retry and exponential backoff)
    poly = PolygonService()
    quote_symbol = _resolve_quote_symbol(ticket.model_dump(mode="json"))
    quote = _fetch_quote_with_retry(poly, quote_symbol)

    # Validate quote before passing to TCM — treat zero bid/ask as missing
    if quote is not None and not _is_valid_quote(quote):
        logger.warning(
            f"paper_stage_invalid_quote: symbol={quote_symbol} quote={quote} — "
            f"treating as missing"
        )
        quote = None

    # TCM Estimate
    tcm_est = TransactionCostModel.estimate(ticket, quote)

    # Determine execution mode upfront so it's set on insert (not patched after)
    from packages.quantum.brokers.execution_router import get_execution_mode, ExecutionMode
    exec_mode = get_execution_mode()

    # Prepare Order
    side = ticket.legs[0].action if ticket.legs else "buy"

    order_payload = {
        "user_id": user_id,
        "portfolio_id": portfolio_id,
        "status": "staged",
        "execution_mode": exec_mode.value,
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "suggestion_id": suggestion_id,
        "order_json": ticket.model_dump(mode="json"),

        # V3 Fields
        "requested_qty": ticket.quantity,
        "requested_price": ticket.limit_price,
        "side": side,
        "order_type": ticket.order_type,
        "quote_at_stage": quote,
        "tcm": tcm_est,
        "position_id": position_id
    }

    # Insert with retry for PGRST204(order_type) schema cache errors
    try:
        res = supabase.table("paper_orders").insert(order_payload).execute()
    except Exception as e:
        if _is_pgrst204_order_type_error(e):
            # Retry without order_type field (schema cache may be stale)
            logger.warning(
                f"paper_orders insert PGRST204(order_type) retry_without_order_type=true "
                f"trace_id={trace_id} suggestion_id={suggestion_id}"
            )
            retry_payload = {k: v for k, v in order_payload.items() if k != "order_type"}
            res = supabase.table("paper_orders").insert(retry_payload).execute()
        else:
            raise

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to stage order")

    order_id = res.data[0]["id"]

    # Telemetry
    ctx = TradeContext(
        trace_id=trace_id,
        suggestion_id=suggestion_id,
        model_version=model_version,
        features_hash=features_hash,
        strategy=strategy,
        window=window,
        regime=regime
    )
    emit_trade_event(analytics, user_id, ctx, "order_staged", is_paper=True, properties={"order_id": order_id})

    # Submit to Alpaca when execution mode requires a broker call.
    # Uses build_alpaca_order_request which translates leg fields
    # (action→side, quantity→qty, Polygon→Alpaca OCC symbols).
    dry_run = os.environ.get("ALPACA_DRY_RUN", "0") == "1"
    if exec_mode in (ExecutionMode.ALPACA_PAPER, ExecutionMode.ALPACA_LIVE):
        if dry_run:
            # Log what we WOULD submit, but don't call Alpaca
            from packages.quantum.brokers.alpaca_order_handler import build_alpaca_order_request
            try:
                order_row = res.data[0]
                req = build_alpaca_order_request(order_row)
                logger.info(
                    f"[ALPACA_DRY_RUN] Would submit order_id={order_id}: {req}"
                )
            except Exception as e:
                logger.warning(f"[ALPACA_DRY_RUN] Build failed: {e}")
        else:
            try:
                from packages.quantum.brokers.alpaca_order_handler import submit_and_track
                from packages.quantum.brokers.alpaca_client import get_alpaca_client
                alpaca = get_alpaca_client()
                order_row = res.data[0]
                submit_and_track(alpaca, supabase, order_row, user_id)
            except Exception as e:
                # Log but don't prevent order_id from returning — the order
                # stays staged with execution_mode already set so it can be
                # retried by the sweep or a manual re-submission.
                logger.error(
                    f"alpaca_submit_failed: order_id={order_id} "
                    f"trace_id={trace_id} error={e}"
                )

    return order_id

def _compute_fill_deltas(order: dict, fill_res: dict) -> dict:
    """
    Computes incremental deltas for this tick's fill.
    Returns:
        this_fill_qty: float (incremental qty filled this tick)
        this_fill_price: float (price for this incremental fill)
        new_total_filled_qty: float (cumulative)
        new_avg_fill_price: float (cumulative avg)
        fees_total: float (cumulative fees)
        fees_delta: float (incremental fees this tick)
    """

    req_qty = float(order.get("requested_qty") or order.get("quantity") or 0.0)
    prev_total_filled = float(order.get("filled_qty") or 0.0)
    prev_fees_total = float(order.get("fees_usd") or 0.0)

    new_total_filled_qty = float(fill_res.get("filled_qty") or 0.0)
    new_avg_fill_price = float(fill_res.get("avg_fill_price") or 0.0)

    this_fill_qty = float(fill_res.get("last_fill_qty") or 0.0)
    if this_fill_qty <= 0:
        this_fill_qty = max(0.0, new_total_filled_qty - prev_total_filled)

    this_fill_price = float(fill_res.get("last_fill_price") or 0.0)
    if this_fill_price <= 0:
        this_fill_price = float(fill_res.get("avg_fill_price") or 0.0)

    # Fees math
    tcm_est = order.get("tcm") or {}
    est_fees = float(tcm_est.get("fees_usd") or 0.0)

    if req_qty > 0:
        fees_total = (new_total_filled_qty / req_qty) * est_fees
    else:
        fees_total = 0.0

    fees_delta = max(0.0, fees_total - prev_fees_total)

    return {
        "this_fill_qty": this_fill_qty,
        "this_fill_price": this_fill_price,
        "new_total_filled_qty": new_total_filled_qty,
        "new_avg_fill_price": new_avg_fill_price,
        "fees_total": fees_total,
        "fees_delta": fees_delta
    }

def _is_valid_quote(quote: dict) -> bool:
    """
    Check if a quote has valid pricing data.

    Returns True if:
    - bid and ask (or bid_price and ask_price) are both > 0, OR
    - price > 0

    Invalid quotes (0/0 or None values) should be treated as missing.
    """
    if not quote or not isinstance(quote, dict):
        return False

    # Check bid/ask (common format)
    bid = quote.get("bid") or quote.get("bid_price") or 0
    ask = quote.get("ask") or quote.get("ask_price") or 0

    try:
        bid = float(bid)
        ask = float(ask)
        if bid > 0 and ask > 0:
            return True
    except (TypeError, ValueError):
        pass

    # Fallback: check price field
    price = quote.get("price") or quote.get("last") or 0
    try:
        price = float(price)
        if price > 0:
            return True
    except (TypeError, ValueError):
        pass

    return False


def _process_orders_for_user(supabase, analytics, user_id, target_order_id=None):
    """
    Process paper orders for a user, attempting fills and updating state.

    v4-L1F Optimization: Returns dict with processed count and any errors,
    allowing callers to detect partial failures without losing progress.

    Returns:
        dict with keys:
            - processed: int, number of orders successfully processed
            - errors: list of dicts with order_id and error message (never null)
            - total_orders: int, total orders attempted
            - diagnostics: list of per-order processing details
    """
    # Fetch working orders: staged, working, or partial
    # A1) Replace exact "staged" check with list of in-flight states
    # We need to filter by portfolio owned by user, or join.
    # Simplest is to get user portfolios then filter orders.
    # Or rely on RLS if enabled. Assuming we trust backend:

    result = {"processed": 0, "errors": [], "total_orders": 0, "diagnostics": []}

    # Get user portfolios
    p_res = supabase.table("paper_portfolios").select("id, cash_balance").eq("user_id", user_id).execute()
    if not p_res.data:
        return result
    p_map = {p["id"]: p for p in p_res.data}
    p_ids = list(p_map.keys())

    # A1 Implementation
    query = supabase.table("paper_orders").select("*").in_("status", ["staged", "working", "partial"])
    orders_res = query.in_("portfolio_id", p_ids).execute()
    orders = orders_res.data or []

    # Fetch orphan filled orders: status='filled' but position_id is NULL and filled_qty > 0
    # These need repair because previous commits failed (e.g., position creation errors)
    orphan_query = supabase.table("paper_orders").select("*").eq("status", "filled").is_("position_id", "null")
    orphan_res = orphan_query.in_("portfolio_id", p_ids).execute()
    orphan_orders = [o for o in (orphan_res.data or []) if float(o.get("filled_qty") or 0) > 0]

    # Bug 5 fix: Always repair orphans first, regardless of target_order_id.
    # Previously, orphans were merged with normal orders and then filtered by
    # target_order_id, causing orphans from prior runs to never get repaired.
    for order in orphan_orders:
        order_id = order.get("id", "unknown")
        try:
            repair_result = _repair_filled_order_commit(
                supabase, analytics, user_id, order, p_map[order["portfolio_id"]]
            )
            if repair_result.get("repaired"):
                result["processed"] += 1
                logger.info(
                    f"paper_order_repaired: order_id={order_id} "
                    f"position_id={repair_result.get('position_id')} "
                    f"ledger_inserted={repair_result.get('ledger_inserted')}"
                )
                result["diagnostics"].append({
                    "order_id": order_id,
                    "symbol": order.get("order_json", {}).get("symbol"),
                    "fill_status": "repaired",
                    "quote_present": False,
                    "last_fill_qty": 0,
                    "repair_result": repair_result,
                })
        except Exception as e:
            logger.error(f"paper_order_repair_error: order_id={order_id} error={e}")
            result["errors"].append({"order_id": order_id, "error": str(e)})

    # Cancel stale working orders (stuck > 2 hours with no fills).
    # These are unrecoverable — the market has moved on. Cancel and log.
    STALE_WORKING_MINUTES = 120
    now_utc = datetime.now(timezone.utc)
    live_orders = []
    for order in orders:
        oid = order.get("id", "unknown")
        status = order.get("status")
        filled = float(order.get("filled_qty") or 0)
        submitted = order.get("submitted_at") or order.get("created_at")
        if status == "working" and filled == 0 and submitted:
            try:
                sub_dt = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
                age_min = (now_utc - sub_dt).total_seconds() / 60
                if age_min > STALE_WORKING_MINUTES:
                    supabase.table("paper_orders").update({
                        "status": "cancelled",
                        "cancelled_reason": f"stale_working_{int(age_min)}m",
                    }).eq("id", oid).execute()
                    logger.warning(
                        f"paper_order_stale_cancel: order_id={oid} "
                        f"age_min={int(age_min)} — cancelled (stuck > {STALE_WORKING_MINUTES}m)"
                    )
                    result["diagnostics"].append({
                        "order_id": oid,
                        "symbol": order.get("order_json", {}).get("symbol"),
                        "fill_status": "cancelled_stale",
                        "age_minutes": int(age_min),
                    })
                    continue
            except (ValueError, TypeError):
                pass
        live_orders.append(order)

    # Apply target_order_id filter to normal in-flight orders only
    target_orders = live_orders
    if target_order_id:
        target_orders = [o for o in live_orders if o["id"] == target_order_id]

    result["total_orders"] = len(orphan_orders) + len(target_orders)
    poly = PolygonService()

    for order in target_orders:
        order_id = order.get("id", "unknown")
        prior_status = order.get("status", "unknown")
        try:
            # Fetch fresh quote
            # Extract OCC symbol from order_json legs (not the underlying ticker)
            ticket_data = order.get("order_json", {})
            symbol = _resolve_quote_symbol(ticket_data)

            # v4-L1F: Fetch quote with retry and exponential backoff
            quote = _fetch_quote_with_retry(poly, symbol) if symbol else None

            # Validate quote - treat invalid quotes (0/0) as missing
            if quote is not None and not _is_valid_quote(quote):
                logger.warning(
                    f"paper_order_invalid_quote: order_id={order_id} symbol={symbol} "
                    f"quote={quote} - treating as missing"
                )
                quote = None

            quote_present = quote is not None

            # Simulate Fill
            fill_res = TransactionCostModel.simulate_fill(order, quote)
            fill_status = fill_res.get("status", "unknown")
            last_fill_qty = float(fill_res.get("last_fill_qty") or 0.0)

            # Structured log for observability
            logger.info(
                f"paper_order_process: order_id={order_id} prior_status={prior_status} "
                f"symbol={symbol} quote_present={quote_present} fill_status={fill_status} "
                f"last_fill_qty={last_fill_qty}"
            )

            # Record diagnostic for this order
            diagnostic = {
                "order_id": order_id,
                "symbol": symbol,
                "fill_status": fill_status,
                "quote_present": quote_present,
                "last_fill_qty": last_fill_qty,
            }
            result["diagnostics"].append(diagnostic)

            # B) Handle no-quote fills:
            # When no live quote is available, simulate_fill() uses TCM
            # precomputed values (fill_probability + expected_fill_price from
            # the staging quote). Allow these fills when the price is reasonable
            # (came from staging quote or limit price). Block only the $1.00
            # last-resort fallback that would corrupt P&L.
            if not quote_present and fill_status in ("partial", "filled") and last_fill_qty > 0:
                fill_price = float(fill_res.get("last_fill_price") or 0)
                is_tcm_fallback = fill_res.get("reason") == "missing_quote_fallback"

                if is_tcm_fallback and fill_price > 1.01:
                    # TCM price from staging quote or limit price — safe to fill
                    logger.info(
                        f"paper_order_fill_tcm_fallback: order_id={order_id} symbol={symbol} "
                        f"fill_price={fill_price} source={fill_res.get('fallback_source')} — "
                        f"no live quote, using TCM precomputed price"
                    )
                    diagnostic["fill_source"] = "tcm_fallback"
                    # Fall through to normal commit below
                else:
                    # $1.00 last-resort or unknown source — refuse and wait
                    logger.warning(
                        f"paper_order_skip_no_quote: order_id={order_id} symbol={symbol} "
                        f"fill_price={fill_price} fill_status={fill_status} — "
                        f"refusing to fill without valid quote or reasonable TCM price"
                    )
                    if prior_status == "staged":
                        now_iso = datetime.now(timezone.utc).isoformat()
                        supabase.table("paper_orders").update({
                            "status": "working",
                            "submitted_at": now_iso,
                        }).eq("id", order["id"]).execute()
                        logger.info(f"paper_order_transition: order_id={order_id} staged->working (no-quote skip)")
                    diagnostic["skipped_reason"] = "no_valid_quote_or_tcm"
                    continue

            # Commit only when a NEW fill happened this tick
            should_commit = False

            # Must be in a valid fill state AND have new quantity
            if fill_status in ("partial", "filled") and last_fill_qty > 0:
                should_commit = True

            if should_commit:
                # Commit Fill
                _commit_fill(supabase, analytics, user_id, order, fill_res, quote, p_map[order["portfolio_id"]])
                result["processed"] += 1
                logger.info(
                    f"paper_order_filled: order_id={order_id} fill_status={fill_status} "
                    f"last_fill_qty={last_fill_qty}"
                )

            elif fill_status == "working":
                # Transition staged -> working
                if prior_status == "staged":
                    now_iso = datetime.now(timezone.utc).isoformat()
                    supabase.table("paper_orders").update({
                        "status": "working",
                        "submitted_at": now_iso,
                    }).eq("id", order["id"]).execute()
                    logger.info(f"paper_order_transition: order_id={order_id} staged->working")

            else:
                # Unexpected fill_status (e.g., "unknown", "rejected", etc.)
                # Don't let orders stall in 'staged' forever - transition to 'working'
                if prior_status == "staged":
                    now_iso = datetime.now(timezone.utc).isoformat()
                    supabase.table("paper_orders").update({
                        "status": "working",
                        "submitted_at": now_iso,
                    }).eq("id", order["id"]).execute()
                    logger.warning(
                        f"paper_order_unexpected_status: order_id={order_id} fill_status={fill_status} "
                        f"quote_present={quote_present} - forcing staged->working"
                    )

                # Record diagnostic error for unexpected status
                result["errors"].append({
                    "order_id": order_id,
                    "symbol": symbol,
                    "fill_status": fill_status,
                    "quote_present": quote_present,
                    "reason": "unexpected_fill_status",
                })

        except Exception as e:
            logger.error(
                f"paper_order_error: order_id={order_id} prior_status={prior_status} error={e}"
            )
            result["errors"].append({"order_id": order_id, "error": str(e)})

    return result


def _repair_filled_order_commit(supabase, analytics, user_id, order, portfolio) -> Dict[str, Any]:
    """
    Repair an orphan filled order that has no position_id.

    This handles orders that were filled but whose commit failed (e.g., due to
    user_id NOT NULL constraint issues). Creates the position and ledger entry
    that should have been created during the original fill.

    Args:
        supabase: Supabase client
        analytics: Analytics service
        user_id: User ID for the order
        order: The orphan filled order dict
        portfolio: Portfolio dict with id and cash_balance

    Returns:
        Dict with repair results:
        - repaired: bool indicating success
        - position_id: ID of created/found position
        - ledger_inserted: bool indicating if ledger row was inserted
    """
    result = {"repaired": False, "position_id": None, "ledger_inserted": False}

    try:
        order_id = order.get("id")
        ticket = order.get("order_json", {})
        symbol = ticket.get("symbol")
        side = order.get("side", "buy")

        filled_qty = float(order.get("filled_qty") or 0)
        avg_fill_price = float(order.get("avg_fill_price") or 0)
        fees_usd = float(order.get("fees_usd") or 0)

        if filled_qty <= 0 or avg_fill_price <= 0:
            logger.warning(f"paper_order_repair_skip: order_id={order_id} invalid filled_qty or avg_fill_price")
            return result

        # Derive strategy key
        try:
            strategy_key = _derive_strategy_key(TradeTicket(**ticket))
        except Exception as e:
            logger.warning(f"paper_order_repair_strategy_key_error: order_id={order_id} error={e}")
            strategy_key = f"{symbol}_custom"

        # Signed quantity: Buy adds (+), Sell subtracts (-)
        fill_sign = 1.0 if side == "buy" else -1.0
        signed_qty = filled_qty * fill_sign

        # 1. Create or find position
        # Try to find existing open position by strategy key first
        pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio["id"]).eq("strategy_key", strategy_key).eq("status", "open").execute()
        pos = pos_res.data[0] if pos_res.data else None

        if pos:
            # Position exists - update it with the filled order's data
            current_qty = float(pos["quantity"])
            current_avg = float(pos["avg_entry_price"])

            new_qty = current_qty + signed_qty

            # Calculate new average price (weighted average for increasing exposure)
            new_avg = current_avg
            if (current_qty >= 0 and signed_qty > 0) or (current_qty <= 0 and signed_qty < 0):
                total_cost = (abs(current_qty) * current_avg) + (abs(signed_qty) * avg_fill_price)
                if abs(new_qty) > 0:
                    new_avg = total_cost / abs(new_qty)

            # Handle flip case
            if (current_qty > 0 and new_qty < 0) or (current_qty < 0 and new_qty > 0):
                new_avg = avg_fill_price

            now = datetime.now(timezone.utc).isoformat()

            if new_qty == 0:
                # Closed completely — mark closed instead of deleting
                multiplier = 100.0
                entry_price = float(pos.get("avg_entry_price") or 0)
                closed_qty = abs(current_qty)
                if current_qty > 0:
                    realized_pl = (avg_fill_price - entry_price) * closed_qty * multiplier
                else:
                    realized_pl = (entry_price - avg_fill_price) * closed_qty * multiplier

                supabase.table("paper_positions").update({
                    "quantity": 0,
                    "status": "closed",
                    "closed_at": now,
                    "realized_pl": realized_pl,
                    "updated_at": now,
                }).eq("id", pos["id"]).execute()
                result["position_id"] = pos["id"]
            else:
                supabase.table("paper_positions").update({
                    "quantity": new_qty,
                    "avg_entry_price": new_avg,
                    "updated_at": now
                }).eq("id", pos["id"]).execute()
                result["position_id"] = pos["id"]

            # Update order with position_id
            supabase.table("paper_orders").update({"position_id": pos["id"]}).eq("id", order_id).execute()

        else:
            # Create new position
            legs_list = ticket.get("legs", [])
            max_credit = avg_fill_price
            nearest_expiry = None
            try:
                expiry_dates = []
                for leg in legs_list:
                    if isinstance(leg, dict):
                        exp = leg.get("expiry") or leg.get("expiration")
                        if exp:
                            expiry_dates.append(str(exp)[:10])
                if expiry_dates:
                    nearest_expiry = min(expiry_dates)
            except Exception:
                pass

            pos_payload = {
                "portfolio_id": portfolio["id"],
                "user_id": user_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "quantity": signed_qty,
                "avg_entry_price": avg_fill_price,
                "current_mark": avg_fill_price,
                "unrealized_pl": 0.0,
                "legs": legs_list,
                "max_credit": max_credit,
                "nearest_expiry": nearest_expiry,
                "status": "open",
                "trace_id": order.get("trace_id"),
                "suggestion_id": order.get("suggestion_id")
            }

            # Enrich with model metadata from suggestion if available
            if order.get("suggestion_id"):
                try:
                    s_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select(
                        "model_version, features_hash, strategy, window, regime"
                    ).eq("id", order.get("suggestion_id")).single().execute()
                    if s_res.data:
                        pos_payload.update(s_res.data)
                except Exception as e:
                    logger.warning(f"paper_order_repair_suggestion_error: order_id={order_id} error={e}")

            new_pos = supabase.table("paper_positions").insert(pos_payload).execute()

            if new_pos.data:
                new_pos_id = new_pos.data[0]["id"]
                result["position_id"] = new_pos_id
                # Update order with position_id
                supabase.table("paper_orders").update({"position_id": new_pos_id}).eq("id", order_id).execute()

        # 2. Insert ledger entry only if one doesn't exist for this order_id
        existing_ledger = supabase.table("paper_ledger").select("id").eq("order_id", order_id).execute()

        if not existing_ledger.data:
            # Calculate cash delta for ledger
            multiplier = 100.0
            txn_value = filled_qty * avg_fill_price * multiplier

            if side == "buy":
                cash_delta = -(txn_value + fees_usd)
            else:
                cash_delta = txn_value - fees_usd

            # Get current cash balance for balance_after calculation
            current_cash = float(portfolio.get("cash_balance") or 0)
            # Note: For repair, we don't update cash balance since this was already accounted for
            # We just record the ledger entry for audit purposes

            ledger = PaperLedgerService(supabase)
            ledger.emit_fill(
                portfolio_id=portfolio["id"],
                amount=cash_delta,
                balance_after=current_cash,  # Current balance (repair doesn't change cash)
                order_id=order_id,
                position_id=result["position_id"],
                trace_id=order.get("trace_id"),
                user_id=user_id,
                metadata={
                    "side": side,
                    "qty": filled_qty,
                    "price": avg_fill_price,
                    "symbol": symbol,
                    "fees": fees_usd,
                    "repair": True,  # Mark as repair entry
                }
            )
            result["ledger_inserted"] = True

        result["repaired"] = True
        logger.info(
            f"paper_order_repair_success: order_id={order_id} position_id={result['position_id']} "
            f"ledger_inserted={result['ledger_inserted']}"
        )

    except Exception as e:
        logger.error(f"paper_order_repair_error: order_id={order.get('id')} error={e}")
        result["error"] = str(e)

    return result


def _commit_fill(supabase, analytics, user_id, order, fill_res, quote, portfolio):
    # D) Use helper to compute deltas
    deltas = _compute_fill_deltas(order, fill_res)

    this_fill_qty = deltas["this_fill_qty"]
    this_fill_price = deltas["this_fill_price"]

    new_total_filled_qty = deltas["new_total_filled_qty"]
    new_avg_fill_price = deltas["new_avg_fill_price"]

    fees_total = deltas["fees_total"]
    fees_delta = deltas["fees_delta"]

    now = datetime.now(timezone.utc).isoformat()

    # 1. Update Order with CUMULATIVE totals
    # BUT write the order row using cumulative totals
    update_payload = {
        "status": fill_res["status"],
        "filled_qty": new_total_filled_qty,
        "avg_fill_price": new_avg_fill_price,
        "fees_usd": fees_total,
        "filled_at": now,
        "quote_at_fill": quote
    }

    supabase.table("paper_orders").update(update_payload).eq("id", order["id"]).execute()

    # 2. Update Portfolio & Position with INCREMENTAL deltas
    side = order.get("side", "buy")
    multiplier = 100.0

    # Cash Delta uses incremental qty and price + incremental fees
    txn_value = this_fill_qty * this_fill_price * multiplier

    # Cash Impact:
    # Buy: - (Price * Qty) - Fees
    # Sell: + (Price * Qty) - Fees

    cash_delta = 0.0
    if side == "buy":
        cash_delta = -(txn_value + fees_delta)
    else:
        cash_delta = (txn_value - fees_delta)

    # Use fresh cash from portfolio object (which we assume is up to date or we fetch)
    # In _process loop we pass p_map[id], let's trust it but verify
    current_cash = float(portfolio["cash_balance"])
    new_cash = current_cash + cash_delta

    # Update DB
    supabase.table("paper_portfolios").update({"cash_balance": new_cash}).eq("id", portfolio["id"]).execute()

    # Update in-memory portfolio object for subsequent fills in same loop
    portfolio["cash_balance"] = new_cash

    # Ledger uses incremental - Phase 2.1: Structured events
    ticket = order.get("order_json", {})
    symbol = ticket.get("symbol", "UNKNOWN")

    ledger = PaperLedgerService(supabase)

    # Determine event type based on fill status
    is_partial = fill_res["status"] == "partial"
    event_type = PaperLedgerEventType.PARTIAL_FILL if is_partial else PaperLedgerEventType.FILL

    fill_metadata = {
        "side": side,
        "qty": this_fill_qty,
        "price": this_fill_price,
        "symbol": symbol,
        "fees": fees_delta,
        "filled_so_far": new_total_filled_qty,
        "total_qty": float(order.get("requested_qty") or 0),
        "order_status": fill_res["status"]
    }

    if is_partial:
        ledger.emit_partial_fill(
            portfolio_id=portfolio["id"],
            amount=cash_delta,
            balance_after=new_cash,
            order_id=order.get("id"),
            position_id=order.get("position_id"),
            trace_id=order.get("trace_id"),
            user_id=user_id,
            metadata=fill_metadata
        )
    else:
        ledger.emit_fill(
            portfolio_id=portfolio["id"],
            amount=cash_delta,
            balance_after=new_cash,
            order_id=order.get("id"),
            position_id=order.get("position_id"),
            trace_id=order.get("trace_id"),
            user_id=user_id,
            metadata=fill_metadata
        )

    # Position Logic — wrapped in try/except to prevent orphan filled orders
    # (Bug 5 fix: if position creation fails, roll back order to 'working')
    pos_id = order.get("position_id")
    ticket = order.get("order_json", {})
    symbol = ticket.get("symbol")

    # Derive strategy key with fallback (matches _repair_filled_order_commit behavior)
    try:
        strategy_key = _derive_strategy_key(TradeTicket(**ticket))
    except Exception as e:
        logger.warning(
            f"paper_commit_fill_strategy_key_error: order_id={order.get('id')} error={e} — "
            f"falling back to {symbol}_custom"
        )
        strategy_key = f"{symbol}_custom"

    # Signed Quantity logic
    # Buy adds (+), Sell subtracts (-)
    fill_sign = 1.0 if side == "buy" else -1.0
    signed_incremental_qty = this_fill_qty * fill_sign

    # Bug 5 fix: Wrap position creation in try/except.
    # If position creation fails AFTER order is already marked 'filled',
    # roll back order to 'working' so orphan repair or next cycle can retry.
    try:
        # Locate or create position
        if pos_id:
            pos_res = supabase.table("paper_positions").select("*").eq("id", pos_id).single().execute()
            pos = pos_res.data
        else:
            # Opening logic fallback: try to find by strategy key (open positions only)
            pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio["id"]).eq("strategy_key", strategy_key).eq("status", "open").execute()
            pos = pos_res.data[0] if pos_res.data else None

        if pos:
            # Update existing
            current_qty = float(pos["quantity"]) # Signed
            current_avg = float(pos["avg_entry_price"])

            new_qty = current_qty + signed_incremental_qty

            # Average Price Logic
            # Only update avg price if we are increasing exposure in the same direction
            # Or flipping direction.

            new_avg = current_avg

            # Case 1: Increasing exposure (Same sign)
            if (current_qty >= 0 and signed_incremental_qty > 0) or (current_qty <= 0 and signed_incremental_qty < 0):
                # Weighted average of OLD total vs NEW incremental
                total_cost = (abs(current_qty) * current_avg) + (abs(signed_incremental_qty) * this_fill_price)
                if abs(new_qty) > 0:
                    new_avg = total_cost / abs(new_qty)

            # Case 2: Reducing exposure (Opposite sign, no flip)
            # Avg price stays same (LIFO/FIFO agnostic for avg cost)

            # Case 3: Flip (Crossed zero)
            # e.g. +5 to -5.
            if (current_qty > 0 and new_qty < 0) or (current_qty < 0 and new_qty > 0):
                # The portion that flipped is new_qty.
                # The cost basis for that portion is this_fill_price.
                # Simplified: if we flip, new avg is the fill price of the flip.
                new_avg = this_fill_price

            if new_qty == 0:
                # Closed completely
                attribution_ok = True
                if pos_id: # Was explicit close
                     # E) Attribution invocation should use UPDATED cumulative order values
                     # Merge update_payload into order to get cumulative values
                     order_updated = {**order, **update_payload}
                     # Pass fees_total (cumulative), not delta
                     try:
                         _run_attribution(supabase, user_id, order_updated, pos, new_avg_fill_price, fees_total, side)
                     except Exception as e:
                         attribution_ok = False
                         logging.warning(f"Attribution failed for order {order.get('id')}; position preserved for retry: {e}")

                # Mark position closed instead of deleting it.
                # realized_pl: long positions profit when exit > entry,
                # short (credit) positions profit when entry > exit.
                entry_price = float(pos.get("avg_entry_price") or 0)
                exit_price = this_fill_price
                closed_qty = abs(current_qty)
                if current_qty > 0:
                    realized_pl = (exit_price - entry_price) * closed_qty * multiplier
                else:
                    realized_pl = (entry_price - exit_price) * closed_qty * multiplier
                realized_pl -= fees_delta  # subtract closing fees

                if attribution_ok:
                    supabase.table("paper_positions").update({
                        "quantity": 0,
                        "status": "closed",
                        "closed_at": now,
                        "realized_pl": realized_pl,
                        "updated_at": now,
                    }).eq("id", pos["id"]).execute()
                else:
                    logging.warning(f"Position {pos['id']} retained — will retry close on next auto_close cycle")
            else:
                # Update
                supabase.table("paper_positions").update({
                    "quantity": new_qty,
                    "avg_entry_price": new_avg,
                    "updated_at": now
                }).eq("id", pos["id"]).execute()

        else:
            # Create new position
            # signed_incremental_qty is the quantity
            # Compute max_credit and nearest_expiry from legs for exit evaluation
            legs_list = ticket.get("legs", [])
            max_credit = this_fill_price  # For credit strategies, entry price ≈ credit received
            nearest_expiry = None
            try:
                expiry_dates = []
                for leg in legs_list:
                    if isinstance(leg, dict):
                        exp = leg.get("expiry") or leg.get("expiration")
                        if exp:
                            expiry_dates.append(str(exp)[:10])  # YYYY-MM-DD
                if expiry_dates:
                    nearest_expiry = min(expiry_dates)
            except Exception:
                pass  # Non-critical — exit evaluator can still use DTE from order

            pos_payload = {
                "portfolio_id": portfolio["id"],
                "user_id": user_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "quantity": signed_incremental_qty,
                "avg_entry_price": this_fill_price,
                "current_mark": this_fill_price,
                "unrealized_pl": 0.0,
                "legs": legs_list,
                "max_credit": max_credit,
                "nearest_expiry": nearest_expiry,
                "status": "open",
                # Linkage
                "trace_id": order.get("trace_id"),
                "suggestion_id": order.get("suggestion_id")
            }

            # Enrich with model metadata from suggestion if available
            if order.get("suggestion_id"):
                try:
                    s_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("model_version, features_hash, strategy, window, regime").eq("id", order.get("suggestion_id")).single().execute()
                    if s_res.data:
                        pos_payload.update(s_res.data)
                except Exception as e:
                    logging.warning(f"Failed to fetch suggestion metadata for position: {e}")

            new_pos = supabase.table("paper_positions").insert(pos_payload).execute()

            # Update order with the new position_id
            if new_pos.data:
                new_pos_id = new_pos.data[0]["id"]
                supabase.table("paper_orders").update({"position_id": new_pos_id}).eq("id", order["id"]).execute()

    except Exception as pos_err:
        # Position creation/update failed — roll back order to 'working' so it can be retried
        logger.error(
            f"paper_commit_fill_position_failed: order_id={order.get('id')} "
            f"symbol={symbol} error={pos_err} — rolling back order to 'working'"
        )
        try:
            supabase.table("paper_orders").update({
                "status": "working",
                "filled_qty": 0,
                "avg_fill_price": 0,
            }).eq("id", order["id"]).execute()
        except Exception as rollback_err:
            logger.error(
                f"paper_commit_fill_rollback_failed: order_id={order.get('id')} "
                f"error={rollback_err}"
            )
        return  # Skip telemetry — fill didn't fully commit

    # Defensive: ensure the order record is definitively marked filled after
    # successful position commit. The initial update_payload (line above) already
    # sets status from fill_res, but if any intermediate update (e.g., position_id
    # write) partially failed or a race condition occurred, this ensures consistency.
    try:
        supabase.table("paper_orders").update({
            "status": "filled",
            "avg_fill_price": new_avg_fill_price,
            "filled_qty": new_total_filled_qty,
            "filled_at": now,
        }).eq("id", order["id"]).execute()
    except Exception as status_err:
        logger.error(
            f"paper_commit_fill_status_update_failed: order_id={order.get('id')} "
            f"error={status_err} — order may be stuck in prior status"
        )

    fill_source = "live_quote" if quote else "tcm_fallback"
    logger.info(
        f"paper_order_filled: order_id={order.get('id')} fill_price={new_avg_fill_price} "
        f"filled_qty={new_total_filled_qty} source={fill_source}"
    )

    # Telemetry
    emit_trade_event(analytics, user_id, TradeContext(trace_id=order.get("trace_id")), "order_filled", is_paper=True, properties={"order_id": order["id"]})


def _run_attribution(supabase, user_id, order, position, exit_fill, fees, side):
    """
    Computes PnL attribution and logs to learning_feedback_loops
    """
    try:
        entry_price = float(position["avg_entry_price"])
        quantity = float(order["filled_qty"])

        # Need "Mid" prices for attribution
        # Entry Mid: hard to get if we didn't store it on position.
        # Approximation: entry_price (assuming we paid close to mid or spread cost was burned).
        # Better: if we stored quote_at_fill in the opening order!
        # But we don't have easy link to opening order.
        # Fallback: Use entry_price as entry_mid.
        entry_mid = entry_price

        # Exit Mid
        quote_at_exit = order.get("quote_at_fill") or {}
        bid = quote_at_exit.get("bid_price", 0)
        ask = quote_at_exit.get("ask_price", 0)
        exit_mid = (bid + ask) / 2.0 if (bid and ask) else exit_fill

        attr = PnlAttribution.compute(
            entry_mid=entry_mid,
            entry_fill=entry_price,
            exit_mid=exit_mid,
            exit_fill=exit_fill,
            quantity=quantity,
            fees_total=fees,
            direction="long" if side == "sell" else "short" # We are closing. If selling, we were long.
        )

        # Insert LFL
        trace_id = order.get("trace_id")
        suggestion_id = order.get("suggestion_id")

        reason_codes = []
        if not suggestion_id:
            reason_codes.append("missing_suggestion_link")
        if entry_price == entry_mid:
            reason_codes.append("fallback_entry_mid_used")
        if not quote_at_exit:
            reason_codes.append("missing_quote_at_exit")

        payload = {
            "user_id": user_id,
            "trace_id": trace_id,
            "suggestion_id": suggestion_id,
            "execution_id": order.get("id"),
            "is_paper": True,
            "pnl_realized": attr["pnl_total"],
            "pnl_alpha": attr["pnl_alpha"],
            "pnl_execution_drag": attr["pnl_execution_drag"],
            "fees_total": attr["fees_total"],
            "entry_mid": entry_mid,
            "entry_fill": entry_price,
            "exit_mid": exit_mid,
            "exit_fill": exit_fill,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "outcome_type": "trade_closed",
            "details_json": {"reason_codes": reason_codes, "is_paper": True}
        }

        # Enrich from suggestion
        agent_signals_snapshot = {}
        if suggestion_id:
            try:
                s_res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("ev, model_version, features_hash, strategy, window, regime, agent_signals, sizing_metadata").eq("id", suggestion_id).single().execute()
                if s_res.data:
                    data = s_res.data
                    payload["pnl_predicted"] = data.get("ev")
                    payload["model_version"] = data.get("model_version")
                    payload["features_hash"] = data.get("features_hash")
                    payload["strategy"] = data.get("strategy")
                    payload["window"] = data.get("window")
                    payload["regime"] = data.get("regime")
                    agent_signals_snapshot = data.get("agent_signals") or {}
                    _sm = data.get("sizing_metadata") or {}
                    if _sm.get("strategy_track"):
                        payload["details_json"]["strategy_track"] = _sm["strategy_track"]
            except Exception as e:
                logging.warning(f"Failed to fetch suggestion data for LFL: {e}")

        # Fallback strategy key if not in suggestion
        if "strategy" not in payload:
            strat_key = position.get("strategy_key","")
            if "_" in strat_key:
                payload["strategy"] = strat_key.split("_")[-1]

        # Post Trade Review Agent
        try:
            review_agent = PostTradeReviewAgent()
            review_context = {
                "realized_pnl": attr["pnl_total"],
                "mfe": 0.0, # Proxy: Not tracked in paper_positions yet
                "mae": 0.0, # Proxy: Not tracked in paper_positions yet
                "agent_signals": agent_signals_snapshot,
                "strategy": payload.get("strategy"),
                "regime": payload.get("regime"),
                "window": payload.get("window")
            }
            review_signal = review_agent.evaluate(review_context)

            if "details_json" not in payload:
                payload["details_json"] = {}

            payload["details_json"]["post_trade_review"] = review_signal.model_dump(mode="json")
        except Exception as e:
            logging.warning(f"PostTradeReviewAgent failed: {e}")
            if "details_json" not in payload:
                payload["details_json"] = {}
            payload["details_json"]["post_trade_review_error"] = str(e)

        supabase.table("learning_feedback_loops").insert(payload).execute()

    except Exception as e:
        logging.error(f"Attribution failed: {e}")
        raise

@router.post("/paper/reset")
def reset_paper_portfolio(
    user_id: str = Depends(get_current_user),
):
    """
    Reset paper portfolio to initial state.

    v4-L1F: Baseline consistency - uses paper_baseline_capital from v3_go_live_state
    if present, otherwise defaults to 100000. This ensures consistency between:
    - paper portfolio reset
    - paper execution ledger
    - validation baseline used for return calculations
    """
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # v4-L1F: Read baseline from v3_go_live_state if present, otherwise use 100000
    baseline_capital = 100000.0
    try:
        state_res = supabase.table("v3_go_live_state").select("paper_baseline_capital").eq("user_id", user_id).limit(1).execute()
        if state_res.data and state_res.data[0].get("paper_baseline_capital"):
            baseline_capital = float(state_res.data[0]["paper_baseline_capital"])
    except Exception as e:
        logging.warning(f"Failed to read baseline capital from state, using default: {e}")

    port_res = supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
    portfolio_ids = [p["id"] for p in port_res.data] if port_res.data else []

    if portfolio_ids:
        supabase.table("paper_orders").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_positions").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_ledger").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_portfolios").delete().in_("id", portfolio_ids).execute()

    new_port = supabase.table("paper_portfolios").insert({
        "user_id": user_id,
        "name": "Main Paper",
        "cash_balance": baseline_capital,
        "net_liq": baseline_capital
    }).execute()

    if not new_port.data:
        raise HTTPException(status_code=500, detail="Failed to recreate paper portfolio")

    return {
        "status": "reset",
        "portfolio": new_port.data[0],
        "baseline_capital": baseline_capital
    }
@router.get("/paper/portfolio")
def get_paper_portfolio(
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # Fetch paper_portfolios for user (limit 1 for v1)
    port_res = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).limit(1).execute()
    if not port_res.data:
        # Check if we should auto-create, or return empty
        return {"portfolio": None, "positions": [], "stats": {}}

    portfolio = port_res.data[0]
    portfolio_id = portfolio["id"]

    # Fetch open positions only for stats (closed positions are preserved for history)
    pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).eq("status", "open").execute()
    positions = pos_res.data if pos_res.data else []

    # Aggregate basic stats
    total_unrealized_pl = sum([float(p.get("unrealized_pl", 0) or 0) for p in positions])
    open_positions_count = len(positions)

    # Calculate benchmarks
    spy_return_pct = 0.0
    zero_strategy_return_pct = 0.0

    created_at_str = portfolio.get("created_at")
    if created_at_str:
        try:
            start_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            days_elapsed = (now_dt - start_dt).days

            # 1. Zero Strategy (Risk Free): 4.5% annualized
            zero_strategy_return_pct = (0.045 / 365.0) * days_elapsed * 100

            # 2. SPY Benchmark
            try:
                poly = PolygonService()
                current_spy = poly.get_recent_quote("SPY") or {}

                bid = float(current_spy.get("bid_price") or current_spy.get("bid") or 0.0)
                ask = float(current_spy.get("ask_price") or current_spy.get("ask") or 0.0)

                # Prefer explicit midpoint if provided by the service; otherwise compute from bid/ask.
                current_price = float(
                    current_spy.get("price")
                    or ((bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0)
                )

                if current_price > 0:
                    start_date_str = start_dt.strftime("%Y-%m-%d")

                    # Pull a small window ending shortly AFTER the portfolio start date so we can
                    # pick the first trading day on/after start_date_str (handles weekends/holidays).
                    hist = poly.get_historical_prices(
                        "SPY",
                        days=10,
                        to_date=start_dt + timedelta(days=7),
                    )

                    dates = (hist or {}).get("dates") or []
                    prices = (hist or {}).get("prices") or []

                    start_price = 0.0
                    for d, p in zip(dates, prices):
                        if d >= start_date_str:
                            try:
                                start_price = float(p or 0.0)
                            except Exception:
                                start_price = 0.0
                            break

                    if start_price > 0:
                        spy_return_pct = ((current_price - start_price) / start_price) * 100.0

            except Exception as e:
                logging.warning(f"Failed to calc SPY benchmark: {e}")

        except Exception as e:
             logging.error(f"Benchmark calculation error: {e}")


    return {
        "portfolio": portfolio,
        "positions": positions,
        "stats": {
            "total_unrealized_pl": total_unrealized_pl,
            "open_positions_count": open_positions_count,
            "spy_return_pct": round(spy_return_pct, 4),
            "zero_strategy_return_pct": round(zero_strategy_return_pct, 4)
        }
    }


@router.get("/pdt/status")
def pdt_status_endpoint(
    user_id: str = Depends(get_current_user),
):
    """
    Current PDT (Pattern Day Trader) day trade status.

    Returns day trades used/remaining in the rolling 5-business-day window,
    and count of same-day positions currently open.
    """
    from packages.quantum.services.pdt_guard_service import (
        is_pdt_enabled, get_pdt_status, is_same_day_close, _chicago_today,
    )

    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    pdt_on = is_pdt_enabled()
    status = get_pdt_status(supabase, user_id)

    # Count same-day positions currently open
    same_day_count = 0
    today_chicago = _chicago_today()
    try:
        port_res = supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
        p_ids = [p["id"] for p in (port_res.data or [])]
        if p_ids:
            pos_res = supabase.table("paper_positions").select("id, created_at") \
                .in_("portfolio_id", p_ids).eq("status", "open").execute()
            for p in (pos_res.data or []):
                if is_same_day_close(p, today_chicago):
                    same_day_count += 1
    except Exception as e:
        logger.warning(f"pdt_status_positions_error: {e}")

    return {
        "enabled": pdt_on,
        "day_trades_used": status["day_trades_used"],
        "day_trades_remaining": status["day_trades_remaining"],
        "max_day_trades": status["max_day_trades"],
        "window": status["window_dates"],
        "same_day_positions_open": same_day_count,
        "at_limit": status["at_limit"],
    }
