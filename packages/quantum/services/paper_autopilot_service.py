"""
Paper Autopilot Service

Provides automated paper trading execution for Phase-3 streak automation.
- Selects and executes top executable suggestions
- Closes positions based on configurable policy
- Respects pause gate and paper-only mode
- Uses deterministic ordering and deduplication

Runtime Environment Variables:
- PAPER_AUTOPILOT_ENABLED: "1" to enable (default: "0")
- PAPER_AUTOPILOT_MAX_TRADES_PER_DAY: Max trades per day (default: "3")
- PAPER_AUTOPILOT_MIN_SCORE: Minimum score threshold (default: "0.0")
- PAPER_AUTOPILOT_CLOSE_POLICY: "close_all" | "min_one" | "ev_rank" (default: "close_all")
- PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY: Max closes per day (default: "99")
"""

import os
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE

logger = logging.getLogger(__name__)


def _get_config() -> Dict[str, Any]:
    """
    Get autopilot configuration from environment variables.
    Read at runtime to allow dynamic configuration.
    """
    return {
        "enabled": os.environ.get("PAPER_AUTOPILOT_ENABLED", "0") == "1",
        "max_trades_per_day": int(os.environ.get("PAPER_AUTOPILOT_MAX_TRADES_PER_DAY", "3")),
        "min_score": float(os.environ.get("PAPER_AUTOPILOT_MIN_SCORE", "0.0")),
        "close_policy": os.environ.get("PAPER_AUTOPILOT_CLOSE_POLICY", "close_all"),
        "max_closes_per_day": int(os.environ.get("PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY", "99")),
    }


