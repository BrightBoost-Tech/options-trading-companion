"""Paper-shadow executor — Phase 1b core (account-isolated order choke-point +
own-fill lifecycle + canonical geometry policy).

Builds on the merged isolation foundation:
  - #1003: dedicated paper client + PA3I8CYLXBOS guard + paper_shadow
    routing_mode + the 3 primary live-job exclusion filters.
  - #1005: reconcile-loop isolation — the live processor/reconciler
    (_process_orders_for_user, alpaca_order_sync Step-2/3) now SKIP
    paper_shadow. So the executor MUST own its full position lifecycle.

This module owns that lifecycle by REUSING core functions (H13 — it does NOT
reimplement #999's close path, the order primitive, or the mark/reconcile
math); it only adds the executor's own orchestration:
  - every order goes through ONE choke-point (`guarded_paper_submit`) that
    builds the dedicated paper client, re-confirms account == PA3I8CYLXBOS,
    then submits — NEVER the global live client (211900084);
  - open-fill → create via the core `_repair_filled_order_commit`;
  - close-fill → reconcile via the core `_close_position_on_fill`;
  - a canonical geometry exit policy (arm B) derived from `exit_geometry`.

SCOPE (this slice): the isolated mechanics + geometry policy, flag OFF, unit
tested. The synthetic-capital selection wiring (deployable_capital_override),
the end-to-end run loop (poll → pair-open → manage → close), arm-A premium-%
management, and D6 realized recording land in the follow-up slice.

RUN-GATE (do not bypass): the executor's first real run requires
  (a) the worker confirmed running #1003 + #1005 (full isolation),
  (b) market hours, and
  (c) a deliberate PAPER_SHADOW_EXECUTOR_ENABLED flip.
Code lands flag-OFF; nothing runs until that deliberate enable.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from packages.quantum.services.paper_shadow_isolation import (
    PAPER_ACCOUNT_NUMBER,
    PAPER_SHADOW_ROUTING_MODE,
    build_paper_client,
    assert_paper_account,
    is_enabled,
)

logger = logging.getLogger(__name__)

# Mid small-tier band; headroom for ~3–5 paired positions (each pair = two
# tier-sized opens). Selection/sizing uses THIS, never paper's real ~$98k.
SYNTHETIC_TIER_CAPITAL = 2500.0

# Stable name for the executor's dedicated paper_shadow portfolio.
SHADOW_PORTFOLIO_NAME = "paper_shadow_executor"


class PaperShadowExecutorDisabled(RuntimeError):
    """Raised if an order-placing path is reached while the flag is OFF — a
    guard against accidental execution. Nothing should call the submit path
    unless is_enabled()."""


# ── Account-isolated submission choke-point (load-bearing safety) ──────────
def guarded_paper_submit(
    supabase, order_row: Dict[str, Any], user_id: str,
) -> Dict[str, Any]:
    """The SINGLE path through which every executor order is submitted.

    1. Refuse to run unless the flag is ON (defense against accidental calls).
    2. Build the DEDICATED paper client (fails closed without paper creds;
       NEVER the global live get_alpaca_client()).
    3. Re-confirm account == PA3I8CYLXBOS; abort (raise) otherwise — no order.
    4. Submit via the core `submit_and_track`, passing the dedicated client.

    There is no other submission path in this module — so there is no path by
    which an executor order can reach the live account (211900084).
    """
    if not is_enabled():
        raise PaperShadowExecutorDisabled(
            "guarded_paper_submit called while PAPER_SHADOW_EXECUTOR_ENABLED is "
            "OFF — refusing to place an order."
        )
    client = build_paper_client()          # dedicated paper creds, paper=True
    account = assert_paper_account(client)  # == PA3I8CYLXBOS or raise
    logger.info(
        "[PAPER_SHADOW] submitting order=%s on account=%s (paper-only)",
        order_row.get("id"), account,
    )
    from packages.quantum.brokers.alpaca_order_handler import submit_and_track

    return submit_and_track(client, supabase, order_row, user_id)


# ── paper_shadow portfolio bootstrap ──────────────────────────────────────
def get_or_create_shadow_portfolio(supabase, user_id: str) -> Dict[str, Any]:
    """Get (or create) the executor's dedicated portfolio, tagged
    routing_mode='paper_shadow' so every live job excludes it (#1003 primary
    filters + #1005 reconcile loops). All executor positions live here."""
    existing = supabase.table("paper_portfolios") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("routing_mode", PAPER_SHADOW_ROUTING_MODE) \
        .limit(1) \
        .execute()
    if existing.data:
        return existing.data[0]

    payload = {
        "user_id": user_id,
        "name": SHADOW_PORTFOLIO_NAME,
        "routing_mode": PAPER_SHADOW_ROUTING_MODE,
        "cash_balance": SYNTHETIC_TIER_CAPITAL,
    }
    created = supabase.table("paper_portfolios").insert(payload).execute()
    logger.info("[PAPER_SHADOW] created paper_shadow portfolio for %s", user_id[:8])
    return (created.data or [payload])[0]


# ── Own-fill lifecycle (reuse core; the live path skips paper_shadow) ──────
def commit_open_fill(supabase, order: Dict[str, Any], portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """Open-fill → CREATE the tracked paper_shadow position. Reuses the core
    `_repair_filled_order_commit` (H13). The live `_process_orders_for_user`
    skips paper_shadow (#1005), so the executor does this itself."""
    from packages.quantum.paper_endpoints import _repair_filled_order_commit
    from packages.quantum.services.analytics_service import AnalyticsService

    return _repair_filled_order_commit(
        supabase, AnalyticsService(supabase), order.get("user_id"), order, portfolio,
    )


def reconcile_close_fill(
    supabase, position_id: str, order: Dict[str, Any], alpaca_order: Dict[str, Any],
) -> None:
    """Close-fill → RECONCILE the paper_shadow position to closed. Reuses the
    core `_close_position_on_fill` (H13 — which itself reuses close_math +
    close_helper). The live Step-3 reconcile skips paper_shadow (#1005)."""
    from packages.quantum.brokers.alpaca_order_handler import _close_position_on_fill

    _close_position_on_fill(supabase, position_id, order, alpaca_order)


# ── Canonical geometry exit policy (arm B) ────────────────────────────────
def geometry_exit_decision(
    position: Dict[str, Any],
    underlying_spot: Optional[float],
    dte: Optional[int],
) -> Tuple[str, str]:
    """Canonical geometry policy for arm B — a FULL exit system per
    `exit_geometry` (debit-verticals only):
      - STOP on breakeven breach (R2) — checked first (downside protection);
      - TAKE_PROFIT once the underlying reaches the configured width fraction
        (R1_frac) OR the DTE-scaled level (R4);
      - else HOLD.

    Returns (decision, reason) where decision ∈ {hold, take_profit, stop, n/a}.
    PURE — composes exit_geometry's pure rules; the caller acts on the result
    by routing a close through `guarded_paper_submit` (the #999 path).
    """
    from packages.quantum.services.exit_geometry import (
        compute_spread_geometry,
        evaluate_geometry_rules,
    )

    geometry = compute_spread_geometry(position, underlying_spot, dte)
    if not geometry.get("applicable"):
        return ("n/a", geometry.get("reason", "geometry_not_applicable"))

    rules = evaluate_geometry_rules(geometry)
    # Rules are n/a when the underlying spot is unavailable (geometry is
    # computable from strikes alone, but no decision can be made without spot).
    if rules["R2"]["decision"] == "n/a":
        return ("n/a", rules["R2"]["reason"])
    # Downside first (safety): a breakeven breach stops regardless of TP rules.
    if rules["R2"]["decision"] == "stop":
        return ("stop", f"geometry_R2:{rules['R2']['reason']}")
    if rules["R1_frac"]["decision"] == "take_profit":
        return ("take_profit", f"geometry_R1_frac:{rules['R1_frac']['reason']}")
    if rules["R4"]["decision"] == "take_profit":
        return ("take_profit", f"geometry_R4:{rules['R4']['reason']}")
    return ("hold", "geometry_below_profit_and_stop_levels")


# ── Order operations — EVERY order routes through the single door ──────────
# These are the ONLY order-placing functions in the orchestration. There is no
# direct call to submit_and_track or any broker submit primitive here — every
# submission goes through guarded_paper_submit (the #1007 choke-point), so no
# executor order can reach the live account.

def _submit_staged(supabase, order_id: str, user_id: str) -> Dict[str, Any]:
    """Fetch a staged paper_orders row and submit it through the single door."""
    row = supabase.table("paper_orders").select("*").eq("id", order_id).single().execute().data
    return guarded_paper_submit(supabase, row, user_id)


def open_pair(supabase, user_id: str, candidate: Dict[str, Any], portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """Open TWO IDENTICAL paper positions (arm A premium-%, arm B geometry) for
    one ranked candidate, in the executor's paper_shadow portfolio, each
    submitted through the single door. Reuses the canonical `_stage_order_internal`
    stager (H13) — no parallel order-building.

    Returns {arm_a, arm_b} submission results. Both legs of a pair are
    structurally identical; the only difference is which exit rule manages each
    (set by the caller's run loop in the next slice)."""
    from packages.quantum.paper_endpoints import _stage_order_internal
    from packages.quantum.services.analytics_service import AnalyticsService
    from packages.quantum.models import TradeTicket

    analytics = AnalyticsService(supabase)
    portfolio_id = portfolio["id"]
    out: Dict[str, Any] = {}
    for arm in ("A", "B"):
        ticket = TradeTicket(
            symbol=candidate["symbol"],
            quantity=int(candidate["quantity"]),
            order_type="limit",
            limit_price=round(float(candidate["limit_price"]), 2),
            strategy_type="custom",
            source_engine=f"paper_shadow_open_{arm.lower()}",
            legs=candidate["legs"],
        )
        order_id = _stage_order_internal(
            supabase, analytics, user_id, ticket, portfolio_id_arg=portfolio_id,
        )
        out[f"arm_{arm.lower()}"] = _submit_staged(supabase, order_id, user_id)
    return out


def close_arm(supabase, user_id: str, position: Dict[str, Any], reason: str, portfolio_id: str) -> Dict[str, Any]:
    """Close one arm's paper_shadow position through the single door. Builds the
    close ticket with the same convention `_close_position` uses (invert legs;
    is_credit_close when selling a long debit spread → #999's negative-credit
    sign is applied by build_alpaca_order_request inside guarded_paper_submit),
    stages via the canonical `_stage_order_internal`, then submits through the
    single door. Reuses #999's close-sign convention and the core stager (H13)."""
    from packages.quantum.paper_endpoints import _stage_order_internal
    from packages.quantum.services.analytics_service import AnalyticsService
    from packages.quantum.models import TradeTicket

    qty = float(position["quantity"])
    abs_qty = abs(int(qty))
    orig_legs = position.get("legs") or []
    close_legs = []
    for leg in orig_legs:
        orig_action = leg.get("action") or leg.get("side") or "buy"
        inverted = "sell" if orig_action == "buy" else "buy"
        close_legs.append({
            "symbol": leg.get("symbol") or leg.get("occ_symbol") or "",
            "action": inverted,
            "quantity": abs_qty,
            "type": leg.get("type", "call"),
            "strike": leg.get("strike"),
            "expiry": leg.get("expiry"),
        })
    is_credit_close = (qty > 0) and (len(close_legs) >= 2)
    exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)

    ticket = TradeTicket(
        symbol=position["symbol"],
        quantity=abs_qty,
        order_type="limit",
        limit_price=round(exit_price, 2),
        strategy_type="custom",
        source_engine=f"paper_shadow_close:{reason}",
        legs=close_legs,
        is_credit_close=is_credit_close,
    )
    order_id = _stage_order_internal(
        supabase, AnalyticsService(supabase), user_id, ticket,
        portfolio_id_arg=portfolio_id, position_id=position["id"],
    )
    return _submit_staged(supabase, order_id, user_id)


def manage_arm(
    position: Dict[str, Any],
    arm: str,
    *,
    underlying_spot: Optional[float] = None,
    dte: Optional[int] = None,
    premium_conditions: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Decide whether an arm should close NOW, by its OWN rule (independent of
    the other arm — the timing divergence is the D6 data):
      - arm 'A' → the premium-% champion exit (reuse `evaluate_position_exit`).
      - arm 'B' → the canonical geometry policy (`geometry_exit_decision`).
    Returns (should_close, reason). Pure decision — the caller acts via
    `close_arm` (the single door)."""
    if arm == "A":
        from packages.quantum.services.paper_exit_evaluator import evaluate_position_exit
        reason = evaluate_position_exit(position, conditions=premium_conditions)
        return (bool(reason), f"premium:{reason}" if reason else "hold")
    if arm == "B":
        decision, reason = geometry_exit_decision(position, underlying_spot, dte)
        return (decision in ("take_profit", "stop"), reason)
    raise ValueError(f"unknown arm {arm!r} (expected 'A' or 'B')")
