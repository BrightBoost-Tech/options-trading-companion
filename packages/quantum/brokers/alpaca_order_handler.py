"""
Alpaca Order Handler — submit, poll, and reconcile order lifecycle.

Bridges the internal paper_orders table with Alpaca's order API.
Production-grade: 3-attempt submission, 10s ack timeout, 90s idle watchdog,
needs_manual_review fallback.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from packages.quantum.brokers.alpaca_client import (
    AlpacaClient,
    AlpacaError,
    AlpacaAuthError,
    polygon_to_alpaca,
    alpaca_to_polygon,
)
from packages.quantum.services.close_math import (
    compute_realized_pl,
    extract_close_legs,
    PartialFillDetected,
    MalformedFillData,
)
from packages.quantum.services.close_helper import (
    close_position_shared,
    PositionAlreadyClosed,
)

# Submission retry config
MAX_SUBMIT_ATTEMPTS = 3
ACK_TIMEOUT_SECONDS = 10.0
# Idle THRESHOLD for the entry-order watchdog — NOT the effective cancel
# time. The watchdog is polled inside poll_pending_orders, which runs on the
# alpaca_order_sync cadence (5-min cron + ad-hoc post-cycle runs), so an
# unfilled order is cancelled at the FIRST sync where idle > 90s — in
# practice up to ~6 minutes (e.g. the 2026-06-03 NFLX entry rested 292s).
# Cancel-only: there is NO resubmission/reprice after the cancel (that is
# the deliberately-deferred step-pricing execution layer — see the
# 2026-06-04 fill-mechanics diagnostic; #1018 changes entry pricing
# upstream instead). Empirically, live mid-limit entries fill instantly or
# never, so the precise window matters little — the price does.
IDLE_WATCHDOG_SECONDS = 90

# Terminal broker-reject classification (06-12). Rejection reasons that can
# never succeed by retrying — fail after the FIRST attempt, one alert, never
# hammer the gateway. NOTE: the 06-12 "30-retry storm" reading was itself a
# lying message — both retry layers interpolated their MAX constants into
# "after N attempts" regardless of actual count (fixed below with honest
# counts); actual behavior was 1 attempt. This classification makes
# terminal-no-retry explicit rather than incidental.
_TERMINAL_REJECT_MARKERS = (
    "42210000", "position intent mismatch",  # duplicate close — prior submission filled
    "sign-incoherent",                       # our own pre-submit coherence guards
    "insufficient",                          # buying power / qty available
    "extra_forbidden",                       # request-shape rejection
)
# Subset that means "a prior submission already filled/closed this position":
# the fill reconciler owns the row — marking needs_manual_review here RACES
# the reconciler and manufactures a false critical (06-12 SPY: the row was
# already filled when the duplicate's rejection marked it for review).
_DUPLICATE_CLOSE_MARKERS = ("42210000", "position intent mismatch")

logger = logging.getLogger(__name__)


def build_alpaca_order_request(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate an internal paper_orders row into an Alpaca order request.

    Reads order_json for legs, limit_price, side, and converts
    Polygon OCC symbols to Alpaca format.

    Close orders (position_id set): sets position_intent per leg
    (buy_to_close / sell_to_close) and clamps |limit_price| to ≥ 0.01
    for near-worthless spreads — sign-preserving so the credit close
    convention below isn't masked.

    Alpaca mleg sign convention (#101 fix, 2026-05-10): for multi-leg
    parent orders, limit_price is signed — positive = net debit (you
    pay), negative = net credit (you receive). When closing a long
    debit-opened spread by selling it back, the close produces credit
    and Alpaca's gateway instant-rejects positive limit_price as
    economically incoherent. paper_exit_evaluator marks such tickets
    with order_json.is_credit_close=True; we negate here. Pre-fix, the
    clamp at lines 86-93 forced negative→+0.01, masking the broken
    sign. Pre-fix, requested_price was always positive too, so the
    only path producing native-negative limit_price was the
    near-worthless-spread mark, which the +0.01 clamp covered. Both
    behaviors are preserved for non-credit-close orders.
    """
    order_json = order.get("order_json") or {}
    legs_data = order_json.get("legs") or []
    side = order.get("side") or order_json.get("side") or "buy"
    limit_price = round(float(order.get("requested_price") or order_json.get("limit_price") or 0), 2)
    qty = int(order.get("requested_qty") or order_json.get("contracts") or 1)

    # Detect close orders: position_id is set when closing an existing position
    is_close_order = bool(order.get("position_id"))
    is_credit_close = bool(order_json.get("is_credit_close")) if is_close_order else False
    # 06-11 incident: the sign convention applies to OPENS too. The first live
    # iron condors (net-credit structures) submitted +1.54/+1.43 and Alpaca's
    # live gateway instant-rejected both in 4ms — same class the #101 comment
    # below documents for closes. The stage seam classifies net direction
    # from validated leg mids and stamps order_json.is_credit_open.
    is_credit_open = bool(order_json.get("is_credit_open")) and not is_close_order

    alpaca_legs = []
    for i, leg in enumerate(legs_data):
        leg_symbol = leg.get("symbol") or leg.get("occ_symbol") or ""
        leg_side = leg.get("side") or leg.get("action") or side
        alpaca_leg = {
            "symbol": polygon_to_alpaca(leg_symbol),
            "side": leg_side,
            "qty": 1,  # Always 1 — contract count goes on parent order qty
        }

        # Set position_intent for close orders so Alpaca doesn't infer buy_to_open
        if is_close_order:
            if leg_side == "buy":
                alpaca_leg["position_intent"] = "buy_to_close"
            else:
                alpaca_leg["position_intent"] = "sell_to_close"

        logger.info(
            f"[BUILD_ALPACA_REQ] leg[{i}] raw_side={leg.get('side')!r} "
            f"raw_action={leg.get('action')!r} fallback_side={side!r} "
            f"→ leg_side={leg_side!r} is_close={is_close_order} "
            f"intent={alpaca_leg.get('position_intent', 'NONE')}"
        )
        alpaca_legs.append(alpaca_leg)

    # Apply Alpaca mleg credit-close sign BEFORE the worthless-spread clamp,
    # so |signed_price| < 0.01 still trips the clamp (preserving the original
    # protection) but a legitimate $1.86 credit becomes -$1.86 cleanly.
    if (is_credit_close or is_credit_open) and limit_price > 0:
        _flip_kind = "Credit-close" if is_credit_close else "Credit-open"
        logger.warning(
            f"[ALPACA_HANDLER] {_flip_kind} sign-flip: order={order.get('id')} "
            f"limit_price={limit_price} → {-limit_price} (Alpaca mleg convention: "
            f"positive=debit, negative=credit)"
        )
        limit_price = -limit_price

    # Close orders on near-worthless spreads can have ~zero mark; clamp the
    # MAGNITUDE to ≥ 0.01 so Alpaca accepts (you're paying/receiving a penny
    # to close). Sign is preserved — pre-2026-05-10 this clamped any
    # negative→+0.01 which masked the credit-close convention above.
    if is_close_order and 0 < abs(limit_price) < 0.01:
        clamp_target = -0.01 if limit_price < 0 else 0.01
        logger.warning(
            f"[ALPACA_HANDLER] Close order |limit_price|={abs(limit_price)} < 0.01 "
            f"(order={order.get('id')}). Clamping {limit_price} → {clamp_target}."
        )
        limit_price = clamp_target

    # Options must always be limit orders — Alpaca rejects market orders
    # outside market hours. Magnitude check, not sign — credit closes are
    # legitimately negative.
    # Pre-submit sign-coherence guard (06-11): a known-credit structure must
    # NEVER leave this function with a positive limit — the live gateway
    # instant-rejects it (close class: #101; open class: the 06-11 condors).
    # Unreachable given the flip above; pins the invariant against future
    # edits. Fail-loud beats a silent broker rejection.
    if (is_credit_close or is_credit_open) and limit_price > 0:
        raise ValueError(
            f"Sign-incoherent credit order: limit_price={limit_price} is "
            f"positive for a net-credit structure (is_credit_close="
            f"{is_credit_close}, is_credit_open={is_credit_open}). "
            f"Refusing to submit. Order ID: {order.get('id')}"
        )

    # The inverse guard (06-11 short-condor close incident): a CLOSE not
    # marked is_credit_close is a net-DEBIT order (buying the structure back)
    # and must never submit a negative limit. The signed close mark passed
    # raw produced −1.39 on a buy-to-close: Alpaca rejected the first submit,
    # then let the retry REST at a price that can never fill — which
    # satisfied the close-idempotency guards and DISARMED the close path.
    # Fail-loud beats a resting impossible order.
    if is_close_order and not is_credit_close and limit_price < 0:
        raise ValueError(
            f"Sign-incoherent debit close: limit_price={limit_price} is "
            f"negative for a close not marked is_credit_close (a buy-to-close "
            f"pays a debit; Alpaca mleg convention: positive=debit). "
            f"Refusing to submit. Order ID: {order.get('id')}"
        )

    if not limit_price or abs(limit_price) < 0.01:
        raise ValueError(
            f"Cannot submit options order without limit_price "
            f"(got {limit_price}). Order ID: {order.get('id')}"
        )

    # Time-in-force: read from the ticket (order_json), default "day".
    # Pre-GTC-profit-exit this was hardcoded "day" — every order the system
    # ever submitted was DAY (the volatility-trap "GTC" was rationale text
    # only). Only the GTC profit-limit placement (services/gtc_profit_exit)
    # sets "gtc"; anything else — entries, stop/target closes, force-closes —
    # still emits DAY (unknown values coerce to "day", never to "gtc").
    tif = str(order_json.get("time_in_force") or "day").lower()
    if tif not in ("day", "gtc"):
        tif = "day"

    return {
        "symbol": order_json.get("symbol") or order.get("symbol"),
        "legs": alpaca_legs,
        "qty": qty,  # Contract count on parent order, not on legs
        "order_type": "limit",
        "limit_price": limit_price,
        "time_in_force": tif,
    }


