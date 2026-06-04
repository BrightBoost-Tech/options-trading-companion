"""GTC resting profit-limit for flat-cohort mleg debit spreads (flag OFF).

The gap (2026-06-04 GTC diagnostic): every order the system has ever
submitted was DAY — "GTC" existed only as rationale text, and profit exits
are passive DAY limits at the mark, fill-or-watchdog-cancel in ~5 minutes.
A winner that spikes between evaluations can round-trip unseen (BAC
+$462 → +$192, 2026-06-03/04).

This module is the broker-side answer: on a LIVE entry fill, park a
CLOSING mleg GTC limit at the cohort's flat profit credit and let Alpaca
auto-fire when the market reaches it. It COMPETES with the poll-side
INTRADAY_TARGET_PROFIT_ENABLED (15-min detection + DAY-limit close
attempts) — both now exist; choosing between them is a separate deliberate
operator decision. This flag defaults OFF and changes nothing until that
decision.

Hard rules:
  - Flag GTC_PROFIT_EXIT_ENABLED, default OFF → byte-identical behavior
    (no resting order is ever placed). Lenient truthy parse (1/true/yes/on)
    — the strict ``== "1"`` parse burned the intraday-TP flip on 2026-06-04.
  - FLAT-COHORT ONLY: the resting price is static, so it can only encode a
    flat target (cohorts: conservative 0.25 / neutral 0.35 / aggressive
    0.50). Positions whose cohort cannot be resolved fall to the DEFAULT
    time-scaled target curve — a static price would be WRONG for them, so
    no GTC is placed (skip, logged).
  - LIVE entries only (the placement hook lives in poll_pending_orders'
    open-fill branch, which only ever sees broker orders); debit verticals
    only (qty>0, >=2 legs) in v1.
  - Lifecycle: the GTC order is EXEMPT from the idle watchdog (it is
    supposed to rest) and EXCLUDED from the close-idempotency guards (so a
    stop/envelope force-close proceeds and pre-cancels it at the broker via
    submit_and_track's cancel_open_orders_for_symbols). When the GTC fills,
    the existing close-fill reconcile (_close_position_on_fill) closes the
    position.
  - #999 sign convention is REUSED, not modified: the ticket carries
    is_credit_close=True and build_alpaca_order_request negates the limit
    at the broker boundary; requested_price stays unsigned.

Known race (accepted, documented): if the GTC fills at the broker in the
same window a force-close decides to fire, the force-close's pre-cancel
fails (already filled) and its DAY close is broker-rejected against the
now-flat position → needs_manual_review + critical alert (the existing
rejection machinery). Same class as today's manual-close races (H10).
"""

import logging
import os
from typing import Any, Dict, Optional

# Module-level on purpose: models is a light, cycle-free import, and binding
# TradeTicket at import time also defends against test-suite sys.modules
# MagicMock pollution of packages.quantum.models (a lazy in-function import
# would resolve to the mock in full-suite runs).
from packages.quantum.models import TradeTicket

logger = logging.getLogger(__name__)

FLAG_ENV = "GTC_PROFIT_EXIT_ENABLED"

# Marker used by the watchdog exemption + close-idempotency exemption.
SOURCE_ENGINE = "gtc_profit_exit"


