"""
Execution Router — routes order flow based on mode and cohort status.

Modes:
  internal_paper  — existing TCM simulation (default, no broker calls)
  alpaca_paper    — orders go to Alpaca paper trading API
  alpaca_live     — real money (requires LIVE_ENABLED=true)
  shadow          — log only, no execution

Environment:
  EXECUTION_MODE      — one of the above (default: internal_paper)
  LIVE_ENABLED        — must be "true" for alpaca_live mode
  LIVE_MAX_CAPITAL_PCT — max % of account for live orders (default: 5)
"""

import logging
import os
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    INTERNAL_PAPER = "internal_paper"
    ALPACA_PAPER = "alpaca_paper"
    ALPACA_LIVE = "alpaca_live"
    SHADOW = "shadow"


def should_submit_to_broker(portfolio_id: str, supabase) -> bool:
    """True if portfolio's routing_mode is live_eligible.

    False (block broker submission) if shadow_only or if the portfolio
    is missing. The defensive 'False on missing' prevents accidental
    real-money submission for orphaned order rows.

    Used by 3 broker-submit sites:
    - paper_endpoints._stage_order_internal (autopilot entry)
    - paper_exit_evaluator._close_position (exit close)
    - brokers.safety_checks.approve_order (human approval)

    PR2a behavior: when False, gate sites mark order as
    execution_mode='shadow_blocked' and leave at status='staged'.
    Cohort data flow (TCM simulate + commit) is deferred to PR2b.

    Composition with EXECUTION_MODE: routing_mode='shadow_only' blocks
    broker submission regardless of EXECUTION_MODE setting.
    """
    try:
        res = supabase.table("paper_portfolios") \
            .select("routing_mode") \
            .eq("id", portfolio_id) \
            .limit(1) \
            .execute()
        if not res.data:
            return False
        return res.data[0].get("routing_mode") == "live_eligible"
    except Exception as e:
        from packages.quantum.observability.alerts import alert, _get_admin_supabase
        alert(
            _get_admin_supabase(),
            alert_type="routing_dispatch_query_failed",
            severity="critical",
            message=f"routing_mode query failed for portfolio {portfolio_id}",
            metadata={
                "function_name": "should_submit_to_broker",
                "portfolio_id": portfolio_id,
                "error_class": type(e).__name__,
                "error_message": str(e)[:500],
                "consequence": "broker submit blocked (defaulted to shadow); portfolio's intended routing could not be verified",
                "operator_action_required": "Verify portfolio routing_mode manually. If routing query is genuinely failing, investigate before resuming autopilot — broker dispatch decisions cannot be trusted while query path is unhealthy.",
            },
        )
        return False


def get_execution_mode() -> ExecutionMode:
    """Determine execution mode from environment."""
    raw = os.environ.get("EXECUTION_MODE", "internal_paper").lower().strip()
    try:
        mode = ExecutionMode(raw)
    except ValueError:
        logger.warning(f"[EXEC_ROUTER] Unknown EXECUTION_MODE '{raw}', defaulting to internal_paper")
        return ExecutionMode.INTERNAL_PAPER

    # Safety: alpaca_live requires explicit LIVE_ENABLED=true
    if mode == ExecutionMode.ALPACA_LIVE:
        if os.environ.get("LIVE_ENABLED", "").lower() not in ("true", "1"):
            logger.critical(
                "[EXEC_ROUTER] EXECUTION_MODE=alpaca_live but LIVE_ENABLED is not true. "
                "Falling back to alpaca_paper."
            )
            return ExecutionMode.ALPACA_PAPER

    return mode


