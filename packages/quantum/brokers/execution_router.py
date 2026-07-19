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
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    INTERNAL_PAPER = "internal_paper"
    ALPACA_PAPER = "alpaca_paper"
    ALPACA_LIVE = "alpaca_live"
    SHADOW = "shadow"


# ── Single-leg experiment hard routing guard ────────────────────────────────
# The one-contract shadow-only single-leg EXPERIMENT (owner decision
# SINGLE_LEG=ONE_CONTRACT_SHADOW_ONLY_EXPERIMENT) is structurally shadow-only:
# a single-leg experiment order must NEVER reach a broker, regardless of
# portfolio routing_mode or EXECUTION_MODE. This is the execution-seam half of
# a two-layer guard (the generator refuses to emit a live-routed candidate;
# this refuses to submit one even if a bug produced it). "shadow" here means
# non-broker: internal_paper and shadow modes are fine; alpaca_paper/alpaca_live
# and a live_eligible portfolio are broker-bound and hard-refused.
SINGLE_LEG_EXPERIMENT = "single_leg"
SHADOW_ONLY_ROUTING = "shadow_only"
# Canonical live-routing value — matches position_scope.LIVE_ROUTING_MODE and
# should_submit_to_broker below (the only routing that reaches the broker).
LIVE_ROUTING_MODE = "live_eligible"
_BROKER_SUBMIT_MODES = frozenset({ExecutionMode.ALPACA_PAPER.value, ExecutionMode.ALPACA_LIVE.value})


class SingleLegLiveRoutingForbidden(RuntimeError):
    """A single-leg experiment order was about to be treated as live-eligible /
    broker-submittable. Typed refusal — the experiment is shadow-only by
    construction; this never degrades into a silent no-op or a broker order."""


def is_single_leg_experiment(order_request: Any) -> bool:
    """True iff the order carries the explicit single-leg experiment marker.

    Keys on the explicit ``experiment`` / ``strategy_experiment`` stamp the
    generator writes — NOT on leg count alone, so a legitimate one-leg order
    from some future non-experimental path is never caught by accident."""
    if not isinstance(order_request, Mapping):
        order_request = getattr(order_request, "__dict__", None) or {}
        if not isinstance(order_request, Mapping):
            return False
    marker = order_request.get("experiment") or order_request.get("strategy_experiment")
    return str(marker or "").strip().lower() == SINGLE_LEG_EXPERIMENT


# Single-leg experiment strategy names — emitted ONLY by the single-leg
# experiment. contract.py verified verticals/condors are the ENTIRE pre-existing
# structure surface; long_call/long_put were ADDED by #1287 for this experiment.
# A paper_positions row carries NO explicit experiment column (only strategy /
# strategy_key), so on the CLOSE seam these names are the by-construction marker.
# ⚠ SEAM: a FUTURE non-experimental single-leg feature would also match these
# names — revisit before building one (mirrors the add-to-position seam already
# on the ledger).
SINGLE_LEG_EXPERIMENT_STRATEGIES = frozenset({"long_call", "long_put"})


def _coerce_mapping(obj: Any) -> Mapping:
    if isinstance(obj, Mapping):
        return obj
    d = getattr(obj, "__dict__", None)
    return d if isinstance(d, Mapping) else {}


def is_single_leg_experiment_row(row: Any) -> bool:
    """Submit-seam recognizer: True iff a DB row (paper_orders / paper_positions)
    or an order request is a single-leg experiment that must never broker-submit.

    Broader than ``is_single_leg_experiment`` (which keys on a top-level marker
    only) so it fires on the SHAPES the real submit seam actually sees:
      1. the explicit experiment marker at top level, OR nested inside
         ``order_json`` (paper_orders stores the order request under an
         ``order_json`` jsonb column — no top-level experiment column), OR
      2. a single-leg experiment strategy name (long_call/long_put) on
         strategy / strategy_key / strategy_type, top level or in order_json
         (the paper_positions close shape carries no experiment column — see the
         SEAM note on SINGLE_LEG_EXPERIMENT_STRATEGIES)."""
    d = _coerce_mapping(row)
    if not d:
        return False
    if is_single_leg_experiment(d):
        return True
    order_json = d.get("order_json")
    oj = order_json if isinstance(order_json, Mapping) else {}
    if oj and is_single_leg_experiment(oj):
        return True

    def _strategy_hit(m: Mapping) -> bool:
        for key in ("strategy", "strategy_key", "strategy_type"):
            val = m.get(key)
            if isinstance(val, str) and val.strip().lower() in SINGLE_LEG_EXPERIMENT_STRATEGIES:
                return True
        return False

    return _strategy_hit(d) or (bool(oj) and _strategy_hit(oj))