def is_enabled() -> bool:
    """Lenient truthy parse — accepts 1/true/yes/on (case-insensitive)."""
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def _f(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_flat_cohort_tp(supabase, cohort_id: Optional[str]) -> Optional[float]:
    """The cohort's FLAT target_profit_pct, or None when it cannot be
    resolved. None means the position is governed by the DEFAULT
    time-scaled target curve — a static GTC price would be wrong, so the
    caller must skip."""
    if not cohort_id:
        return None
    try:
        res = (
            supabase.table("policy_lab_cohorts")
            .select("policy_config")
            .eq("id", cohort_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        tp = _f((res.data[0].get("policy_config") or {}).get("target_profit_pct"))
        if tp is None or tp <= 0 or tp > 5:
            return None
        return tp
    except Exception as e:
        logger.warning(f"[GTC_PROFIT_EXIT] cohort tp resolve failed ({cohort_id}): {e}")
        return None


def maybe_place_gtc_profit_exit(
    supabase, entry_order_id: str, user_id: str
) -> Dict[str, Any]:
    """Flag-gated placement: after a LIVE entry fill, park a closing mleg
    GTC limit at entry × (1 + cohort_flat_tp).

    Returns a decision dict {placed: bool, reason: str, ...}. Never raises
    (fail-soft — placement must never break the fill-commit path). With the
    flag OFF this is a pure no-op.
    """
    try:
        if not is_enabled():
            return {"placed": False, "reason": "flag_off"}

        # ── The entry order (refetched: the fill commit set position_id) ──
        order = (
            supabase.table("paper_orders")
            .select("id, position_id, suggestion_id, execution_mode, alpaca_order_id, avg_fill_price")
            .eq("id", entry_order_id)
            .single()
            .execute()
            .data
        ) or {}
        decision: Dict[str, Any] = {"placed": False, "entry_order_id": entry_order_id}

        if str(order.get("execution_mode") or "") != "alpaca_live":
            decision["reason"] = "not_live_entry"
            return decision
        if not order.get("alpaca_order_id") or not order.get("suggestion_id"):
            decision["reason"] = "not_suggestion_born_broker_entry"
            return decision
        position_id = order.get("position_id")
        if not position_id:
            decision["reason"] = "position_not_committed_yet"
            return decision

        # ── The position ───────────────────────────────────────────────
        position = (
            supabase.table("paper_positions")
            .select("*")
            .eq("id", position_id)
            .single()
            .execute()
            .data
        ) or {}
        qty = _f(position.get("quantity")) or 0.0
        legs = position.get("legs") or []
        if (position.get("status") or "").lower() != "open" or qty <= 0 or len(legs) < 2:
            decision["reason"] = "not_open_long_multileg"
            return decision

        # ── Flat-cohort gate (static price cannot time-scale) ──────────
        tp = _resolve_flat_cohort_tp(supabase, position.get("cohort_id"))
        if tp is None:
            decision["reason"] = "no_flat_cohort_target_time_scaled_default"
            logger.info(
                f"[GTC_PROFIT_EXIT] skip position={str(position_id)[:8]} — cohort "
                f"unresolved → default time-scaled target governs; a static GTC "
                f"price would be wrong"
            )
            return decision

        # ── Idempotency: any existing close-side order blocks placement ─
        close_side = "sell"  # qty > 0 guaranteed above
        existing = (
            supabase.table("paper_orders")
            .select("id, status")
            .eq("position_id", position_id)
            .eq("side", close_side)
            .in_("status", [
                "staged", "submitted", "working", "partial", "pending",
                "needs_manual_review", "filled",
            ])
            .limit(1)
            .execute()
        )
        if existing.data:
            decision["reason"] = "close_order_already_exists"
            return decision

        # ── The resting price: entry × (1 + flat tp), per spread ────────
        entry_price = _f(order.get("avg_fill_price")) or _f(position.get("avg_entry_price"))
        if not entry_price or entry_price <= 0:
            decision["reason"] = "entry_price_unavailable"
            return decision
        target_credit = round(entry_price * (1.0 + tp), 2)

        # ── Build the closing ticket (same conventions as _close_position) ─
        abs_qty = abs(int(qty))
        close_legs = []
        for leg in legs:
            orig_action = leg.get("action") or leg.get("side") or "buy"
            close_legs.append({
                "symbol": leg.get("symbol") or leg.get("occ_symbol") or "",
                "action": "sell" if orig_action == "buy" else "buy",
                "quantity": abs_qty,
                "type": leg.get("type", "call"),
                "strike": leg.get("strike"),
                "expiry": leg.get("expiry"),
            })

        ticket = TradeTicket(
            symbol=position["symbol"],
            quantity=abs_qty,
            order_type="limit",
            limit_price=target_credit,
            strategy_type="custom",
            source_engine=SOURCE_ENGINE,
            legs=close_legs,
            # #999: selling back a long debit spread produces net credit →
            # the broker boundary negates the limit. requested_price stays
            # unsigned for accounting consumers.
            is_credit_close=True,
            time_in_force="gtc",
        )

        # ── Stage + submit through the canonical path (H13) ────────────
        # Live position → _stage_order_internal resolves the alpaca mode and
        # submits via submit_and_track. The marketable-entry hook inside it
        # skips close orders (position_id set); pre-cancel is harmless here
        # (no other open orders on these legs right after entry).
        from packages.quantum.paper_endpoints import (
            _stage_order_internal,
            get_analytics_service,
        )

        gtc_order_id = _stage_order_internal(
            supabase,
            get_analytics_service(),
            user_id,
            ticket,
            position["portfolio_id"],
            position_id=position_id,
            trace_id_override=position.get("trace_id"),
        )

        decision.update({
            "placed": True,
            "reason": "gtc_profit_limit_placed",
            "gtc_order_id": gtc_order_id,
            "position_id": position_id,
            "entry_price": entry_price,
            "flat_tp": tp,
            "target_credit": target_credit,
        })
        logger.info(
            f"[GTC_PROFIT_EXIT] placed resting GTC profit-limit: "
            f"position={str(position_id)[:8]} entry={entry_price} tp={tp:.0%} "
            f"target_credit={target_credit} order={gtc_order_id}"
        )
        return decision
    except Exception as e:  # fail-soft: never break the fill-commit path
        logger.error(
            f"[GTC_PROFIT_EXIT] placement failed (non-fatal) "
            f"entry_order={entry_order_id}: {e}"
        )
        return {"placed": False, "reason": f"error:{type(e).__name__}"}