class ExecutionRouter:
    """
    Routes orders to the appropriate execution backend based on mode.

    Usage:
        router = ExecutionRouter(supabase)
        result = router.execute_order(order_request)
    """

    def __init__(self, supabase=None, alpaca_client=None):
        self.supabase = supabase
        self.mode = get_execution_mode()
        self._alpaca = alpaca_client

        logger.info(f"[EXEC_ROUTER] Initialized in {self.mode.value} mode")

    @property
    def alpaca(self):
        """Lazy-load Alpaca client only when needed."""
        if self._alpaca is None and self.mode in (
            ExecutionMode.ALPACA_PAPER, ExecutionMode.ALPACA_LIVE,
        ):
            from packages.quantum.brokers.alpaca_client import get_alpaca_client
            self._alpaca = get_alpaca_client()
        return self._alpaca

    def execute_order(
        self,
        order_request: Dict[str, Any],
        user_id: str,
        internal_order_id: Optional[str] = None,
        cohort_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route order to appropriate execution path.

        Args:
            order_request: Dict with symbol, legs, order_type, limit_price, etc.
            user_id: Owning user
            internal_order_id: Our paper_orders.id (for linking)
            cohort_name: Policy Lab cohort (for shadow routing)

        Returns:
            Dict with execution_mode, status, and mode-specific fields.
        """
        if self.mode == ExecutionMode.INTERNAL_PAPER:
            return self._execute_internal_paper(order_request, internal_order_id)

        if self.mode == ExecutionMode.SHADOW:
            return self._execute_shadow(order_request, internal_order_id)

        if self.mode in (ExecutionMode.ALPACA_PAPER, ExecutionMode.ALPACA_LIVE):
            return self._execute_alpaca(order_request, user_id, internal_order_id)

        return {"execution_mode": self.mode.value, "status": "unknown_mode"}

    def _execute_internal_paper(
        self, order_request: Dict, internal_order_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Internal paper mode — no broker call. The existing TCM simulation
        in _process_orders_for_user handles fills.
        """
        return {
            "execution_mode": ExecutionMode.INTERNAL_PAPER.value,
            "status": "delegated_to_tcm",
            "internal_order_id": internal_order_id,
            "reason": "Order will be filled by TCM simulation in process_orders",
        }

    def _execute_shadow(
        self, order_request: Dict, internal_order_id: Optional[str],
    ) -> Dict[str, Any]:
        """Shadow mode — log only, no execution."""
        logger.info(
            f"[EXEC_ROUTER] SHADOW: order logged but not executed. "
            f"internal_order_id={internal_order_id} "
            f"symbol={order_request.get('symbol')} "
            f"legs={len(order_request.get('legs', []))}"
        )
        return {
            "execution_mode": ExecutionMode.SHADOW.value,
            "status": "shadow_logged",
            "internal_order_id": internal_order_id,
        }

    def _execute_alpaca(
        self,
        order_request: Dict,
        user_id: str,
        internal_order_id: Optional[str],
    ) -> Dict[str, Any]:
        """Submit order to Alpaca (paper or live)."""
        if not self.alpaca:
            logger.error("[EXEC_ROUTER] Alpaca client not available — falling back to shadow")
            return self._execute_shadow(order_request, internal_order_id)

        try:
            alpaca_result = self.alpaca.submit_option_order(order_request)

            # Store Alpaca order ID on our internal order
            if internal_order_id and self.supabase:
                self.supabase.table("paper_orders").update({
                    "alpaca_order_id": alpaca_result.get("alpaca_order_id"),
                    "execution_mode": self.mode.value,
                    "broker_status": alpaca_result.get("status"),
                    "broker_response": alpaca_result,
                    "status": "submitted",
                }).eq("id", internal_order_id).execute()

            return {
                "execution_mode": self.mode.value,
                "status": "submitted",
                "alpaca_order_id": alpaca_result.get("alpaca_order_id"),
                "broker_status": alpaca_result.get("status"),
                "internal_order_id": internal_order_id,
            }

        except Exception as e:
            logger.error(
                f"[EXEC_ROUTER] Alpaca submission failed: {e}. "
                f"internal_order_id={internal_order_id}"
            )
            # Mark order as failed
            if internal_order_id and self.supabase:
                self.supabase.table("paper_orders").update({
                    "execution_mode": self.mode.value,
                    "broker_status": "submission_failed",
                    "broker_response": {"error": str(e)},
                }).eq("id", internal_order_id).execute()

            return {
                "execution_mode": self.mode.value,
                "status": "submission_failed",
                "error": str(e),
                "internal_order_id": internal_order_id,
            }

    # ── Order status sync ─────────────────────────────────────────────

    def sync_order_status(self, internal_order_id: str) -> Dict[str, Any]:
        """
        Sync order status from Alpaca back to paper_orders.
        Maps Alpaca order states → internal states.
        """
        if not self.alpaca or not self.supabase:
            return {"status": "no_client"}

        # Get our order to find the Alpaca order ID
        res = self.supabase.table("paper_orders") \
            .select("alpaca_order_id, status") \
            .eq("id", internal_order_id) \
            .single() \
            .execute()
        order = res.data
        if not order or not order.get("alpaca_order_id"):
            return {"status": "no_alpaca_id"}

        try:
            alpaca_order = self.alpaca.get_order(order["alpaca_order_id"])
        except Exception as e:
            logger.error(f"[EXEC_ROUTER] sync_order_status failed: {e}")
            return {"status": "error", "error": str(e)}

        # Map Alpaca status → internal status
        alpaca_status = alpaca_order.get("status", "")
        status_map = {
            "new": "working",
            "accepted": "working",
            "pending_new": "working",
            "partially_filled": "partial",
            "filled": "filled",
            "done_for_day": "working",
            "canceled": "cancelled",
            "expired": "cancelled",
            "replaced": "working",
            "pending_cancel": "working",
            "pending_replace": "working",
            "rejected": "cancelled",
        }
        internal_status = status_map.get(alpaca_status, "working")

        update = {
            "broker_status": alpaca_status,
            "broker_response": alpaca_order,
            "status": internal_status,
        }

        filled_qty = alpaca_order.get("filled_qty", 0)
        if filled_qty and filled_qty > 0:
            update["filled_qty"] = filled_qty
            if alpaca_order.get("filled_avg_price"):
                update["avg_fill_price"] = alpaca_order["filled_avg_price"]
            if alpaca_order.get("filled_at"):
                update["filled_at"] = alpaca_order["filled_at"]

        self.supabase.table("paper_orders") \
            .update(update) \
            .eq("id", internal_order_id) \
            .execute()

        return {
            "status": "synced",
            "internal_status": internal_status,
            "broker_status": alpaca_status,
            "filled_qty": filled_qty,
        }

    # ── Position sync ─────────────────────────────────────────────────

    def sync_positions(self, user_id: str) -> Dict[str, Any]:
        """
        Sync positions from Alpaca and log them.
        Full reconciliation is in position_sync.py.
        """
        if not self.alpaca:
            return {"status": "no_client"}

        try:
            positions = self.alpaca.get_option_positions()
            logger.info(f"[EXEC_ROUTER] Synced {len(positions)} option positions from Alpaca")
            return {"status": "ok", "position_count": len(positions), "positions": positions}
        except Exception as e:
            logger.error(f"[EXEC_ROUTER] Position sync failed: {e}")
            return {"status": "error", "error": str(e)}