def _alert_single_leg_submit_blocked(portfolio_id: str, supabase, order: Any) -> None:
    """The single-leg experiment veto just blocked a broker submit. Emit LOUD
    (critical alert) iff the portfolio was ``live_eligible`` — there the veto
    actually OVERRODE a broker order (an upstream bug: a shadow-only experiment
    reached a live-routed portfolio). For a shadow_only/missing portfolio the
    routing check below would have blocked anyway (the normal shadow path), so a
    single info line suffices. Best-effort — never raises."""
    routing = None
    try:
        res = supabase.table("paper_portfolios") \
            .select("routing_mode") \
            .eq("id", portfolio_id) \
            .limit(1) \
            .execute()
        if getattr(res, "data", None):
            routing = res.data[0].get("routing_mode")
    except Exception:
        routing = None
    if routing == LIVE_ROUTING_MODE:
        logger.critical(
            "[ROUTING] single-leg experiment order BLOCKED at the submit seam on a "
            "LIVE_ELIGIBLE portfolio %s — shadow-only by construction; the veto "
            "overrode a broker submission (upstream bug: a single-leg experiment "
            "reached a live-routed portfolio)", str(portfolio_id)[:8],
        )
        try:
            from packages.quantum.observability.alerts import alert, _get_admin_supabase
            alert(
                _get_admin_supabase(),
                alert_type="single_leg_experiment_live_submit_blocked",
                severity="critical",
                message=(
                    f"single-leg experiment blocked from broker submit on "
                    f"live_eligible portfolio {portfolio_id}"
                ),
                metadata={
                    "function_name": "should_submit_to_broker",
                    "portfolio_id": str(portfolio_id),
                    "consequence": (
                        "Broker submission blocked (single-leg experiment is "
                        "shadow-only by construction). No broker order placed; the "
                        "order is marked shadow_blocked and fills internally."
                    ),
                    "operator_action_required": (
                        "Investigate how a single-leg experiment order reached a "
                        "live_eligible portfolio — the experiment is dark/shadow-only "
                        "and should never bind to a live-routed portfolio."
                    ),
                },
            )
        except Exception:
            # Alert path failure must not break the routing decision.
            pass
    else:
        logger.info(
            "[ROUTING] single-leg experiment order blocked at submit seam "
            "(shadow-only by construction; portfolio %s routing=%s)",
            str(portfolio_id)[:8], routing,
        )


def assert_single_leg_shadow_only(
    order_request: Any,
    *,
    execution_mode: Optional[str] = None,
    routing_mode: Optional[str] = None,
) -> None:
    """Hard guard: a single-leg experiment order must be shadow-only and must
    never reach a broker. No-op for any non-single-leg-experiment order.

    Raises ``SingleLegLiveRoutingForbidden`` if a single-leg experiment order
    (a) is missing its ``routing='shadow_only'`` marker (malformed — refuse
    unconditionally), or (b) would reach a broker: EXECUTION_MODE is
    alpaca_paper/alpaca_live, or the portfolio routing_mode is live_eligible."""
    if not is_single_leg_experiment(order_request):
        return
    order_routing = str((order_request.get("routing") if isinstance(order_request, Mapping) else None) or "").strip().lower()
    if order_routing != SHADOW_ONLY_ROUTING:
        raise SingleLegLiveRoutingForbidden(
            f"single-leg experiment order missing shadow_only routing marker "
            f"(routing={order_routing!r}) — refusing to route"
        )
    mode = str(execution_mode or "").strip().lower()
    portfolio_routing = str(routing_mode or "").strip().lower()
    if mode in _BROKER_SUBMIT_MODES or portfolio_routing == LIVE_ROUTING_MODE:
        raise SingleLegLiveRoutingForbidden(
            f"single-leg experiment is shadow-only and cannot be broker-submitted "
            f"(execution_mode={mode!r}, routing_mode={portfolio_routing!r})"
        )


