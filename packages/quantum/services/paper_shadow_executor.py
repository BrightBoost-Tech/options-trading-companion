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
        out[f"arm_{arm.lower()}"] = {
            "order_id": order_id,
            "result": _submit_staged(supabase, order_id, user_id),
        }
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
    # Unsigned limit + direction via the canonical helper (06-11: a signed
    # short-structure mark passed raw produced an unfillable negative-limit
    # debit close on the live path; the shadow twin keeps the same seam).
    from packages.quantum.services.paper_exit_evaluator import _close_limit_and_direction
    exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)
    close_limit, is_credit_close = _close_limit_and_direction(
        exit_price, qty, len(close_legs)
    )

    ticket = TradeTicket(
        symbol=position["symbol"],
        quantity=abs_qty,
        order_type="limit",
        limit_price=round(close_limit, 2),
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


# ── Idempotent run loop (the state machine over paper_shadow_pairs) ─────────
# A repeating loop that must NOT corrupt its own experiment: every action is
# gated on the pair's persisted state. The pair row is BOTH the state machine
# and the D6 realized record. Submission stays through the single door
# (open_pair / close_arm → guarded_paper_submit); only READS (own-fill polling)
# build the dedicated client directly.

PAIRS_TABLE = "paper_shadow_pairs"
CONCURRENCY_CAP = 4  # 3–5 paired positions
_ACTIVE_STATES = ("pending_open", "open", "closing")


def _guarded_get_order(alpaca_order_id: str) -> Dict[str, Any]:
    """Account-guarded READ of an order's status via the dedicated paper client.
    Reads only (no order placed) — submission stays through guarded_paper_submit.
    Still asserts PA3I8CYLXBOS so reads can't even touch the live account."""
    client = build_paper_client()
    assert_paper_account(client)
    return client.get_order(alpaca_order_id)


def _pairs_in(supabase, user_id: str, cycle_date: str, states) -> list:
    return (supabase.table(PAIRS_TABLE).select("*")
            .eq("user_id", user_id).eq("cycle_date", cycle_date)
            .in_("pair_state", list(states)).execute().data) or []


def _update_pair(supabase, pair_id: str, fields: Dict[str, Any]) -> None:
    supabase.table(PAIRS_TABLE).update(fields).eq("id", pair_id).execute()


def _step_open(supabase, user_id, cycle_date, portfolio, candidates, cap) -> int:
    """Open new pairs up to the concurrency cap, skipping candidates already
    running (idempotent). Each open goes through the single door (open_pair)."""
    active = len(_pairs_in(supabase, user_id, cycle_date, _ACTIVE_STATES))
    room = max(0, cap - active)
    if room <= 0:
        return 0
    existing = {r["signal_key"] for r in (
        supabase.table(PAIRS_TABLE).select("signal_key")
        .eq("user_id", user_id).eq("cycle_date", cycle_date).execute().data or [])}
    opened = 0
    for cand in candidates:
        if opened >= room:
            break
        sk = cand["signal_key"]
        if sk in existing:
            continue  # idempotent: this candidate already has a pair this cycle
        result = open_pair(supabase, user_id, cand, portfolio)  # single door ×2
        supabase.table(PAIRS_TABLE).insert({
            "user_id": user_id, "portfolio_id": portfolio["id"],
            "cycle_date": cycle_date, "signal_key": sk, "pair_state": "pending_open",
            "arm_a_order_id": result["arm_a"]["order_id"], "arm_a_state": "pending_open",
            "arm_b_order_id": result["arm_b"]["order_id"], "arm_b_state": "pending_open",
            "synthetic_capital": SYNTHETIC_TIER_CAPITAL,
        }).execute()
        existing.add(sk)
        opened += 1
    return opened


def _step_poll_open_fills(supabase, user_id, cycle_date, portfolio) -> None:
    """pending_open arms whose open order filled → commit_open_fill (create the
    position) → arm 'open'. When both arms open → pair 'open'. Gated: only acts
    on arms still pending_open with no position yet."""
    for pair in _pairs_in(supabase, user_id, cycle_date, ["pending_open"]):
        upd: Dict[str, Any] = {}
        for arm in ("a", "b"):
            if pair[f"arm_{arm}_state"] != "pending_open" or pair.get(f"arm_{arm}_position_id"):
                continue
            res = _poll_arm_fill(supabase, pair[f"arm_{arm}_order_id"], portfolio, is_close=False)
            if res and res.get("filled"):
                upd[f"arm_{arm}_position_id"] = res["position_id"]
                upd[f"arm_{arm}_entry_price"] = res.get("price")
                upd[f"arm_{arm}_state"] = "open"
        new_a = upd.get("arm_a_state", pair["arm_a_state"])
        new_b = upd.get("arm_b_state", pair["arm_b_state"])
        if new_a == "open" and new_b == "open":
            upd["pair_state"] = "open"
        if upd:
            _update_pair(supabase, pair["id"], upd)


def _step_manage(supabase, user_id, cycle_date, portfolio, market_fn) -> None:
    """open pairs: manage each open arm by its OWN rule; when it fires, close via
    the single door (close_arm) → arm 'closing'. Gated: only arms in 'open'."""
    for pair in _pairs_in(supabase, user_id, cycle_date, ["open"]):
        for arm, label in (("a", "A"), ("b", "B")):
            if pair[f"arm_{arm}_state"] != "open":
                continue
            position = _get_position(supabase, pair[f"arm_{arm}_position_id"])
            if not position:
                continue
            spot, dte, premium_conditions = market_fn(position)
            should_close, reason = manage_arm(
                position, label, underlying_spot=spot, dte=dte,
                premium_conditions=premium_conditions,
            )
            if should_close:
                close_arm(supabase, user_id, position, reason, portfolio["id"])  # door
                _update_pair(supabase, pair["id"], {
                    f"arm_{arm}_state": "closing", f"arm_{arm}_close_reason": reason,
                })


def _step_poll_close_fills(supabase, user_id, cycle_date, portfolio) -> None:
    """closing arms whose close order filled → reconcile_close_fill → arm
    'closed' with realized P&L. When both arms closed → pair 'closed'."""
    for pair in _pairs_in(supabase, user_id, cycle_date, ["open", "closing"]):
        upd: Dict[str, Any] = {}
        for arm in ("a", "b"):
            if pair[f"arm_{arm}_state"] != "closing":
                continue
            res = _poll_arm_fill(supabase, pair[f"arm_{arm}_position_id"], portfolio, is_close=True)
            if res and res.get("filled"):
                upd[f"arm_{arm}_state"] = "closed"
                upd[f"arm_{arm}_exit_price"] = res.get("price")
                upd[f"arm_{arm}_realized_pl"] = res.get("realized_pl")
                upd[f"arm_{arm}_closed_at"] = res.get("closed_at")
        new_a = upd.get("arm_a_state", pair["arm_a_state"])
        new_b = upd.get("arm_b_state", pair["arm_b_state"])
        if new_a == "closed" and new_b == "closed":
            upd["pair_state"] = "closed"
        if upd:
            _update_pair(supabase, pair["id"], upd)


def _step_record(supabase, user_id, cycle_date) -> int:
    """closed pairs → 'recorded' (idempotent: the row IS the D6 realized A/B
    record; the only action is the closed→recorded transition, done ONCE)."""
    recorded = 0
    for pair in _pairs_in(supabase, user_id, cycle_date, ["closed"]):
        _update_pair(supabase, pair["id"], {"pair_state": "recorded"})
        recorded += 1
    return recorded


# Broker/market seams (patched in tests; reuse #1007 own-fill primitives):
def _get_position(supabase, position_id: str) -> Optional[Dict[str, Any]]:
    if not position_id:
        return None
    res = supabase.table("paper_positions").select("*").eq("id", position_id).single().execute()
    return res.data


def _poll_arm_fill(supabase, ref_id: str, portfolio: Dict[str, Any], *, is_close: bool) -> Optional[Dict[str, Any]]:
    """Own-fill polling for ONE arm via the dedicated paper client (read-only).
    On an OPEN-order fill → commit_open_fill (create position). On a CLOSE-order
    fill → reconcile_close_fill. Returns a dict with filled/price/position_id (or
    realized_pl/closed_at) or None. Detects ONLY the executor's own paper_shadow
    orders (it is only ever called with the executor's tracked ids)."""
    # Open path: ref_id is the open order id. Close path: ref_id is the
    # position id; find its in-flight close order.
    if not is_close:
        row = supabase.table("paper_orders").select("*").eq("id", ref_id).single().execute().data
    else:
        row = (supabase.table("paper_orders").select("*")
               .eq("position_id", ref_id).eq("side", "sell")
               .in_("status", ["submitted", "working", "filled"]).execute().data or [None])[0]
    if not row or not row.get("alpaca_order_id"):
        return None
    alpaca_order = _guarded_get_order(row["alpaca_order_id"])
    if (alpaca_order or {}).get("status") != "filled":
        return None
    price = float(alpaca_order.get("filled_avg_price") or 0)
    if not is_close:
        row["filled_qty"] = float(alpaca_order.get("filled_qty") or 0)
        row["avg_fill_price"] = price
        commit = commit_open_fill(supabase, row, portfolio)
        return {"filled": True, "position_id": commit.get("position_id"), "price": price}
    reconcile_close_fill(supabase, ref_id, row, alpaca_order)
    pos = _get_position(supabase, ref_id) or {}
    return {"filled": True, "price": price, "realized_pl": pos.get("realized_pl"),
            "closed_at": alpaca_order.get("filled_at")}


def run_paper_shadow_cycle(
    supabase, user_id: str, *, cycle_date: str, select_fn, market_fn,
    concurrency_cap: int = CONCURRENCY_CAP,
) -> Dict[str, Any]:
    """The executor's idempotent cycle. Flag-gated; a no-op when OFF. Each step
    is gated on the pair's persisted state, so re-running a cycle changes nothing
    it shouldn't (no re-open / over-cap / double-close / re-record). Every order
    routes through the single door via open_pair / close_arm.

    select_fn() -> list of candidate dicts (each with at least signal_key,
    symbol, quantity, limit_price, legs), sized at synthetic-tier capital.
    market_fn(position) -> (underlying_spot, dte, premium_conditions) for manage.
    """
    if not is_enabled():
        return {"ran": False, "reason": "flag_off"}
    portfolio = get_or_create_shadow_portfolio(supabase, user_id)
    opened = _step_open(supabase, user_id, cycle_date, portfolio, select_fn() or [], concurrency_cap)
    _step_poll_open_fills(supabase, user_id, cycle_date, portfolio)
    _step_manage(supabase, user_id, cycle_date, portfolio, market_fn)
    _step_poll_close_fills(supabase, user_id, cycle_date, portfolio)
    recorded = _step_record(supabase, user_id, cycle_date)
    return {"ran": True, "opened": opened, "recorded": recorded}


def _adapt_candidate(cand: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Best-effort adapt a rank_and_select candidate → executor shape. Returns
    None (skipped) if the required fields aren't present — SAFE: a skipped
    candidate just isn't opened. Never raises."""
    try:
        legs = cand.get("legs")
        symbol = cand.get("symbol") or cand.get("ticker") or cand.get("underlying")
        price = (cand.get("limit_price") or cand.get("entry_price")
                 or cand.get("net_debit") or cand.get("avg_entry_price"))
        qty = int(cand.get("contracts") or cand.get("quantity") or 1)
        if not (legs and symbol and price):
            return None
        strikes = "_".join(str(l.get("strike")) for l in legs if isinstance(l, dict))
        signal_key = f"{symbol}:{strikes}:{cand.get('expiry') or cand.get('expiration') or ''}"
        return {"signal_key": signal_key, "symbol": symbol, "quantity": qty,
                "limit_price": float(price), "legs": legs}
    except Exception:
        return None


def run_paper_shadow_cycle_default(supabase, user_id, scout_results, regime, cycle_date) -> Dict[str, Any]:
    """The production wrapper called by run_midday_cycle's flag-gated hook.
    Builds a DEFENSIVE synthetic-tier select_fn (re-rank the already-computed
    scout_results at SYNTHETIC_TIER_CAPITAL — reuse, no re-scan) + a market_fn,
    then runs the idempotent cycle. Best-effort + fail-soft: any selection error
    yields no opens (safe), never a bad/live order."""

    def _select():
        try:
            from packages.quantum.services.analytics.small_account_compounder import (
                SmallAccountCompounder,
            )
            ranked = SmallAccountCompounder.rank_and_select(
                candidates=list(scout_results or []),
                capital=SYNTHETIC_TIER_CAPITAL,
                risk_budget=SYNTHETIC_TIER_CAPITAL,
                regime=str(regime or "normal"),
            )
            out = [_adapt_candidate(c) for c in (ranked or [])]
            return [c for c in out if c]
        except Exception as e:  # selection must never break the cycle
            logger.warning("[PAPER_SHADOW] synthetic selection failed (no opens): %s", e)
            return []

    def _market(position):
        # Best-effort spot/dte + premium-% cohort conditions for manage_arm.
        spot, dte, premium_conditions = None, None, None
        try:
            from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
            snap = MarketDataTruthLayer().snapshot_many([position.get("symbol")])
            q = (snap.get(position.get("symbol")) or {}).get("quote", {})
            bid, ask = float(q.get("bid") or 0), float(q.get("ask") or 0)
            spot = (bid + ask) / 2.0 if (bid and ask) else (float(q.get("mid") or 0) or None)
        except Exception:
            pass
        try:
            from packages.quantum.services.paper_exit_evaluator import (
                build_exit_conditions, days_to_expiry,
            )
            from packages.quantum.policy_lab.config import load_cohort_configs
            dte = days_to_expiry(position)
            cfgs = load_cohort_configs(user_id, supabase) or {}
            cfg = cfgs.get("aggressive") or next(iter(cfgs.values()), None)
            if cfg:
                premium_conditions = build_exit_conditions(
                    target_profit_pct=cfg.target_profit_pct, stop_loss_pct=cfg.stop_loss_pct,
                    min_dte_to_exit=cfg.min_dte_to_exit)
        except Exception:
            pass
        return (spot, dte, premium_conditions)

    return run_paper_shadow_cycle(
        supabase, user_id, cycle_date=cycle_date, select_fn=_select, market_fn=_market,
    )
