"""TCM v2 PROPOSAL — routing-aware commission, OBSERVE-ONLY dual-run.

A VERSIONED proposed cost model that sits BESIDE the frozen current
``execution.transaction_cost_model.TransactionCostModel`` (NEVER replaces it).
It changes exactly ONE component — commission — and only where the broker
evidences a different truth than the frozen fee model. Everything else
(slippage / spread) is carried over from the current model UNCHANGED, because
only commission is evidenced tonight.

WHY (evidence pin — realized-cost study, consumer #3, PR #1273 merged):
  The frozen TCM charges ``max(qty * commission_per_contract, min_fee)`` (0.65
  $/contract) at stage REGARDLESS of routing. But BROKER-routed options fills
  carry the REAL Alpaca commission the ``alpaca_fill_reconciler`` stamps, which
  is $0 (zero-commission options). Verified read-only 2026-07-18: on ALL 42
  broker-routed FILLED orders ``paper_orders.fees_usd == 0`` and it NEVER
  equals ``tcm.fees_usd`` (0/42). The study's
  ``entry_realized_commission_vs_tcm_estimate`` mean is −1.55 USD — the frozen
  model over-charges commission for the zero-fee options routing. (CLAUDE.md §5
  still reads "real costs are fees ~$1–2/round-trip"; that doctrine line
  PREDATES the $0-commission evidence — this proposal is the correction, staged
  observe-only for the owner to adjudicate.)

WHAT (routing-aware commission):
  * BROKER-routed options (``execution_mode`` alpaca_paper/alpaca_live AND the
    portfolio is ``live_eligible`` → the order gets an ``alpaca_order_id`` and a
    broker fill) → commission = ``$0.00`` (broker truth). The reconciler stamps
    NO separate regulatory/exchange fee either: ``fees_usd`` is the whole
    commission+fees roll-up and it is 0 on all 42 broker fills. Source label
    ``broker_zero_commission_options``.
  * INTERNAL / SHADOW fills (internal_paper / shadow_only) → the model's
    SYNTHETIC estimate, explicitly LABELED as synthetic (source
    ``synthetic_estimate``). Internal fills have no broker to pay; the frozen
    fee estimate stands as the internal-fill charge, exactly as
    ``paper_endpoints._compute_fill_deltas`` already applies it.

HONESTY (H9 both-ends):
  * Commission is qty-based and independent of the quote → always computable by
    routing, entries AND exits.
  * Slippage / spread are CARRIED from the current model. When the current
    model used its missing-quote FALLBACK (fabricated 0.99/1.01 band), those
    two components are fallback-derived, not real NBBO → this proposal types
    them UNAVAILABLE (never carries a fabricated spread as if evidenced).
  * The REALIZED commission is UNAVAILABLE at the stage seam by construction
    (``no_broker_fill_pre_execution``). It joins AFTER the fact at close via the
    broker fill — see ``realized_commission_when_available`` (mirrors the
    study's ``_broker_routed`` predicate exactly).

OBSERVE-ONLY / promotion gate:
  This module feeds NO decision. The selector / ranker / gate / executor keep
  reading the FROZEN model's outputs; the dual-run only ADDS a sibling record
  for later comparison. ``ENABLE_LIVE_TCM_MODEL`` is the (future) promotion
  switch — it defaults false and is NOT read here or anywhere in the decision
  path. Promotion is owner-gated and documented in
  ``docs/specs/tcm_v2_promotion_packet.md`` (references the existing convergence
  conventions — the #1051 8-close rule / the Phase-3 10–15-fills gate — never a
  number invented here).

PURITY: no scanner/ranker/gate/executor import touches this module; it takes
plain values and returns a plain dict. It never raises on a partial input.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

VERSION = "tcm_v2_proposal/0.1.0"

# --- routing shapes ----------------------------------------------------------
ROUTING_BROKER = "broker_alpaca_options"
ROUTING_SHADOW = "shadow"
ROUTING_INTERNAL = "internal"

_ALPACA_EXEC_MODES = frozenset({"alpaca_paper", "alpaca_live"})
_LIVE_ROUTING = "live_eligible"
_SHADOW_ROUTING = "shadow_only"

# --- commission sources ------------------------------------------------------
COMMISSION_SOURCE_BROKER = "broker_zero_commission_options"
COMMISSION_SOURCE_SYNTHETIC = "synthetic_estimate"

# Broker truth: verified read-only 2026-07-18 (realized_cost_study consumer #3).
# 42/42 broker-routed FILLED options orders carry paper_orders.fees_usd == 0 and
# it never equals tcm.fees_usd (0/42). The reconciler stamps no separate
# regulatory/exchange fee — fees_usd is the whole commission+fees roll-up = $0.
BROKER_OPTIONS_COMMISSION_USD = 0.0

_EVIDENCE = (
    "#1273 realized_cost_study consumer #3: broker-routed options fills carry "
    "$0 real Alpaca commission (fees_usd=0 on 42/42; never == tcm.fees_usd); "
    "the frozen TCM over-charges ~0.65$/contract one-way; "
    "entry_realized_commission_vs_tcm_estimate mean −1.55 USD"
)


# --- small numeric helper ----------------------------------------------------
def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf → not a value
        return None
    return f


def _component(
    usd: Optional[float], available: bool, reason: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """A typed money component: never a fabricated zero — an unavailable
    component carries ``usd=None`` + a reason, never 0.0."""
    out: Dict[str, Any] = {"usd": usd, "available": available}
    if reason is not None:
        out["reason"] = reason
    out.update(extra)
    return out


# --- routing classification (stage-time predictor) ---------------------------
def classify_routing(
    execution_mode: Any, routing_mode: Any
) -> str:
    """Predict the FILL VENUE at stage time from the two authoritative signals
    already in hand at the stamp site (no extra DB call):

      * ``execution_mode`` — get_execution_mode() (alpaca_paper/alpaca_live vs
        internal_paper/shadow).
      * ``routing_mode`` — the portfolio's routing_mode (``live_eligible`` for
        the live champion, ``shadow_only`` for shadow cohorts).

    BROKER iff an alpaca execution mode AND a live_eligible portfolio — this is
    the stage-time proxy for "the order will get an alpaca_order_id + a broker
    fill", mirroring ``execution_router.should_submit_to_broker`` (which gates
    on routing_mode == 'live_eligible') WITHOUT re-querying. It is deliberately
    INDEPENDENT of ``submit_to_broker`` (which is single-submitter OWNERSHIP,
    not venue: a live CLOSE is staged submit_to_broker=False yet the caller
    still routes it to the broker) and of ``dry_run`` (a temporary env toggle
    that changes WHEN, not WHERE, the alpaca order lands).

    SHADOW when routing_mode is exactly ``shadow_only`` (the value production
    emits — matches ``paper_endpoints._is_shadow_routing``). Everything else →
    INTERNAL. Unknown/future routing values fall to INTERNAL (synthetic
    commission), never silently to broker-$0 — the fail-safe direction for a
    cost proposal (never understate a cost on an unrecognized route)."""
    em = str(execution_mode or "").strip().lower()
    rm = str(routing_mode or "").strip().lower()
    if em in _ALPACA_EXEC_MODES and rm == _LIVE_ROUTING:
        return ROUTING_BROKER
    if rm == _SHADOW_ROUTING:
        return ROUTING_SHADOW
    return ROUTING_INTERNAL


def is_broker_routed(routing: str) -> bool:
    return routing == ROUTING_BROKER


# --- the dual-run record -----------------------------------------------------
def build_proposal(
    *,
    current_tcm: Optional[Mapping[str, Any]],
    routing: str,
    leg_count: Optional[int],
    quantity: Optional[float],
    entry_or_close: str,
    submit_to_broker: Optional[bool] = None,
    dry_run: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute the PROPOSED routing-aware cost model beside the frozen current
    one and return the observe-only dual-run record. Pure; never raises on a
    partial ``current_tcm``.

    Commission is the ONLY evidenced change: broker-routed → $0 (broker truth),
    internal/shadow → the current model's synthetic estimate (labeled). Slippage
    / spread are carried from the current model UNCHANGED, typed UNAVAILABLE
    when the current model used its missing-quote fallback (H9). The realized
    value is UNAVAILABLE here (joins at close — see
    ``realized_commission_when_available``)."""
    ct: Mapping[str, Any] = current_tcm if isinstance(current_tcm, Mapping) else {}

    cur_commission = _coerce_float(ct.get("fees_usd"))
    cur_spread = _coerce_float(ct.get("expected_spread_cost_usd"))
    cur_slip = _coerce_float(ct.get("expected_slippage_usd"))
    missing_quote = bool(ct.get("missing_quote"))
    used_fallback = bool(ct.get("used_fallback"))

    # --- commission by routing (the only evidenced component) ---------------
    if routing == ROUTING_BROKER:
        proposed_commission: Optional[float] = BROKER_OPTIONS_COMMISSION_USD
        commission_source = COMMISSION_SOURCE_BROKER
        commission_available = True
        commission_reason: Optional[str] = None
    else:
        # internal / shadow → the synthetic estimate = the current model's fee,
        # labeled synthetic. Unavailable only if the current model had no fee.
        proposed_commission = cur_commission
        commission_source = COMMISSION_SOURCE_SYNTHETIC
        commission_available = cur_commission is not None
        commission_reason = None if commission_available else "current_commission_unavailable"

    # --- commission delta: proposed − current (COMPARE, never SUM) ----------
    if commission_available and proposed_commission is not None and cur_commission is not None:
        commission_delta: Optional[float] = proposed_commission - cur_commission
        delta_available = True
        delta_reason: Optional[str] = None
    else:
        commission_delta = None
        delta_available = False
        delta_reason = (
            "current_commission_unavailable" if cur_commission is None
            else "proposed_commission_unavailable"
        )

    # --- slippage / spread carried from current, H9-honest on missing quote -
    if missing_quote:
        spread_comp = _component(None, False, "quote_missing_carried_from_current")
        slip_comp = _component(None, False, "quote_missing_carried_from_current")
    else:
        spread_comp = _component(
            cur_spread, cur_spread is not None,
            None if cur_spread is not None else "not_persisted_in_current",
        )
        slip_comp = _component(
            cur_slip, cur_slip is not None,
            None if cur_slip is not None else "not_persisted_in_current",
        )

    return {
        "model_version": VERSION,
        "routing": routing,
        "entry_or_close": entry_or_close,
        "leg_count": leg_count,
        "quantity": quantity,
        "source": commission_source,
        "current_model": {
            "commission_usd": _component(
                cur_commission, cur_commission is not None,
                None if cur_commission is not None else "not_persisted_in_current",
            ),
            "spread_cost_usd": _component(cur_spread, cur_spread is not None),
            "slippage_usd": _component(cur_slip, cur_slip is not None),
            "tcm_version": ct.get("tcm_version"),
        },
        "proposed_model": {
            "commission_usd": _component(
                proposed_commission, commission_available, commission_reason,
                source=commission_source,
            ),
            # carried from current UNCHANGED (only commission is evidenced).
            "spread_cost_usd": spread_comp,
            "slippage_usd": slip_comp,
            "carried_unchanged_from_current": ["spread_cost_usd", "slippage_usd"],
        },
        "delta": {
            "commission_usd": commission_delta,
            "available": delta_available,
            "reason": delta_reason,
            "note": ("proposed − current commission (TOTAL USD, one-way); "
                     "negative = the proposal charges LESS (broker $0 vs the "
                     "frozen fee estimate)"),
        },
        "realized_when_available": {
            "available": False,
            "reason": "no_broker_fill_pre_execution",
            "join": ("joins at close via the broker fill: execution_mode in "
                     "{alpaca_paper,alpaca_live} AND alpaca_order_id present AND "
                     "broker_status='filled' → paper_orders.fees_usd; see "
                     "realized_commission_when_available + "
                     "scripts/analytics/realized_cost_study.py"),
        },
        "context": {
            "missing_quote": missing_quote,
            "used_fallback": used_fallback,
            "dry_run": bool(dry_run) if dry_run is not None else None,
            "submit_to_broker": bool(submit_to_broker) if submit_to_broker is not None else None,
        },
        "evidence": _EVIDENCE,
        "observe_only": True,
    }


