"""High-EV-gated marketable-from-start LIVE entry pricing (flag-gated, OFF).

Purpose (2026-06-04 fill-aggression diagnostic): passive combo-mid DAY
limits fill ~12% live (3/25, all same-second; resting almost never
converts), which leaves the live-validation channel dark (~1 fill / 5
weeks — PR #908 mleg-close validation, the end-to-end small-tier
entry→manage→exit cycle, real fee/slippage measurement) and biases the
live book to the instant-marketable subset. This lever crosses toward the
combo NATURAL — but ONLY for candidates whose net EV clearly covers the
cross (the high-EV gate), and ONLY on the live path.

What this is NOT:
  - NOT step-pricing / a reprice ladder / watchdog-retry infrastructure
    (deferred — modeled at ~$12/wk over this, needs new live-path
    execution-loop code).
  - NOT a shadow/TCM change (#1017 owns shadow fill realism), NOT D6,
    NOT sizing/selection/risk.

Hard rules implemented here:
  - Flag default OFF: submission byte-identical to today (passive mid);
    the would-be decision is still computed + logged for observation.
  - High-EV gate: net EV >= K x the actual cross cost (K is a named,
    env-calibratable assumption, default 3.0).
  - Never cross PAST natural (cap at natural, rounded to the cent).
  - Budget recheck AT the marketable price (not mid): if the higher entry
    cost would exceed the per-trade risk budget, do NOT upgrade — submit
    the unchanged passive-mid order (which is within ceiling, = today).
  - No-quote => no aggression: if the per-leg NBBO is unavailable, submit
    passive-mid with a logged reason. NEVER a blind/estimated cross with
    real money (the bounded-estimate fallback is a shadow-realism device,
    not a live-pricing one).
  - Fail-soft: any internal error leaves the order untouched (passive
    mid). This helper must never block a live submission.

Only ``requested_price`` changes on the order (the live limit). The
decision blob is persisted under ``tcm.marketable_entry`` so realized
fills can later be compared against the modeled cross (staged_mid vs
avg_fill_price).
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

FLAG_ENV = "MARKETABLE_ENTRY_ENABLED"

# ── FLAGGED ASSUMPTION (calibratable, not a magic number) ──────────────────
# Only pay the cross when net EV covers it at least K times over.
# Diagnostic (2026-06-04): K≈3 admits the June NFLX/BAC class (EV ~$80 vs
# ~$30 cross) and rejects the May micro-era F/AAL class (EV ~$13-15).
EV_CROSS_K_ENV = "MARKETABLE_ENTRY_EV_CROSS_K"
DEFAULT_EV_CROSS_K = 3.0


def is_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def ev_cross_k() -> float:
    try:
        return float(os.environ.get(EV_CROSS_K_ENV, DEFAULT_EV_CROSS_K))
    except (TypeError, ValueError):
        return DEFAULT_EV_CROSS_K


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _leg_action(leg: Dict[str, Any]) -> str:
    return str(leg.get("action") or leg.get("side") or "buy").lower()


def _valid_leg_quote(quote: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Return {bid, ask} when the quote is a usable two-sided NBBO, else None.
    The Polygon guardrail returns zeros on failure — zeros are 'missing'."""
    if not quote:
        return None
    bid = _f(quote.get("bid_price") or quote.get("bid"))
    ask = _f(quote.get("ask_price") or quote.get("ask"))
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return {"bid": bid, "ask": ask}


def _credit_width(legs: List[Dict[str, Any]]) -> Optional[float]:
    """Strike width for a 2-leg credit vertical (max_loss = width - credit)."""
    strikes = [_f(leg.get("strike")) for leg in legs]
    if len(strikes) != 2 or any(s is None for s in strikes):
        return None
    width = abs(strikes[0] - strikes[1])
    return width if width > 0 else None


