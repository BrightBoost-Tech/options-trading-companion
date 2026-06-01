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
