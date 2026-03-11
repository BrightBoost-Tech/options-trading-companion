"""
Paper Exit Evaluator

Replaces the blanket EOD force-close with condition-based exits.
Checks open positions against exit conditions and closes only those that trigger.

Exit conditions (checked in order — first match triggers close):
1. target_profit: Captured >= 50% of max credit
2. stop_loss: Loss exceeds 2x the credit received
3. dte_threshold: 7 DTE or less (gamma risk)
4. expiration_day: Expires today — must close

Schedule: 3:00 PM CDT (before mark-to-market at 3:30 PM).
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, Any, List, Tuple, Optional, Callable

logger = logging.getLogger(__name__)


def days_to_expiry(position: Dict[str, Any]) -> int:
    """
    Compute days to expiration from position's nearest_expiry or legs.

    Returns large number (999) if no expiry information available,
    so the position won't be falsely triggered by DTE conditions.
    """
    # 1. Try nearest_expiry column (set at position creation)
    nearest = position.get("nearest_expiry")
    if nearest:
        try:
            if isinstance(nearest, str):
                exp_date = date.fromisoformat(nearest[:10])
            elif isinstance(nearest, date):
                exp_date = nearest
            else:
                exp_date = None

            if exp_date:
                return (exp_date - date.today()).days
        except (ValueError, TypeError):
            pass

    # 2. Fallback: scan legs for earliest expiry
    legs = position.get("legs") or []
    expiry_dates = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        exp = leg.get("expiry") or leg.get("expiration")
        if exp:
            try:
                expiry_dates.append(date.fromisoformat(str(exp)[:10]))
            except (ValueError, TypeError):
                continue

    if expiry_dates:
        nearest_date = min(expiry_dates)
        return (nearest_date - date.today()).days

    return 999  # No expiry info — don't trigger DTE conditions


# ---------------------------------------------------------------------------
# Exit condition definitions
# ---------------------------------------------------------------------------

EXIT_CONDITIONS: Dict[str, Dict[str, Any]] = {
    "target_profit": {
        "description": "Position has reached target profit percentage",
        "check": lambda pos: (
            pos.get("max_credit") is not None
            and pos["max_credit"] > 0
            and float(pos.get("unrealized_pl") or 0) >= float(pos["max_credit"]) * 100 * 0.50
        ),
    },
    "stop_loss": {
        "description": "Position has exceeded maximum acceptable loss",
        "check": lambda pos: (
            pos.get("max_credit") is not None
            and pos["max_credit"] > 0
            and float(pos.get("unrealized_pl") or 0) <= -(float(pos["max_credit"]) * 100 * 2.0)
        ),
    },
    "dte_threshold": {
        "description": "Position is too close to expiration (gamma risk)",
        "check": lambda pos: 0 < days_to_expiry(pos) <= 7,
    },
    "expiration_day": {
        "description": "Position expires today — must close",
        "check": lambda pos: days_to_expiry(pos) <= 0,
    },
}


def evaluate_position_exit(position: Dict[str, Any]) -> Optional[str]:
    """
    Check a single position against all exit conditions.

    Returns the name of the first triggered condition, or None if position should hold.
    """
    pos_id = position.get("id", "?")
    symbol = position.get("symbol", "?")
    max_credit = position.get("max_credit")
    unrealized_pl = position.get("unrealized_pl")
    nearest_expiry = position.get("nearest_expiry")
    qty = position.get("quantity")
    dte = days_to_expiry(position)

    fields_msg = (
        f"[EXIT_EVAL_DEBUG] position={pos_id} symbol={symbol} "
        f"qty={qty} max_credit={max_credit} (type={type(max_credit).__name__}) "
        f"unrealized_pl={unrealized_pl} (type={type(unrealized_pl).__name__}) "
        f"nearest_expiry={nearest_expiry} dte={dte}"
    )
    logger.info(fields_msg)
    print(fields_msg, flush=True)

    # Log threshold computations if max_credit is available
    if max_credit is not None:
        try:
            mc = float(max_credit)
            upl = float(unrealized_pl or 0)
            tp_threshold = mc * 100 * 0.50
            sl_threshold = -(mc * 100 * 2.0)
            thresh_msg = (
                f"[EXIT_EVAL_DEBUG] position={pos_id} "
                f"target_profit: {upl} >= {tp_threshold} ? {upl >= tp_threshold} | "
                f"stop_loss: {upl} <= {sl_threshold} ? {upl <= sl_threshold} | "
                f"dte_threshold: 0 < {dte} <= 7 ? {0 < dte <= 7} | "
                f"expiration_day: {dte} <= 0 ? {dte <= 0}"
            )
            logger.info(thresh_msg)
            print(thresh_msg, flush=True)
        except (TypeError, ValueError) as e:
            logger.warning(f"[EXIT_EVAL_DEBUG] position={pos_id} threshold calc error: {e}")
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} threshold calc error: {e}", flush=True)
    else:
        print(f"[EXIT_EVAL_DEBUG] position={pos_id} max_credit is None — skipping P&L conditions", flush=True)

    for condition_name, condition in EXIT_CONDITIONS.items():
        try:
            result = condition["check"](position)
            logger.info(
                f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} result={result}"
            )
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} result={result}", flush=True)
            if result:
                return condition_name
        except Exception as e:
            logger.warning(
                f"Exit condition '{condition_name}' error for position "
                f"{position.get('id')}: {e}"
            )
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} ERROR: {e}", flush=True)
    return None


class PaperExitEvaluator:
    """Evaluates open positions against exit conditions and closes triggered ones."""

    def __init__(self, supabase_client):
        self.client = supabase_client

    def evaluate_exits(self, user_id: str) -> Dict[str, Any]:
        """
        Check all open positions against exit conditions. Close those that trigger.

        Returns summary with closes, holds, and close_reasons breakdown.
        """
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        print(f"[EXIT_EVAL_DEBUG] evaluate_exits called for user={user_id}", flush=True)

        # 1. Refresh marks first so unrealized_pl is current
        mtm = PaperMarkToMarketService(self.client)
        mtm_result = mtm.refresh_marks(user_id)
        logger.info(f"[EXIT_EVAL_DEBUG] refresh_marks result: {mtm_result}")
        print(f"[EXIT_EVAL_DEBUG] refresh_marks result: {mtm_result}", flush=True)

        # 2. Get enriched open positions
        positions = self._get_open_positions(user_id)
        logger.info(
            f"[EXIT_EVAL_DEBUG] fetched {len(positions)} open positions for user={user_id}"
        )
        print(f"[EXIT_EVAL_DEBUG] fetched {len(positions)} open positions", flush=True)
        for p in positions:
            msg = (
                f"[EXIT_EVAL_DEBUG] position_row: id={p.get('id')} "
                f"symbol={p.get('symbol')} qty={p.get('quantity')} "
                f"avg_entry={p.get('avg_entry_price')} "
                f"max_credit={p.get('max_credit')} "
                f"unrealized_pl={p.get('unrealized_pl')} "
                f"current_mark={p.get('current_mark')} "
                f"nearest_expiry={p.get('nearest_expiry')}"
            )
            logger.info(msg)
            print(msg, flush=True)
        if not positions:
            return {
                "status": "ok",
                "total_open": 0,
                "closing": 0,
                "holding": 0,
                "closes": [],
                "close_reasons": {},
            }

        # 3. Evaluate each position
        closes: List[Dict[str, Any]] = []
        holds: List[Dict[str, Any]] = []

        for position in positions:
            triggered = evaluate_position_exit(position)
            if triggered:
                closes.append({
                    "position_id": position["id"],
                    "symbol": position.get("symbol"),
                    "reason": triggered,
                    "description": EXIT_CONDITIONS[triggered]["description"],
                    "unrealized_pl": float(position.get("unrealized_pl") or 0),
                    "max_credit": float(position.get("max_credit") or 0),
                    "dte": days_to_expiry(position),
                })
            else:
                holds.append(position)

        # 4. Close triggered positions
        closed_results = []
        for close_item in closes:
            try:
                result = self._close_position(
                    user_id,
                    close_item["position_id"],
                    close_item["reason"],
                )
                closed_results.append({**close_item, **result})
            except Exception as e:
                logger.error(
                    f"Failed to close position {close_item['position_id']}: {e}"
                )
                closed_results.append({**close_item, "error": str(e)})

        # 5. Build reason summary
        close_reasons: Dict[str, int] = {}
        for c in closes:
            reason = c["reason"]
            close_reasons[reason] = close_reasons.get(reason, 0) + 1

        logger.info(
            f"exit_evaluation_summary: user_id={user_id} "
            f"total_open={len(positions)} closing={len(closes)} "
            f"holding={len(holds)} reasons={close_reasons}"
        )

        return {
            "status": "ok",
            "total_open": len(positions),
            "closing": len(closes),
            "holding": len(holds),
            "closes": closed_results,
            "close_reasons": close_reasons,
        }

    def _get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all open paper positions for a user."""
        try:
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .execute()

            portfolio_ids = [p["id"] for p in (port_res.data or [])]
            if not portfolio_ids:
                return []

            pos_res = self.client.table("paper_positions") \
                .select("*") \
                .in_("portfolio_id", portfolio_ids) \
                .neq("quantity", 0) \
                .execute()

            return pos_res.data or []
        except Exception as e:
            logger.error(f"Failed to fetch positions for exit eval: {e}")
            return []

    def _close_position(
        self,
        user_id: str,
        position_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Close a single position using the existing paper trading machinery."""
        from packages.quantum.paper_endpoints import (
            _stage_order_internal,
            _process_orders_for_user,
            get_analytics_service,
        )
        from packages.quantum.models import TradeTicket
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )

        supabase = self.client
        analytics = get_analytics_service()

        # Fetch position
        pos_res = supabase.table("paper_positions") \
            .select("*") \
            .eq("id", position_id) \
            .single() \
            .execute()
        position = pos_res.data

        # Resolve OCC symbol
        occ_symbol = PaperAutopilotService._resolve_occ_symbol(position, supabase)

        qty = float(position["quantity"])
        side = "sell" if qty > 0 else "buy"

        ticket = TradeTicket(
            symbol=position["symbol"],
            quantity=abs(qty),
            order_type="market",
            strategy_type="custom",  # Closing order — single market order, not the original multi-leg strategy
            source_engine="paper_exit_evaluator",
            legs=[{"symbol": occ_symbol, "action": side, "quantity": abs(qty)}],
        )

        if position.get("suggestion_id"):
            ticket.source_ref_id = position["suggestion_id"]

        order_id = _stage_order_internal(
            supabase,
            analytics,
            user_id,
            ticket,
            position["portfolio_id"],
            position_id=position_id,
            trace_id_override=position.get("trace_id"),
        )

        process_result = _process_orders_for_user(
            supabase, analytics, user_id, target_order_id=order_id
        )

        # Record close reason on position (best effort — position may already be deleted)
        try:
            supabase.table("paper_positions").update({
                "close_reason": reason,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", position_id).execute()
        except Exception:
            pass  # Position may have been deleted by _commit_fill

        return {
            "order_id": order_id,
            "processed": process_result.get("processed", 0),
        }