def submit_and_track(
    alpaca: AlpacaClient,
    supabase,
    order: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    Submit an internal order to Alpaca with production-grade reliability.

    - Up to 3 submission attempts with backoff
    - 10s acknowledgment check after each submission
    - Falls back to needs_manual_review after 3 failures (never silently drops)
    """
    order_id = order.get("id")
    num_legs = len((order.get("order_json") or {}).get("legs", []))
    last_error = None
    attempts_made = 0  # honest count for messages/alerts — never the MAX constant

    # Pre-cancel: if this is a close order, cancel any open Alpaca orders
    # for the same contract symbols to avoid held_for_orders rejection.
    is_close_order = bool(order.get("position_id"))
    if is_close_order:
        leg_symbols = [
            leg.get("symbol") or leg.get("occ_symbol") or ""
            for leg in ((order.get("order_json") or {}).get("legs") or [])
            if leg.get("symbol") or leg.get("occ_symbol")
        ]
        if leg_symbols:
            cancelled = alpaca.cancel_open_orders_for_symbols(leg_symbols)
            if cancelled:
                logger.info(
                    f"[ALPACA_HANDLER] Pre-cancel for close order={order_id}: "
                    f"cancelled {len(cancelled)} conflicting orders: {cancelled}"
                )

    for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
        try:
            req = build_alpaca_order_request(order)
            num_legs = len(req.get("legs", []))
            t_submit = time.monotonic()

            result = alpaca.submit_option_order(req)

            alpaca_order_id = result.get("alpaca_order_id")
            t_ack = time.monotonic() - t_submit

            # Silent failure detection: verify we got an order ID back
            if not alpaca_order_id:
                logger.error(
                    f"[ALPACA_HANDLER] Silent failure: submission returned no order ID "
                    f"(order={order_id}, attempt={attempt}/{MAX_SUBMIT_ATTEMPTS})"
                )
                last_error = "no_alpaca_order_id_returned"
                attempts_made = attempt
                if attempt < MAX_SUBMIT_ATTEMPTS:
                    time.sleep(1.0 * attempt)  # Brief backoff before retry
                    continue
                break

            # Log acknowledgment timing
            if t_ack > ACK_TIMEOUT_SECONDS:
                logger.warning(
                    f"[ALPACA_HANDLER] Slow ack: order={order_id} took {t_ack:.1f}s "
                    f"(threshold={ACK_TIMEOUT_SECONDS}s)"
                )

            supabase.table("paper_orders").update({
                "alpaca_order_id": alpaca_order_id,
                "execution_mode": "alpaca_paper" if alpaca.paper else "alpaca_live",
                "broker_status": result.get("status"),
                "broker_response": result,
                "status": "submitted",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()

            logger.info(
                f"[ALPACA_HANDLER] Order submitted: internal={order_id} "
                f"alpaca={alpaca_order_id} legs={num_legs} "
                f"status={result.get('status')} ack={t_ack:.2f}s "
                f"attempt={attempt}/{MAX_SUBMIT_ATTEMPTS}"
            )
            return {"status": "submitted", **result}

        except (AlpacaAuthError,) as e:
            # Auth errors already attempted re-auth inside _call_with_retry
            # If we're here, re-auth failed — no point retrying
            last_error = str(e)
            logger.error(
                f"[ALPACA_HANDLER] Auth failure (fatal): order={order_id} error={last_error}"
            )
            break

        except Exception as e:
            last_error = str(e)
            attempts_made = attempt
            logger.error(
                f"[ALPACA_HANDLER] Submit failed (attempt {attempt}/{MAX_SUBMIT_ATTEMPTS}): "
                f"order={order_id} legs={num_legs} error={last_error}"
            )
            err_lower = last_error.lower()
            # Duplicate-close: a prior submission already filled/closed this
            # position. Return WITHOUT marking needs_manual_review — the fill
            # reconciler owns the row (poll_pending_orders / order_sync via
            # the prior alpaca_order_id); marking here races it and produces
            # a false critical (06-12 SPY).
            if any(m in err_lower for m in _DUPLICATE_CLOSE_MARKERS):
                logger.warning(
                    f"[ALPACA_HANDLER] Position-intent-mismatch on order={order_id} — "
                    f"prior submission likely already filled. No retry, no "
                    f"manual-review mark; the fill reconciler owns this row."
                )
                return {
                    "status": "duplicate_close_prior_fill",
                    "attempts": attempts_made,
                    "error": last_error,
                }
            # Terminal rejects: will never succeed on retry — stop now; the
            # post-loop needs_manual_review + single critical alert handles it.
            if any(m in err_lower for m in _TERMINAL_REJECT_MARKERS):
                logger.error(
                    f"[ALPACA_HANDLER] Terminal reject on order={order_id} — "
                    f"not retrying (reason class matched): {last_error[:160]}"
                )
                break
            if attempt < MAX_SUBMIT_ATTEMPTS:
                backoff = 2.0 * attempt  # 2s, 4s
                logger.info(f"[ALPACA_HANDLER] Retrying in {backoff}s...")
                time.sleep(backoff)

    # Attempts exhausted or terminal — mark needs_manual_review (never
    # silently fail). Honest count: pre-06-12 these messages interpolated
    # MAX_SUBMIT_ATTEMPTS regardless of how many attempts actually ran (the
    # lying-message class — "after 3 attempts: ... after 10 attempts" on a
    # single-attempt terminal reject).
    logger.error(
        f"[ALPACA_HANDLER] Submission failed after {attempts_made} attempt(s) "
        f"(max {MAX_SUBMIT_ATTEMPTS}) for order={order_id}. "
        f"Marking needs_manual_review. Last error: {last_error}"
    )
    supabase.table("paper_orders").update({
        "broker_status": "needs_manual_review",
        "broker_response": {
            "error": last_error,
            "legs": num_legs,
            "attempts": attempts_made,
            "marked_at": datetime.now(timezone.utc).isoformat(),
        },
        "status": "needs_manual_review",
    }).eq("id", order_id).execute()

    # #98 fix (2026-05-01): emit critical alert immediately. The H5a alert at
    # paper_exit_evaluator.py:1226 only fires for raised exceptions, but
    # submit_and_track returns a dict on this path instead. Today's BAC ghost
    # position incident sat silent for 5+ hours because no alert covered the
    # dict-return failure mode. This alert catches ALL callers regardless of
    # how they handle the return value.
    try:
        from packages.quantum.observability.alerts import (
            alert, _get_admin_supabase,
        )
        alert(
            _get_admin_supabase(),
            user_id=user_id,
            alert_type="paper_order_marked_needs_manual_review",
            severity="critical",
            message=(
                f"Alpaca rejected order after {attempts_made} "
                f"attempt(s): {str(last_error)[:200]}"
            ),
            metadata={
                "function_name": "submit_and_track",
                "order_id": str(order_id),
                "attempts": attempts_made,
                "num_legs": num_legs,
                "last_error": str(last_error)[:500],
                "broker_status": "needs_manual_review",
                "is_close_order": is_close_order,
                "consequence": (
                    "Order will not retry. If this was a close order, the "
                    "linked paper_position will diverge from broker state — "
                    "broker may still hold position despite DB intent to "
                    "close. Manual reconciliation required."
                ),
                "operator_action_required": (
                    "1. Check the linked paper_position.status. If 'open', "
                    "verify broker state via Alpaca dashboard. "
                    "2. If broker position is open and intent was close: "
                    "manually close via Alpaca UI. "
                    "3. UPDATE paper_positions row to status='closed' with "
                    "appropriate realized_pl. "
                    "4. Investigate root cause from last_error (insufficient "
                    "options buying power, contract no longer tradable, "
                    "account restriction, position intent mismatch, etc.)."
                ),
            },
        )
    except Exception:
        # Alert path failure must NOT break the needs_manual_review marker
        # write or the function's return contract. Same precedent as H5a
        # site 9, H5b site 236, and PR #846 execution_router alert site.
        pass

    return {"status": "needs_manual_review", "error": last_error, "attempts": attempts_made}


def _close_position_on_fill(
    supabase,
    position_id: str,
    order: Dict[str, Any],
    alpaca_order: Dict[str, Any],
) -> None:
    """
    Close a paper_position when its Alpaca close order fills.

    PR #6 refactor. Delegates to the shared close-path pipeline:
        1. extract_close_legs (close_math.py) — normalize Alpaca shape
           to LegFill list. Raises PartialFillDetected / MalformedFillData
           on anomalies.
        2. compute_realized_pl (close_math.py) — canonical leg-level
           P&L. Sign-convention-safe without needing parent-level
           mleg flag. Same function 3 other handlers use.
        3. close_position_shared (close_helper.py) — atomic write to
           paper_positions with close_reason + fill_source + realized_pl
           + closed_at + quantity=0. Raises PositionAlreadyClosed on
           duplicate attempts (loud, not silent).

    Any exception from the pipeline results in a severity='critical'
    risk_alert + early return. No close action on anomalies. Caller
    (poll_pending_orders) continues processing other orders normally.

    Downstream side effects (paper_orders update, etc.) remain in
    poll_pending_orders' existing code — this helper only touches
    paper_positions per the Gap D decision.
    """
    filled_at_iso = (
        alpaca_order.get("filled_at") or datetime.now(timezone.utc).isoformat()
    )

    # Fetch position (unchanged from pre-PR-#6).
    pos_res = supabase.table("paper_positions") \
        .select("*") \
        .eq("id", position_id) \
        .single() \
        .execute()

    if not pos_res.data:
        logger.warning(
            f"[CLOSE_ON_FILL] Position {position_id[:8]} not found — "
            f"may already be closed"
        )
        return

    position = pos_res.data

    # Fast-path early return if already closed. close_position_shared
    # would also raise PositionAlreadyClosed here, but the fast path
    # skips the extract/compute work for the no-op case.
    if position.get("status") == "closed":
        logger.info(
            f"[CLOSE_ON_FILL] Position {position_id[:8]} already closed, skipping"
        )
        return

    raw_qty = float(position.get("quantity") or 0)
    if raw_qty == 0:
        logger.warning(
            f"[CLOSE_ON_FILL] Position {position_id[:8]} has quantity=0 "
            f"but status!='closed'; cannot derive spread_type. "
            f"Skipping close; manual review required."
        )
        _write_close_path_critical_alert(
            supabase, position, "derive_inputs",
            f"quantity=0 with status={position.get('status')!r}",
        )
        return

    qty_abs = abs(int(raw_qty))
    spread_type = "debit" if raw_qty > 0 else "credit"
    entry_price = Decimal(str(position.get("avg_entry_price") or 0))

    # Step 1: extract legs from Alpaca fill data.
    try:
        close_legs = extract_close_legs(alpaca_order)
    except (PartialFillDetected, MalformedFillData) as exc:
        _write_close_path_critical_alert(
            supabase, position, "extract_close_legs", str(exc),
        )
        return

    # Step 2: compute realized_pl via canonical leg-level math.
    try:
        realized_pl = compute_realized_pl(
            close_legs=close_legs,
            entry_price=entry_price,
            qty=qty_abs,
            spread_type=spread_type,
        )
    except PartialFillDetected as exc:
        _write_close_path_critical_alert(
            supabase, position, "compute_realized_pl", str(exc),
        )
        return

    # Step 3: atomic close via shared helper.
    #
    # close_reason='alpaca_fill_reconciler_standard' for all new
    # reconciler closes. The historical value
    # 'alpaca_fill_reconciler_sign_corrected' is preserved in the
    # enum for the one existing row (PYPL cfe69b28, manual UPDATE
    # 2026-04-20) but not written here — compute_realized_pl
    # handles sign conventions automatically post-PR #790.
    try:
        closed_at_dt = _parse_iso_timestamp(filled_at_iso)
        close_position_shared(
            supabase=supabase,
            position_id=position_id,
            realized_pl=realized_pl,
            close_reason="alpaca_fill_reconciler_standard",
            fill_source="alpaca_fill_reconciler",
            closed_at=closed_at_dt,
        )
    except PositionAlreadyClosed as exc:
        _write_close_path_critical_alert(
            supabase, position, "close_position_shared", str(exc),
            extra_metadata={
                "existing_close_reason": exc.existing_close_reason,
                "existing_fill_source": exc.existing_fill_source,
                "existing_closed_at": exc.existing_closed_at,
            },
        )
        return

    logger.info(
        f"[CLOSE_ON_FILL] Position closed: id={position_id[:8]} "
        f"symbol={position.get('symbol')} "
        f"realized_pl=${realized_pl}"
    )

    # ── CLOSE_FILL_GAP (LIVE fill): record the slippage between the stage-time
    # full-cross executable estimate and the marketable-limit fill obtained.
    # ADDITIVE / observe-only — never affects the close. cross/mid were stamped
    # onto order_json at stage time (paper_exit_evaluator); fill is the broker's
    # net combo fill. Older orders without the stamp log fill-only (NA). The
    # whole block is best-effort and swallows every exception.
    try:
        from packages.quantum.services.close_fill_gap import (
            read_stamp as _cfg_read,
            log_close_fill_gap as _cfg_log,
            stamp_payload as _cfg_payload,
            broker_fill_to_mark_basis as _cfg_basis,
        )
        _cfg_cross, _cfg_mid = _cfg_read(order.get("order_json"))
        # SIGN FIX (2026-07-08): cross/mid are stamped SIGNED (credit
        # structures are negative); the broker's net combo fill maps onto
        # that basis by NEGATION (credit fills negative / debit positive at
        # the broker). The old abs() here corrupted every credit close
        # (QQQ 07-07 stored gap_fraction 15.08; true 1.42).
        _cfg_fill = _cfg_basis(alpaca_order.get("filled_avg_price"))
        _cfg_log(
            position.get("symbol"), position_id,
            _cfg_cross, _cfg_mid, _cfg_fill,
            reason="alpaca_fill_reconciler_standard", log=logger,
        )
        # P2 persistence (existing order_json JSONB, NO migration): write the
        # full {cross, mid, fill, gap_fraction} so the LIVE distribution is
        # self-contained + queryable for the Phase-3 REOPEN gate. Best-effort.
        try:
            _oj = dict(order.get("order_json") or {})
            _oj.update(_cfg_payload(_cfg_cross, _cfg_mid, _cfg_fill))
            supabase.table("paper_orders").update({"order_json": _oj}).eq(
                "id", order.get("id")
            ).execute()
        except Exception:
            pass
    except Exception as _cfg_e:
        logger.warning(f"[CLOSE_FILL_GAP] live emit failed: {_cfg_e}")


def _write_close_path_critical_alert(
    supabase,
    position: Dict[str, Any],
    stage: str,
    reason: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a severity='critical' risk_alert when a close-path
    anomaly aborts the reconciler's close attempt.

    Anomalies covered: PartialFillDetected, MalformedFillData,
    PositionAlreadyClosed, or any other pre-condition failure.
    Caller returns early after writing; no close action taken.

    Swallows its own exceptions — a failed risk_alert write must
    not cascade to a handler crash. Logs via logger.error instead.
    """
    try:
        metadata = {
            "detector": "alpaca_fill_reconciler",
            "stage": stage,
            "reason": reason,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        supabase.table("risk_alerts").insert({
            "user_id": position.get("user_id"),
            "alert_type": "close_path_anomaly",
            "severity": "critical",
            "position_id": position.get("id"),
            "symbol": position.get("symbol"),
            "message": (
                f"Reconciler close aborted at {stage}: {reason[:200]}"
            ),
            "metadata": metadata,
        }).execute()
    except Exception as alert_err:
        logger.error(
            f"[CLOSE_ON_FILL] Failed to write critical risk_alert for "
            f"position {position.get('id', '?')[:8]}: {alert_err}. "
            f"Original anomaly at {stage}: {reason[:200]}"
        )


def _parse_iso_timestamp(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp (with either 'Z' or '+00:00'
    suffix) to a timezone-aware datetime. Returns utcnow() as
    fallback on parse failure rather than raising — caller has
    already completed the fill-math work at this point."""
    try:
        normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError, TypeError):
        return datetime.now(timezone.utc)


def poll_pending_orders(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
) -> Dict[str, Any]:
    """
    Check status of all submitted Alpaca orders and sync back.

    Production features:
    - Idle watchdog: an unfilled working order is cancelled at the first
      poll where idle > IDLE_WATCHDOG_SECONDS (effective timing = the
      order_sync cadence, ~up to 6 min). CANCEL-ONLY — no resubmission;
      the order ends watchdog_cancelled and its suggestion stays pending.
    - Retry on poll failures (transient)
    - Fill detection with position creation
    """
    # Get orders with Alpaca IDs that are still pending
    port_res = supabase.table("paper_portfolios") \
        .select("id").eq("user_id", user_id).execute()
    if not port_res.data:
        return {"synced": 0, "errors": []}

    p_ids = [p["id"] for p in port_res.data]

    # Include needs_manual_review: the outer retry can exhaust while Alpaca
    # actually filled on a prior attempt. If alpaca_order_id is set, Alpaca's
    # record is authoritative and polling will reconcile the fill.
    orders_res = supabase.table("paper_orders") \
        .select("id, alpaca_order_id, status, submitted_at, broker_status, position_id, side, order_json") \
        .in_("status", ["submitted", "working", "partial", "needs_manual_review"]) \
        .in_("portfolio_id", p_ids) \
        .not_.is_("alpaca_order_id", "null") \
        .execute()
    orders = orders_res.data or []

    synced = 0
    fills = 0
    partials = 0
    cancels = 0
    unchanged = 0
    watchdog_cancels = 0
    errors = []

    now_utc = datetime.now(timezone.utc)

    for order in orders:
        order_id = order["id"]
        alpaca_id = order["alpaca_order_id"]

        try:
            alpaca_order = alpaca.get_order(alpaca_id)
            alpaca_status = alpaca_order.get("status", "")

            # Map Alpaca status → internal
            status_map = {
                "new": "working", "accepted": "working",
                "pending_new": "working", "partially_filled": "partial",
                "filled": "filled", "canceled": "cancelled",
                "expired": "cancelled", "rejected": "cancelled",
                "replaced": "working", "pending_replace": "working",
            }
            internal_status = status_map.get(alpaca_status, "working")

            # === IDLE WATCHDOG (threshold 90s, checked on the sync cadence) ===
            # If the order is still in a "waiting" state with no fills and has
            # been idle past IDLE_WATCHDOG_SECONDS, cancel it. CANCEL-ONLY:
            # nothing resubmits after this — the order terminates in
            # watchdog_cancelled (resubmission/reprice is the deferred
            # step-pricing layer; entry pricing is handled upstream by the
            # flag-gated marketable-entry lever instead).
            #
            # GTC EXEMPTION (gtc_profit_exit): a GTC resting profit-limit is
            # SUPPOSED to idle — it parks at the cohort's profit credit until
            # the market comes to it. Idle-timeout cancellation applies to DAY
            # orders only; without this exemption every resting GTC would be
            # killed at the first sync after 90s. Lifecycle for GTC orders is
            # owned by the close path instead (a competing stop/envelope close
            # pre-cancels them via cancel_open_orders_for_symbols).
            _order_oj = order.get("order_json") or {}
            _order_tif = str(_order_oj.get("time_in_force") or "day").lower()
            # 06-12: intentional_resting_exit is the explicit order-class
            # marker for orders that are SUPPOSED to rest (resting-TP pilot);
            # exempt alongside tif=gtc (belt + suspenders — a future DAY-
            # variant resting order stays watchdog-safe via the class).
            _order_cls = str(_order_oj.get("order_class") or "")
            if (
                internal_status == "working"
                and order.get("submitted_at")
                and _order_tif != "gtc"
                and _order_cls != "intentional_resting_exit"
            ):
                try:
                    submitted_at = datetime.fromisoformat(
                        order["submitted_at"].replace("Z", "+00:00")
                    )
                    idle_seconds = (now_utc - submitted_at).total_seconds()
                    filled_qty = float(alpaca_order.get("filled_qty") or 0)

                    if idle_seconds > IDLE_WATCHDOG_SECONDS and filled_qty == 0:
                        logger.warning(
                            f"[ALPACA_HANDLER] Idle watchdog triggered: order={order_id} "
                            f"alpaca={alpaca_id} idle={idle_seconds:.0f}s "
                            f"(threshold={IDLE_WATCHDOG_SECONDS}s). Cancelling."
                        )
                        try:
                            alpaca.cancel_order(alpaca_id)
                        except Exception as cancel_err:
                            logger.warning(
                                f"[ALPACA_HANDLER] Watchdog cancel failed: {cancel_err}"
                            )

                        # #101 Component 4: also write cancelled_at/reason
                        # at the row level so forensic queries don't have
                        # to dig into broker_response JSONB.
                        supabase.table("paper_orders").update({
                            "broker_status": "watchdog_cancelled",
                            "status": "watchdog_cancelled",
                            "cancelled_at": now_utc.isoformat(),
                            "cancelled_reason": (
                                f"watchdog_idle_timeout idle={round(idle_seconds)}s "
                                f"threshold={IDLE_WATCHDOG_SECONDS}s"
                            ),
                            "broker_response": {
                                **alpaca_order,
                                "watchdog": {
                                    "reason": "idle_timeout",
                                    "idle_seconds": round(idle_seconds),
                                    "threshold": IDLE_WATCHDOG_SECONDS,
                                    "cancelled_at": now_utc.isoformat(),
                                },
                            },
                        }).eq("id", order_id).execute()

                        watchdog_cancels += 1
                        continue  # Skip normal processing for this order
                except (ValueError, TypeError):
                    pass  # Malformed submitted_at, skip watchdog

            update = {
                "broker_status": alpaca_status,
                "broker_response": alpaca_order,
                "status": internal_status,
            }

            filled_qty = float(alpaca_order.get("filled_qty") or 0)
            if filled_qty > 0:
                update["filled_qty"] = filled_qty
                if alpaca_order.get("filled_avg_price"):
                    update["avg_fill_price"] = float(alpaca_order["filled_avg_price"])
                if alpaca_order.get("filled_at"):
                    update["filled_at"] = alpaca_order["filled_at"]

            # #101 Component 4: capture broker rejection reason + transition
            # timestamp. Pre-fix, rejected/failed orders had cancelled_at and
            # cancelled_reason both NULL — forensic blind spot during the
            # CSX 22-rejection cascade. Alpaca surfaces rejection text on the
            # leg-level status_text field for mleg orders; for simple orders
            # it lands on a top-level field. We try both, fall back to the
            # status code itself when no text is available.
            broker_failed_at = alpaca_order.get("failed_at")
            broker_canceled_at = alpaca_order.get("canceled_at")
            is_broker_rejection = alpaca_status in ("rejected", "expired") or (
                alpaca_status == "canceled" and broker_failed_at is not None
            )
            rejection_reason = None
            if is_broker_rejection or alpaca_status in ("canceled", "expired"):
                for leg in (alpaca_order.get("legs") or []):
                    text = leg.get("status_text") or leg.get("reject_reason")
                    if text:
                        rejection_reason = text
                        break
                if not rejection_reason:
                    rejection_reason = (
                        alpaca_order.get("status_text")
                        or alpaca_order.get("reject_reason")
                        or f"alpaca_status={alpaca_status}"
                    )
                update["cancelled_reason"] = str(rejection_reason)[:500]
                update["cancelled_at"] = (
                    broker_failed_at or broker_canceled_at or now_utc.isoformat()
                )

            supabase.table("paper_orders").update(update).eq("id", order_id).execute()
            synced += 1

            # #101 Component 3: loud alert when the broker pre-rejects an
            # order. Pre-fix, 22 CSX close orders rejected silently over 36+
            # hours — only force_close + warn alerts fired, none surfacing
            # the actual broker-side failure. Throttle to 1/hour per
            # (alert_type, position_id) so retry storms produce one alert,
            # not one-per-attempt. Best-effort: any throttle-query or
            # alert-write failure must NOT break the poll loop.
            if is_broker_rejection:
                try:
                    from packages.quantum.observability.alerts import alert
                    pos_id = order.get("position_id")
                    throttle_q = supabase.table("risk_alerts") \
                        .select("id") \
                        .eq("alert_type", "order_rejected_by_broker") \
                        .gte("created_at", (now_utc - timedelta(hours=1)).isoformat())
                    if pos_id:
                        throttle_q = throttle_q.eq("position_id", pos_id)
                    else:
                        throttle_q = throttle_q.eq("user_id", user_id)
                    recent_alert = throttle_q.limit(1).execute()
                    if not (recent_alert.data or []):
                        leg_summary = [
                            {
                                "symbol": leg.get("symbol"),
                                "side": leg.get("side"),
                                "position_intent": leg.get("position_intent"),
                            }
                            for leg in (alpaca_order.get("legs") or [])
                        ]
                        alert(
                            supabase,
                            alert_type="order_rejected_by_broker",
                            severity="critical",
                            message=(
                                f"Alpaca rejected {order.get('side', '?')} order "
                                f"on {order.get('order_json', {}).get('symbol', '?')}: "
                                f"{str(rejection_reason)[:200]}"
                            ),
                            user_id=user_id,
                            position_id=pos_id,
                            symbol=(order.get("order_json") or {}).get("symbol"),
                            metadata={
                                "alpaca_order_id": alpaca_id,
                                "internal_order_id": str(order_id),
                                "alpaca_status": alpaca_status,
                                "broker_failed_at": broker_failed_at,
                                "broker_canceled_at": broker_canceled_at,
                                "limit_price": alpaca_order.get("limit_price"),
                                "leg_structure": leg_summary,
                                "rejection_reason": rejection_reason,
                                "consequence": (
                                    "Position cannot be closed via this order. "
                                    "If retried with same parameters it will "
                                    "reject again. Investigate sign convention, "
                                    "position-intent, account entitlements, "
                                    "limit-price bounds."
                                ),
                            },
                        )
                except Exception as alert_err:
                    # Never break the poll loop on alert-path failure.
                    logger.warning(
                        f"[ALPACA_HANDLER] order_rejected_by_broker alert "
                        f"path failed: order={order_id} err={alert_err}"
                    )

            # When order transitions to filled, handle position updates.
            if internal_status == "filled" and filled_qty > 0:
                pos_id = order.get("position_id")
                try:
                    if pos_id:
                        # ── CLOSE ORDER FILL: close the position ─────────
                        # This is the critical path that was missing — close
                        # orders have position_id set, but _process_orders_for_user
                        # and _commit_fill never touched paper_positions.
                        _close_position_on_fill(
                            supabase, pos_id, order, alpaca_order,
                        )
                        logger.info(
                            f"[ALPACA_HANDLER] Position closed on fill: "
                            f"order={order_id} position={pos_id[:8]} "
                            f"filled_qty={filled_qty} "
                            f"avg_price={alpaca_order.get('filled_avg_price')}"
                        )
                    else:
                        # ── OPEN ORDER FILL: create/update position ──────
                        from packages.quantum.paper_endpoints import (
                            _process_orders_for_user,
                        )
                        from packages.quantum.services.analytics_service import AnalyticsService

                        analytics = AnalyticsService(supabase)
                        repair_result = _process_orders_for_user(
                            supabase, analytics, user_id
                        )
                        logger.info(
                            f"[ALPACA_HANDLER] Open fill committed: order={order_id} "
                            f"repair_processed={repair_result.get('processed', 0)}"
                        )

                        # GTC resting profit-limit placement (flag-gated,
                        # default OFF — no-op until GTC_PROFIT_EXIT_ENABLED).
                        # On a LIVE entry fill, park a closing mleg GTC limit
                        # at the cohort's flat profit credit so the broker
                        # auto-fires on profit. Fail-soft: placement errors
                        # never break the poll loop.
                        try:
                            from packages.quantum.services.gtc_profit_exit import (
                                maybe_place_gtc_profit_exit,
                            )
                            maybe_place_gtc_profit_exit(supabase, order_id, user_id)
                        except Exception as gtc_err:
                            logger.error(
                                f"[GTC_PROFIT_EXIT] placement hook failed "
                                f"(non-fatal): order={order_id} err={gtc_err}"
                            )
                    fills += 1
                except Exception as fill_err:
                    logger.error(
                        f"[ALPACA_HANDLER] Fill commit failed: order={order_id} "
                        f"position_id={pos_id} error={fill_err}"
                    )
            elif internal_status == "partial":
                partials += 1
            elif internal_status == "cancelled":
                cancels += 1
            else:
                unchanged += 1

            logger.info(
                f"[ALPACA_HANDLER] Synced: internal={order_id} "
                f"alpaca_status={alpaca_status} → {internal_status} "
                f"filled_qty={filled_qty}"
            )

        except Exception as e:
            logger.error(f"[ALPACA_HANDLER] Poll failed: order={order_id} error={e}")
            errors.append({"order_id": order_id, "error": str(e)})

    return {
        "synced": synced, "total_polled": len(orders),
        "fills": fills, "partials": partials,
        "cancels": cancels, "unchanged": unchanged,
        "watchdog_cancels": watchdog_cancels,
        "errors": errors,
    }


def ghost_position_sweep(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
    min_age_seconds: int = 600,
    stale_review_min_seconds: int = 3600,
) -> Dict[str, Any]:
    """
    Leg-level drift sweep: find DB open positions whose OCC legs are not
    present on Alpaca. Writes a severity=warn risk_alert per ghost position.

    Also (per #98 Option B) finds paper_orders rows in needs_manual_review
    state linked to open paper_positions past `stale_review_min_seconds`
    staleness. Defense-in-depth catch for the 2026-05-01 BAC ghost-position
    incident shape — Option C's write-site alert (PR #853) catches these
    at creation; this sweep is the recurring catch when that alert is
    missed in the moment.

    Gated by the caller (RECONCILE_POSITIONS_ENABLED env var). `min_age_seconds`
    protects entries that just filled on Alpaca but whose position row is still
    catching up (default 10 minutes). `stale_review_min_seconds` (default 1h)
    gives Option C's alert + operator time to clear the state before this
    recurring catch fires. Idempotency: at most one alert per stuck order
    per hour to avoid flooding risk_alerts at sweep cadence.

    Returns {ghost_count, positions_checked, alpaca_leg_count, ghosts,
    stale_review_orders_checked, stale_review_alerts_fired,
    stale_review_alerts}.
    """
    from datetime import datetime, timezone, timedelta

    try:
        alpaca_positions = alpaca.get_option_positions()
    except Exception as e:
        return {"status": "error", "error": str(e), "ghost_count": 0}

    # Normalize Alpaca-side symbols to raw OCC (strip "O:" prefix) to
    # match the DB-side normalization below. `alpaca.get_option_positions()`
    # returns symbols via `_serialize_position` which converts Alpaca's
    # raw OCC back to Polygon's "O:"-prefixed format via
    # `alpaca_to_polygon`, so both sides arrive here with the prefix and
    # we strip from both. Without this, every DB-Alpaca match falsely
    # flags as a ghost (see 2026-04-21 RECONCILE observation window —
    # 56 false positives on AMZN a0f05755 despite the position being
    # legitimately open on both sides).
    alpaca_legs = {
        (p.get("symbol", "") or "").lstrip("O:")
        for p in alpaca_positions
        if p.get("symbol")
    }

    # Ghost-sweep live-scoping (2026-07-02, ledgered P2→P1): a broker-desync
    # detector must compare only positions that are SUPPOSED to exist at the
    # broker. shadow_only/paper_shadow positions never reach Alpaca by design
    # (execution_router.should_submit_to_broker), so sweeping them emitted one
    # false "desync" warn per sync cycle for every open shadow (58 warns from
    # the single 06-30→07-01 shadow SOFI) — burying the H10 signal exactly
    # when live order flow makes a REAL desync time-critical. Scopes BOTH
    # halves below (ghost legs + stale needs_manual_review): both detect
    # broker-side drift, which a shadow cannot have. FAIL-OPEN polarity for a
    # DETECTOR: if the scope query fails, fall back to the legacy UNSCOPED
    # sweep (noisy beats blind) with a warning — never a silently narrower
    # sweep.
    try:
        from packages.quantum.risk.position_scope import live_routed_portfolio_ids

        p_ids = live_routed_portfolio_ids(supabase, user_id)
        if not p_ids:
            return {"status": "no_live_routed_portfolios", "ghost_count": 0}
    except Exception as scope_err:
        logger.warning(
            f"[GHOST_SWEEP] live-routed scope query failed ({scope_err}); "
            f"falling back to UNSCOPED sweep (may include shadow noise)"
        )
        port_res = supabase.table("paper_portfolios") \
            .select("id").eq("user_id", user_id).execute()
        if not port_res.data:
            return {"status": "no_portfolios", "ghost_count": 0}
        p_ids = [p["id"] for p in port_res.data]

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)).isoformat()

    open_res = supabase.table("paper_positions") \
        .select("id, symbol, legs, created_at, quantity") \
        .in_("portfolio_id", p_ids) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .lt("created_at", cutoff) \
        .execute()
    open_positions = open_res.data or []

    ghosts: List[Dict[str, Any]] = []
    for pos in open_positions:
        legs = pos.get("legs") or []
        if not legs:
            continue
        # Strip Polygon "O:" prefix to match Alpaca's OCC format
        expected_occs = {
            (leg.get("symbol") or "").lstrip("O:")
            for leg in legs
            if leg.get("symbol")
        }
        if not expected_occs:
            continue
        # If NONE of the expected legs are on Alpaca, the position is a ghost
        if not (expected_occs & alpaca_legs):
            ghosts.append({
                "position_id": pos["id"],
                "symbol": pos.get("symbol"),
                "expected_legs": sorted(expected_occs),
                "created_at": pos.get("created_at"),
            })

    for g in ghosts:
        try:
            supabase.table("risk_alerts").insert({
                "user_id": user_id,
                "alert_type": "ghost_position",
                "severity": "warn",
                "position_id": g["position_id"],
                "symbol": g["symbol"],
                "message": (
                    f"Ghost position detected: {g['symbol']} (id={g['position_id'][:8]}) "
                    f"open in DB but no matching legs on Alpaca"
                ),
                "metadata": {
                    "expected_legs": g["expected_legs"],
                    "created_at": g["created_at"],
                    "detector": "ghost_position_sweep",
                },
            }).execute()
        except Exception as alert_err:
            logger.error(
                f"[GHOST_SWEEP] Failed to write risk_alert for {g['position_id'][:8]}: {alert_err}"
            )

    # ─────────────────────────────────────────────────────────────────────
    # #98 Option B: stale needs_manual_review orders linked to open positions
    #
    # Defense-in-depth catch for the 2026-05-01 BAC incident shape. Option C
    # (PR #853) alerts at the moment submit_and_track marks an order
    # needs_manual_review; this sweep surfaces the persistent stuck state
    # if that alert was missed in the moment. BAC sat in needs_manual_review
    # with an open position from Friday 16:45 UTC to Monday 13:52 UTC — this
    # check would have fired hourly through that window.
    # ─────────────────────────────────────────────────────────────────────
    open_position_map = {pos["id"]: pos for pos in open_positions if pos.get("id")}

    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=stale_review_min_seconds)
    ).isoformat()
    stale_orders_res = supabase.table("paper_orders") \
        .select("id, position_id, status, broker_status, submitted_at, created_at, broker_response") \
        .in_("portfolio_id", p_ids) \
        .eq("status", "needs_manual_review") \
        .lt("created_at", stale_cutoff) \
        .execute()
    stale_orders = stale_orders_res.data or []

    dedup_cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    now_utc = datetime.now(timezone.utc)
    stale_review_alerts: List[Dict[str, Any]] = []

    for ord_row in stale_orders:
        pos_id = ord_row.get("position_id")
        if not pos_id:
            continue
        pos = open_position_map.get(pos_id)
        if not pos:
            # Linked position not in the open set (closed, missing, or
            # belongs to a different portfolio). The order is stuck but
            # the position is no longer open — out of scope for this check.
            continue

        # Idempotency gate: skip if we've already alerted on this order
        # within the last hour. Without this, sweep cadence (every 5 min
        # via alpaca_order_sync) would flood risk_alerts with ~12 rows per
        # hour for a single stuck order. BAC's 3-day stuck duration would
        # have produced 864 alerts.
        try:
            prior_res = supabase.table("risk_alerts") \
                .select("id") \
                .eq("alert_type", "stale_manual_review_with_open_position") \
                .filter("metadata->>order_id", "eq", ord_row["id"]) \
                .gte("created_at", dedup_cutoff) \
                .limit(1) \
                .execute()
            if prior_res.data:
                continue
        except Exception as dedup_err:
            # Idempotency-check failure must not block the alert path.
            # Better to risk a duplicate alert than to silently drop the
            # whole signal. Log and proceed.
            logger.warning(
                f"[GHOST_SWEEP] stale_review dedup check failed for "
                f"order={ord_row['id'][:8]}: {dedup_err}; firing anyway"
            )

        try:
            created_dt = datetime.fromisoformat(
                (ord_row.get("created_at") or "").replace("Z", "+00:00")
            )
            hours_stale = (now_utc - created_dt).total_seconds() / 3600.0
        except Exception:
            hours_stale = 0.0

        symbol = pos.get("symbol")
        stale_review_alerts.append({
            "order_id": ord_row["id"],
            "position_id": pos_id,
            "symbol": symbol,
            "hours_stale": round(hours_stale, 2),
            "order_created_at": ord_row.get("created_at"),
            "order_submitted_at": ord_row.get("submitted_at"),
            "position_quantity": pos.get("quantity"),
            "broker_response": ord_row.get("broker_response"),
            "broker_status": ord_row.get("broker_status"),
        })

    for sa in stale_review_alerts:
        try:
            supabase.table("risk_alerts").insert({
                "user_id": user_id,
                "alert_type": "stale_manual_review_with_open_position",
                "severity": "warn",
                "position_id": sa["position_id"],
                "symbol": sa["symbol"],
                "message": (
                    f"Stale needs_manual_review order for {sa['symbol']}: "
                    f"{sa['hours_stale']:.1f}h old, position still open. "
                    f"Same shape as 2026-05-01 BAC ghost-position incident."
                ),
                "metadata": {
                    "order_id": sa["order_id"],
                    "position_id": sa["position_id"],
                    "symbol": sa["symbol"],
                    "hours_stale": sa["hours_stale"],
                    "order_created_at": sa["order_created_at"],
                    "order_submitted_at": sa["order_submitted_at"],
                    "position_quantity": sa["position_quantity"],
                    "broker_response": sa["broker_response"],
                    "broker_status": sa["broker_status"],
                    "detector": "ghost_position_sweep",
                    "operator_action_required": (
                        "Order is stuck in needs_manual_review with linked "
                        "position still open. Investigate broker_response "
                        "for rejection reason. Resolution paths: "
                        "(1) manual close at Alpaca UI + DB reconciliation "
                        "per docs/pr6_close_path_consolidation.md Section 4, "
                        "or (2) confirm position is flat at broker "
                        "(ghost-state scenario) and update DB to closed. "
                        "Do NOT retry the close until root cause is "
                        "understood."
                    ),
                    "doctrine_ref": (
                        "loud_error_doctrine.md anti-pattern 4 "
                        "(per-iteration recurring catch)"
                    ),
                },
            }).execute()
        except Exception as alert_err:
            logger.error(
                f"[GHOST_SWEEP] Failed to write stale_review alert for "
                f"order={sa['order_id'][:8]}: {alert_err}"
            )

    logger.info(
        f"[GHOST_SWEEP] user={user_id[:8]} checked={len(open_positions)} "
        f"alpaca_legs={len(alpaca_legs)} ghosts={len(ghosts)} "
        f"stale_review_orders={len(stale_orders)} "
        f"stale_review_alerts_fired={len(stale_review_alerts)}"
    )

    return {
        "status": "ok",
        "ghost_count": len(ghosts),
        "positions_checked": len(open_positions),
        "alpaca_leg_count": len(alpaca_legs),
        "ghosts": ghosts,
        "stale_review_orders_checked": len(stale_orders),
        "stale_review_alerts_fired": len(stale_review_alerts),
        "stale_review_alerts": stale_review_alerts,
    }


def reconcile_positions(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
) -> Dict[str, Any]:
    """
    Compare Alpaca positions vs internal paper_positions.
    Returns list of discrepancies.
    """
    # Get Alpaca positions
    try:
        alpaca_positions = alpaca.get_option_positions()
    except Exception as e:
        return {"status": "error", "error": str(e)}

    # Get internal open positions
    port_res = supabase.table("paper_portfolios") \
        .select("id").eq("user_id", user_id).execute()
    if not port_res.data:
        return {"status": "no_portfolios"}

    p_ids = [p["id"] for p in port_res.data]
    internal_res = supabase.table("paper_positions") \
        .select("id, symbol, quantity, status") \
        .in_("portfolio_id", p_ids) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .execute()
    internal_positions = internal_res.data or []

    # Build maps for comparison
    alpaca_map = {}
    for p in alpaca_positions:
        sym = p.get("symbol", "")
        alpaca_map[sym] = float(p.get("qty", 0))

    internal_map = {}
    for p in internal_positions:
        sym = p.get("symbol", "")
        internal_map[sym] = float(p.get("quantity", 0))

    discrepancies = []

    # Check Alpaca positions not in internal
    for sym, qty in alpaca_map.items():
        if sym not in internal_map:
            discrepancies.append({
                "type": "alpaca_only",
                "symbol": sym,
                "alpaca_qty": qty,
                "internal_qty": 0,
            })
        elif abs(internal_map[sym] - qty) > 0.01:
            discrepancies.append({
                "type": "qty_mismatch",
                "symbol": sym,
                "alpaca_qty": qty,
                "internal_qty": internal_map[sym],
            })

    # Check internal positions not in Alpaca
    for sym, qty in internal_map.items():
        if sym not in alpaca_map:
            discrepancies.append({
                "type": "internal_only",
                "symbol": sym,
                "alpaca_qty": 0,
                "internal_qty": qty,
            })

    logger.info(
        f"[ALPACA_HANDLER] Reconciliation: alpaca={len(alpaca_map)} "
        f"internal={len(internal_map)} discrepancies={len(discrepancies)}"
    )

    return {
        "status": "ok",
        "alpaca_count": len(alpaca_map),
        "internal_count": len(internal_map),
        "discrepancies": discrepancies,
    }