def compute_marketable_decision(
    order_row: Dict[str, Any],
    suggestion: Optional[Dict[str, Any]],
    leg_quotes: Dict[str, Optional[Dict[str, Any]]],
    *,
    k: Optional[float] = None,
) -> Dict[str, Any]:
    """PURE decision: should this live entry's limit be upgraded to the
    combo natural, and at what price?

    Returns a decision dict (never raises):
      upgrade: bool — apply the marketable price
      reason:  why / why not (deterministic, loggable)
      staged_mid, natural, marketable_price, cross_per_share,
      cross_cost_total, gate {...}, budget {...}, quote_status
    """
    k = k if k is not None else ev_cross_k()
    decision: Dict[str, Any] = {
        "upgrade": False,
        "reason": None,
        "k": k,
        "staged_mid": None,
        "natural": None,
        "marketable_price": None,
        "cross_per_share": None,
        "cross_cost_total": None,
        "gate": None,
        "budget": None,
        "quote_status": None,
    }

    legs = (order_row.get("order_json") or {}).get("legs") or []
    qty = _f(order_row.get("requested_qty")) or 0.0
    staged_mid = _f(order_row.get("requested_price"))
    side = str(order_row.get("side") or "buy").lower()
    decision["staged_mid"] = staged_mid

    if not legs or qty <= 0 or not staged_mid or staged_mid <= 0:
        decision["reason"] = "order_shape_unusable"
        return decision

    # ── Per-leg NBBO (the natural needs long ask / short bid) ──────────────
    # No-quote => no aggression (0c): never a blind/estimated cross live.
    resolved = {}
    for leg in legs:
        sym = leg.get("symbol") or ""
        q = _valid_leg_quote(leg_quotes.get(sym))
        if q is None:
            decision["quote_status"] = f"missing:{sym}"
            decision["reason"] = "no_quote_no_aggression"
            return decision
        resolved[sym] = q
    decision["quote_status"] = "ok"

    # ── Combo natural: buy legs at the ask, sell legs at the bid ──────────
    natural_net = 0.0
    for leg in legs:
        q = resolved[leg.get("symbol") or ""]
        if _leg_action(leg) == "buy":
            natural_net += q["ask"]
        else:
            natural_net -= q["bid"]

    if side == "buy":
        # Net-debit combo: natural >= mid; cross UP, capped AT natural.
        natural = natural_net
        cross_per_share = natural - staged_mid
        marketable = round(natural, 2)
    else:
        # Net-credit combo: natural credit <= mid credit; cross DOWN.
        natural = -natural_net
        cross_per_share = staged_mid - natural
        marketable = max(0.01, round(natural, 2))
    decision["natural"] = round(natural, 4)

    if natural <= 0 and side == "buy":
        decision["reason"] = "natural_unusable"
        return decision
    if cross_per_share <= 0:
        # Market moved through the staged mid — the order is already
        # marketable as priced. Leave it (no repricing logic here).
        decision["reason"] = "already_marketable"
        return decision

    cross_cost_total = cross_per_share * qty * 100.0
    decision["cross_per_share"] = round(cross_per_share, 4)
    decision["cross_cost_total"] = round(cross_cost_total, 2)
    decision["marketable_price"] = marketable

    # ── High-EV gate: net EV must cover the ACTUAL cross K times over ─────
    sugg = suggestion or {}
    net_ev = _f(sugg.get("net_ev"))
    if net_ev is None:
        net_ev = _f(sugg.get("ev"))
    threshold = k * cross_cost_total
    gate_passed = net_ev is not None and net_ev >= threshold
    decision["gate"] = {
        "net_ev": net_ev,
        "threshold": round(threshold, 2),
        "k": k,
        "passed": bool(gate_passed),
    }
    if net_ev is None:
        decision["reason"] = "ev_unavailable"
        return decision
    if not gate_passed:
        decision["reason"] = "ev_gate_failed"
        return decision

    # ── Budget recheck AT the marketable price (36% ceiling discipline) ───
    sizing = sugg.get("sizing_metadata") or {}
    risk_budget = _f(sizing.get("risk_budget_dollars"))
    if side == "buy":
        max_loss_at_marketable = marketable * qty * 100.0
    else:
        width = _credit_width(legs)
        if width is None:
            decision["reason"] = "credit_width_unavailable"
            return decision
        max_loss_at_marketable = (width - marketable) * qty * 100.0
    budget_passed = risk_budget is not None and max_loss_at_marketable <= risk_budget
    decision["budget"] = {
        "risk_budget_dollars": risk_budget,
        "max_loss_at_marketable": round(max_loss_at_marketable, 2),
        "passed": bool(budget_passed),
    }
    if risk_budget is None:
        decision["reason"] = "risk_budget_unavailable"
        return decision
    if not budget_passed:
        # Over-ceiling at the marketable price: do NOT submit over-ceiling.
        # The unchanged passive-mid order is within ceiling (= today).
        decision["reason"] = "budget_ceiling_at_marketable"
        return decision

    decision["upgrade"] = True
    decision["reason"] = "marketable_applied"
    return decision