# --- realized close-join (the deferred realized side) ------------------------
def realized_commission_when_available(
    *,
    execution_mode: Any,
    has_alpaca_order_id: Any,
    broker_status: Any,
    fees_usd: Any,
) -> Dict[str, Any]:
    """Routing-aware REALIZED commission for a FILLED order row — the value the
    stage-time ``realized_when_available`` field joins to at close.

    Mirrors ``scripts/analytics/realized_cost_study._broker_routed`` EXACTLY:
    a genuine broker execution is an alpaca execution_mode AND a broker order id
    AND ``broker_status='filled'``. Broker-routed → KNOWN (= ``fees_usd``, $0
    options today, source ``broker_reconciler``). Internal / non-broker →
    typed UNAVAILABLE (``fees_usd`` is estimate-or-ambiguous there), never
    fabricated. Reporting the broker-known value UNAVAILABLE would be
    OVER-abstention (the mirror image of H9)."""
    em = str(execution_mode or "").strip().lower()
    broker = (
        em in _ALPACA_EXEC_MODES
        and bool(has_alpaca_order_id)
        and str(broker_status or "").strip().lower() == "filled"
    )
    if not broker:
        return _component(
            None, False, "internal_fill_commission_not_broker_stamped",
            source="internal_fill",
        )
    fee = _coerce_float(fees_usd)
    if fee is None:
        return _component(
            None, False, "broker_routed_but_fees_missing",
            source="broker_reconciler",
        )
    return _component(abs(fee), True, source="broker_reconciler")
