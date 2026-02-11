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
- PAPER_AUTOPILOT_CLOSE_POLICY: "min_one" (default)
- PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY: Max closes per day (default: "1")
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
        "close_policy": os.environ.get("PAPER_AUTOPILOT_CLOSE_POLICY", "min_one"),
        "max_closes_per_day": int(os.environ.get("PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY", "1")),
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

        # Filter by min_score and dedupe
        candidates = []
        for s in suggestions:
            sid = s.get("id")
            if sid in already_executed:
                continue

            score = s.get("score") or s.get("probability_of_profit") or s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0

            if score >= min_score:
                candidates.append(s)

        if not candidates:
            return {
                "status": "ok",
                "executed_count": 0,
                "skipped_count": len(suggestions),
                "reason": "no_qualifying_candidates",
            }

        # Take top N
        to_execute = candidates[:limit]

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

                executed.append({
                    "suggestion_id": sid,
                    "order_id": order_id,
                    "processed": process_result.get("processed", 0),
                    "processing_errors": process_result.get("errors") or None,
                })

            except Exception as e:
                logger.error(f"Failed to execute suggestion {sid}: {e}")
                errors.append({"suggestion_id": sid, "error": str(e)})

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
            policy: Close policy - "min_one" (default)

        Returns:
            Summary dict with closed_count, skipped_reason, etc.
        """
        max_to_close = max_to_close or self.config["max_closes_per_day"]
        policy = policy or self.config["close_policy"]

        # Check how many already closed today
        already_closed = self.get_positions_closed_today(user_id)

        if already_closed >= max_to_close:
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
        # "min_one" policy: close at least 1, up to remaining quota
        to_close = positions[:remaining_quota]

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
                # Build closing ticket (same logic as close_paper_position)
                qty = float(position["quantity"])
                side = "sell" if qty > 0 else "buy"

                ticket = TradeTicket(
                    symbol=position["symbol"],
                    quantity=abs(qty),
                    order_type="market",
                    strategy_type=position.get("strategy_key", "").split("_")[-1] if position.get("strategy_key") else "custom",
                    source_engine="paper_autopilot",
                    legs=[
                        {"symbol": position["symbol"], "action": side, "quantity": abs(qty)}
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