def _compute_today_window() -> Tuple[str, str]:
    """
    Compute UTC today window bounds for deterministic queries.
    Returns (today_start_iso, tomorrow_start_iso).
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    return today_start.isoformat(), tomorrow_start.isoformat()


def _get_utc_date_key() -> str:
    """Get UTC date string for idempotency keys."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class PaperAutopilotService:
    """
    Service for automated paper trading.

    Provides methods for:
    - Selecting executable suggestions
    - Executing top suggestions deterministically
    - Closing positions with configurable policy
    """

    def __init__(self, supabase_client):
        self.client = supabase_client
        self.config = _get_config()

    def is_enabled(self) -> bool:
        """Check if autopilot is enabled via environment."""
        return self.config["enabled"]

    def get_executable_suggestions(
        self,
        user_id: str,
        include_backlog: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch executable (pending) suggestions for a user.

        Uses same logic as inbox: pending status, optionally bounded to today.
        Returns list sorted deterministically by (score desc, created_at asc, id asc).
        """
        today_start, tomorrow_start = _compute_today_window()

        query = self.client.table(TRADE_SUGGESTIONS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("status", "pending")

        if not include_backlog:
            query = query \
                .gte("created_at", today_start) \
                .lt("created_at", tomorrow_start)

        result = query.execute()
        suggestions = result.data or []

        # Deterministic sorting: score desc, created_at asc, id asc
        def sort_key(s):
            score = s.get("score") or s.get("probability_of_profit") or s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            created = s.get("created_at") or ""
            sid = s.get("id") or ""
            return (-score, created, sid)

        suggestions.sort(key=sort_key)
        return suggestions

    def get_already_executed_suggestion_ids_today(self, user_id: str) -> set:
        """
        Get suggestion IDs that already have paper orders staged/executed today.
        Used for deduplication to prevent double-execution.
        """
        today_start, tomorrow_start = _compute_today_window()

        # Query paper_orders for today's orders linked to suggestions
        result = self.client.table("paper_orders") \
            .select("suggestion_id") \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()

        orders = result.data or []
        return {o["suggestion_id"] for o in orders if o.get("suggestion_id")}

    def execute_top_suggestions(
        self,
        user_id: str,
        limit: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute top N executable suggestions for a user.

        Args:
            user_id: Target user
            limit: Max suggestions to execute (default from config)
            min_score: Minimum score threshold (default from config)

        Returns:
            Summary dict with executed_count, skipped_count, errors, etc.
        """
        limit = limit or self.config["max_trades_per_day"]
        min_score = min_score if min_score is not None else self.config["min_score"]

        # Get executable suggestions
        suggestions = self.get_executable_suggestions(user_id, include_backlog=False)

        if not suggestions:
            return {
                "status": "ok",
                "executed_count": 0,
                "skipped_count": 0,
                "reason": "no_candidates",
            }

        # Get already executed to dedupe
        already_executed = self.get_already_executed_suggestion_ids_today(user_id)

        # Filter by min_score and dedupe, tracking skip reasons
        candidates = []
        deduped_count = 0
        below_min_score_count = 0
        for s in suggestions:
            sid = s.get("id")
            if sid in already_executed:
                deduped_count += 1
                continue

            score = s.get("score") or s.get("probability_of_profit") or s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0

            if score >= min_score:
                candidates.append(s)
            else:
                below_min_score_count += 1

        if not candidates:
            return {
                "status": "ok",
                "executed_count": 0,
                "skipped_count": len(suggestions),
                "reason": "no_qualifying_candidates",
            }

        # Take top N
        to_execute = candidates[:limit]

        logger.info(
            f"paper_auto_execute_start: user_id={user_id} "
            f"suggestions_fetched={len(suggestions)} deduped={deduped_count} "
            f"below_min_score={below_min_score_count} candidates={len(candidates)} "
            f"to_execute={len(to_execute)}"
        )

        # Execute using internal staging logic
        from packages.quantum.paper_endpoints import (
            _suggestion_to_ticket,
            _stage_order_internal,
            _process_orders_for_user,
            get_supabase,
            get_analytics_service,
        )

        supabase = self.client
        analytics = get_analytics_service()

        executed = []
        errors = []

        for suggestion in to_execute:
            sid = suggestion.get("id")
            ticker = suggestion.get("ticker", "unknown")
            logger.info(f"paper_auto_execute_processing: suggestion_id={sid} symbol={ticker}")
            try:
                # Convert to ticket
                ticket = _suggestion_to_ticket(suggestion)

                # Stage order
                order_id = _stage_order_internal(
                    supabase,
                    analytics,
                    user_id,
                    ticket,
                    portfolio_id_arg=None,
                    suggestion_id_override=sid
                )

                # Update suggestion status (non-fatal: proceed even if this fails)
                try:
                    supabase.table(TRADE_SUGGESTIONS_TABLE).update({
                        "status": "staged"
                    }).eq("id", sid).execute()
                except Exception as status_err:
                    logger.warning(
                        f"Failed to update suggestion {sid} status to 'staged', "
                        f"proceeding with order processing: {status_err}"
                    )

                # Process order (execute) - always proceed even if status update failed
                process_result = _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

                logger.info(
                    f"paper_auto_execute_order_created: suggestion_id={sid} "
                    f"order_id={order_id} symbol={ticker}"
                )

                executed.append({
                    "suggestion_id": sid,
                    "order_id": order_id,
                    "processed": process_result.get("processed", 0),
                    "processing_errors": process_result.get("errors") or None,
                })

            except Exception as e:
                logger.error(
                    f"paper_auto_execute_error: suggestion_id={sid} "
                    f"symbol={ticker} error={e}"
                )
                errors.append({"suggestion_id": sid, "error": str(e)})

        logger.info(
            f"paper_auto_execute_summary: user_id={user_id} "
            f"orders_created={len(executed)} skipped={len(suggestions) - len(to_execute)} "
            f"errors={len(errors)}"
        )

        # Compute processing summary: count orders that had processing errors
        processing_error_count = sum(
            1 for e in executed if e.get("processing_errors")
        )
        total_processed = sum(e.get("processed", 0) for e in executed)

        # Status: "partial" if staging or processing errors, else "ok"
        has_staging_errors = len(errors) > 0
        has_processing_errors = processing_error_count > 0
        if has_staging_errors or has_processing_errors:
            status = "partial"
        elif executed:
            status = "ok"
        else:
            status = "ok"

        return {
            "status": status,
            "executed_count": len(executed),
            "skipped_count": len(suggestions) - len(to_execute),
            "error_count": len(errors),
            "executed": executed,
            "errors": errors if errors else None,
            "processed_summary": {
                "total_processed": total_processed,
                "processing_error_count": processing_error_count,
            },
        }

    def get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get open paper positions for a user.

        Positions are sorted deterministically by (opened_at asc, id asc)
        for consistent close ordering.
        """
        # First get user's portfolios
        port_res = self.client.table("paper_portfolios") \
            .select("id") \
            .eq("user_id", user_id) \
            .execute()

        portfolios = port_res.data or []
        if not portfolios:
            return []

        portfolio_ids = [p["id"] for p in portfolios]

        # Get positions
        pos_res = self.client.table("paper_positions") \
            .select("*") \
            .in_("portfolio_id", portfolio_ids) \
            .execute()

        positions = pos_res.data or []

        # Deterministic sort: created_at asc, id asc (oldest first)
        def sort_key(p):
            created = p.get("created_at") or ""
            pid = p.get("id") or ""
            return (created, pid)

        positions.sort(key=sort_key)
        return positions

    def get_positions_closed_today(self, user_id: str) -> int:
        """
        Count positions closed today (via learning_feedback_loops outcomes).
        Used for deduplication to enforce max_closes_per_day.
        """
        today_start, tomorrow_start = _compute_today_window()

        # Count paper trade outcomes closed today
        result = self.client.table("learning_feedback_loops") \
            .select("id", count="exact") \
            .eq("user_id", user_id) \
            .eq("is_paper", True) \
            .eq("outcome_type", "trade_closed") \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()

        return result.count or 0

    @staticmethod
    def _resolve_occ_symbol(position: Dict[str, Any], supabase) -> str:
        """
        Resolve OCC options symbol from position legs or opening order.

        Priority: position.legs → opening order legs → underlying ticker fallback.
        """
        pos_id = position.get("id")
        underlying = position["symbol"]

        # 1. Try position legs (available after Phase 1 / Bug 5 fix)
        pos_legs = position.get("legs") or []
        if pos_legs:
            leg_sym = pos_legs[0].get("symbol", "") if isinstance(pos_legs[0], dict) else ""
            if leg_sym.startswith("O:") or len(leg_sym) > 10:
                return leg_sym

        # 2. Fallback: query opening order's legs
        try:
            open_order = supabase.table("paper_orders") \
                .select("order_json") \
                .eq("position_id", pos_id) \
                .order("created_at", desc=False) \
                .limit(1) \
                .execute()
            if open_order.data:
                legs = open_order.data[0].get("order_json", {}).get("legs", [])
                if legs:
                    leg_sym = legs[0].get("symbol", "")
                    if leg_sym.startswith("O:") or len(leg_sym) > 10:
                        return leg_sym
        except Exception as e:
            logger.warning(f"Failed to resolve OCC symbol for position {pos_id}: {e}")

        logger.warning(
            f"No OCC symbol found for position {pos_id} — "
            f"falling back to underlying ticker {underlying}. "
            f"Quote will be stock NBBO, not options."
        )
        return underlying

    @staticmethod
    def _marginal_ev(position: Dict[str, Any]) -> float:
        """
        Estimate marginal EV for position ranking.

        Positions with worst unrealized P&L should close first (ascending sort).
        """
        return float(position.get("unrealized_pl") or 0.0)

    def _select_positions_to_close(
        self,
        positions: List[Dict[str, Any]],
        remaining_quota: int,
        policy: str,
    ) -> List[Dict[str, Any]]:
        """
        Select and rank positions for closing based on policy.

        Policies:
        - "close_all": Close all open positions (ignores quota)
        - "ev_rank": Close worst marginal EV first, up to quota
        - "min_one": Close oldest first, up to quota (legacy)
        """
        if policy == "close_all":
            return positions

        if policy == "ev_rank":
            # Sort by worst unrealized P&L first (ascending)
            ranked = sorted(positions, key=self._marginal_ev)
            return ranked[:remaining_quota]

        # Default "min_one": oldest first (already sorted by get_open_positions)
        return positions[:remaining_quota]

    def close_positions(
        self,
        user_id: str,
        max_to_close: Optional[int] = None,
        policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Close paper positions according to policy.

        Args:
            user_id: Target user
            max_to_close: Maximum positions to close (default from config)
            policy: Close policy - "close_all" | "ev_rank" | "min_one"

        Returns:
            Summary dict with closed_count, skipped_reason, etc.
        """
        max_to_close = max_to_close or self.config["max_closes_per_day"]
        policy = policy or self.config["close_policy"]

        # Check how many already closed today (skip for close_all policy)
        already_closed = self.get_positions_closed_today(user_id)

        if policy != "close_all" and already_closed >= max_to_close:
            return {
                "status": "ok",
                "closed_count": 0,
                "reason": "max_closes_reached",
                "already_closed_today": already_closed,
            }

        remaining_quota = max_to_close - already_closed

        # Get open positions
        positions = self.get_open_positions(user_id)

        if not positions:
            return {
                "status": "ok",
                "closed_count": 0,
                "reason": "no_positions",
            }

        # Select positions to close based on policy
        to_close = self._select_positions_to_close(positions, remaining_quota, policy)

        logger.info(
            f"paper_auto_close_selection: user_id={user_id} policy={policy} "
            f"open_positions={len(positions)} to_close={len(to_close)} "
            f"already_closed_today={already_closed}"
        )

        # Close using internal logic
        from packages.quantum.paper_endpoints import (
            _stage_order_internal,
            _process_orders_for_user,
            get_analytics_service,
        )
        from packages.quantum.models import TradeTicket

        supabase = self.client
        analytics = get_analytics_service()

        closed = []
        errors = []

        for position in to_close:
            pos_id = position.get("id")
            try:
                # Resolve OCC symbol from position legs or opening order
                occ_symbol = self._resolve_occ_symbol(position, supabase)

                # Build closing ticket
                qty = float(position["quantity"])
                side = "sell" if qty > 0 else "buy"

                ticket = TradeTicket(
                    symbol=position["symbol"],
                    quantity=abs(qty),
                    order_type="market",
                    strategy_type=position.get("strategy_key", "").split("_")[-1] if position.get("strategy_key") else "custom",
                    source_engine="paper_autopilot",
                    legs=[
                        {"symbol": occ_symbol, "action": side, "quantity": abs(qty)}
                    ]
                )

                # Set source_ref_id if available
                if position.get("suggestion_id"):
                    ticket.source_ref_id = position.get("suggestion_id")

                # Stage closing order
                order_id = _stage_order_internal(
                    supabase,
                    analytics,
                    user_id,
                    ticket,
                    position["portfolio_id"],
                    position_id=pos_id,
                    trace_id_override=position.get("trace_id")
                )

                # Process order
                process_result = _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

                closed.append({
                    "position_id": pos_id,
                    "order_id": order_id,
                    "processed": process_result.get("processed", 0),
                    "processing_errors": process_result.get("errors") or None,
                })

            except Exception as e:
                logger.error(f"Failed to close position {pos_id}: {e}")
                errors.append({"position_id": pos_id, "error": str(e)})

        # Compute processing summary
        processing_error_count = sum(
            1 for c in closed if c.get("processing_errors")
        )
        total_processed = sum(c.get("processed", 0) for c in closed)

        # Status: "partial" if staging or processing errors
        has_staging_errors = len(errors) > 0
        has_processing_errors = processing_error_count > 0
        if has_staging_errors or has_processing_errors:
            status = "partial"
        elif closed:
            status = "ok"
        else:
            status = "ok"

        return {
            "status": status,
            "closed_count": len(closed),
            "error_count": len(errors),
            "closed": closed,
            "errors": errors if errors else None,
            "processed_summary": {
                "total_processed": total_processed,
                "processing_error_count": processing_error_count,
            },
        }