def _default_fetch_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Production per-leg NBBO: PolygonService via the existing staging
    retry helper (lazy import — paper_endpoints imports this module)."""
    from packages.quantum.market_data import PolygonService
    from packages.quantum.paper_endpoints import _fetch_quote_with_retry

    return _fetch_quote_with_retry(PolygonService(), symbol)


def maybe_apply_marketable_entry(
    supabase,
    order_row: Dict[str, Any],
    user_id: str,
    fetch_quote: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """LIVE-entry hook: compute (always) and apply (flag ON only) the
    high-EV-gated marketable price.

    Scope guards — returns the order untouched unless ALL hold:
      - entry order (suggestion_id set, no position_id — not a close),
      - execution_mode == 'alpaca_live' (the live account path; shadow
        cohorts were routed away upstream, D6 is alpaca-paper),
      - limit order with a positive requested_price.

    Flag OFF: submission byte-identical (requested_price untouched); the
    would-be decision is persisted to tcm.marketable_entry for observation.
    Fail-soft: any error logs + returns the order unchanged.
    """
    try:
        if not order_row.get("suggestion_id") or order_row.get("position_id"):
            return order_row
        if str(order_row.get("execution_mode") or "") != "alpaca_live":
            return order_row
        if str(order_row.get("order_type") or "limit") != "limit":
            return order_row
        if not _f(order_row.get("requested_price")):
            return order_row

        fetch = fetch_quote or _default_fetch_quote

        suggestion = None
        try:
            res = (
                supabase.table("trade_suggestions")
                .select("net_ev, ev, sizing_metadata")
                .eq("id", order_row["suggestion_id"])
                .single()
                .execute()
            )
            suggestion = res.data
        except Exception as sugg_err:
            logger.warning(
                "[MARKETABLE_ENTRY] suggestion fetch failed order=%s: %s",
                order_row.get("id"), sugg_err,
            )

        legs = (order_row.get("order_json") or {}).get("legs") or []
        leg_quotes = {}
        for leg in legs:
            sym = leg.get("symbol") or ""
            try:
                leg_quotes[sym] = fetch(sym)
            except Exception as q_err:
                logger.warning(
                    "[MARKETABLE_ENTRY] leg quote fetch failed %s: %s", sym, q_err
                )
                leg_quotes[sym] = None

        decision = compute_marketable_decision(order_row, suggestion, leg_quotes)
        flag_on = is_enabled()
        applied = bool(flag_on and decision["upgrade"])
        decision["flag_on"] = flag_on
        decision["mode"] = "applied" if applied else "would_be"

        logger.info(
            "[MARKETABLE_ENTRY] order=%s mode=%s reason=%s mid=%s natural=%s "
            "marketable=%s cross_total=%s gate=%s budget=%s quote=%s",
            order_row.get("id"), decision["mode"], decision["reason"],
            decision["staged_mid"], decision["natural"],
            decision["marketable_price"], decision["cross_cost_total"],
            decision["gate"], decision["budget"], decision["quote_status"],
        )

        update: Dict[str, Any] = {
            "tcm": {**(order_row.get("tcm") or {}), "marketable_entry": decision},
        }
        if applied:
            update["requested_price"] = decision["marketable_price"]

        try:
            supabase.table("paper_orders").update(update).eq(
                "id", order_row["id"]
            ).execute()
        except Exception as persist_err:
            logger.error(
                "[MARKETABLE_ENTRY] decision persist failed order=%s: %s",
                order_row.get("id"), persist_err,
            )
            if applied:
                # The DB row must match what we submit; if we can't persist
                # the upgraded price, do NOT submit it (fail back to mid).
                return order_row

        order_row["tcm"] = update["tcm"]
        if applied:
            order_row["requested_price"] = decision["marketable_price"]
        return order_row
    except Exception as e:  # fail-soft: never block a live submission
        logger.error(
            "[MARKETABLE_ENTRY] failed (passive mid preserved) order=%s: %s",
            order_row.get("id"), e,
        )
        return order_row