def should_submit_to_broker(portfolio_id: str, supabase, order: Any = None) -> bool:
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

    SINGLE-LEG EXPERIMENT HARD VETO (submit-seam SAFETY OWNER): when ``order`` is
    supplied and carries the single-leg experiment marker
    (``is_single_leg_experiment_row``), returns False (block broker submit)
    REGARDLESS of routing_mode — even a mistakenly ``live_eligible`` portfolio
    cannot broker-submit it. This seam — the one the 3 broker-submit sites call —
    is now the OWNER of that safety; the ExecutionRouter.execute_order guard
    (``assert_single_leg_shadow_only``, no production callers) remains as
    defense-in-depth. A critical alert fires iff the veto overrode a live_eligible
    routing. For any non-single-leg order — or when ``order`` is omitted — behavior
    is byte-identical to the pre-veto function.
    """
    if order is not None and is_single_leg_experiment_row(order):
        _alert_single_leg_submit_blocked(portfolio_id, supabase, order)
        return False
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


def live_enabled() -> bool:
    """LIVE_ENABLED — the real-money arming gate for alpaca_live.

    Truthy set is ('true', '1') ONLY — historically NOT yes/on. Absent/empty
    -> False (safe). Extracted 2026-07-16 (startup flag-echo, P2 §3) so the
    echo reports the SAME parse this router applies at the alpaca_live gate
    below — reuse, never a reimplementation (the drift-lie guard). Behavior is
    identical to the prior inline read; ``x not in S`` == ``not (x in S)``.
    """
    return os.environ.get("LIVE_ENABLED", "").lower() in ("true", "1")


def get_execution_mode() -> ExecutionMode:
    """Determine execution mode from environment."""
    raw = os.environ.get("EXECUTION_MODE", "internal_paper").lower().strip()
    try:
        mode = ExecutionMode(raw)
    except ValueError:
        # Loud-Error Doctrine v1.0 — SAFETY-CRITICAL silent fallback.
        # Unknown EXECUTION_MODE means real-money routing intent
        # (alpaca_live, alpaca_paper) silently degrades to TCM
        # simulation. The bug at 2026-04-25 17:10Z set
        # EXECUTION_MODE='micro_live' (a phase name, not a valid mode),
        # which silently routed to internal_paper for 5 days. This
        # site was missed during the H1-H5 doctrine sweep; correcting
        # now (#A4 sequence).
        from packages.quantum.observability.alerts import alert, _get_admin_supabase
        try:
            alert(
                _get_admin_supabase(),
                user_id=None,
                alert_type="execution_mode_invalid_env_value",
                severity="critical",
                message=f"Unknown EXECUTION_MODE='{raw}' — defaulted to internal_paper",
                metadata={
                    "function_name": "get_execution_mode",
                    "raw_value": raw,
                    "valid_values": [m.value for m in ExecutionMode],
                    "consequence": (
                        "All broker submissions silently degraded to TCM simulation. "
                        "Trades intended as alpaca_live/alpaca_paper went internal_paper "
                        "instead. Position state and cash accounting may diverge from intent. "
                        "Live Alpaca account receives no orders despite operator intent."
                    ),
                    "operator_action_required": (
                        "Verify EXECUTION_MODE Railway env. Valid values: "
                        "internal_paper, alpaca_paper, alpaca_live, shadow. "
                        "If alpaca_live intended, also ensure LIVE_ENABLED=true "
                        "(second-stage safety check at execution_router.py:88-94 "
                        "falls back to alpaca_paper otherwise). "
                        "Audit paper_orders.execution_mode for trades since the env "
                        "was set to confirm intent vs reality."
                    ),
                },
            )
        except Exception:
            # Alert path failure must not break routing decision.
            # The warning log below remains as last-resort visibility.
            pass
        logger.warning(f"[EXEC_ROUTER] Unknown EXECUTION_MODE '{raw}', defaulting to internal_paper")
        return ExecutionMode.INTERNAL_PAPER

    # Safety: alpaca_live requires explicit LIVE_ENABLED=true
    if mode == ExecutionMode.ALPACA_LIVE:
        if not live_enabled():
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
        # Hard guard (FIRST, before any routing): a single-leg experiment order
        # is shadow-only by construction and must never reach a broker. Raises a
        # typed SingleLegLiveRoutingForbidden in a broker-submit mode — the
        # broker path below is never reached for such an order.
        assert_single_leg_shadow_only(order_request, execution_mode=self.mode.value)

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
