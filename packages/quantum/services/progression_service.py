"""
Progression Service — single source of truth for go-live state machine.

Phases: alpaca_paper → micro_live → full_auto

Gate from alpaca_paper → micro_live:
  - N consecutive green trading days (default 4)
  - A green day = total realized PnL from closed positions > $0

Gate from micro_live → full_auto (rewritten 2026-05-06):
  - broker equity ≥ $1500
  - cumulative realized_pl > 0 across Alpaca-real closed trades
  - alpaca_real_trade_count ≥ 3
  Manual promotion via promote() preserved as bypass.

The "Alpaca-real" trade definition (closed paper_position whose entry
order has alpaca_order_id IS NOT NULL) is shared via
get_alpaca_real_closed_trades() between alpaca_paper green-day counting
and full_auto eligibility. Excludes internal-paper-era simulations and
the 34 corrupted rows documented in CLAUDE.md 2026-04-16 entry.

All trading-day calculations use Chicago timezone.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)

TABLE = "go_live_progression"
LOG_TABLE = "go_live_progression_log"

# Gate thresholds for micro_live → full_auto auto-promotion (2026-05-06)
EQUITY_THRESHOLD_FULL_AUTO = 1500.0
MIN_TRADES_FULL_AUTO = 3

# Gate threshold for strategy lifecycle EXPERIMENTAL → LIVE_FULL graduation
# (#108 PR-1, 2026-05-07). Kept separate from MIN_TRADES_FULL_AUTO because
# tier-promotion and strategy-graduation may diverge later — same value
# today (3) but no semantic coupling. Revisit unification if both
# constants stay in lockstep across multiple changes.
MIN_TRADES_FOR_STRATEGY_GRADUATION = 3


def get_alpaca_real_closed_trades(
    user_id: str,
    supabase,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    strategy_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return closed paper_positions whose ENTRY order was Alpaca-routed.

    Excludes internal-paper era simulations and the 34 corrupted rows
    documented in CLAUDE.md 2026-04-16 entry. This is the canonical
    'real trade' definition shared by:
    - daily_progression_eval (alpaca_paper green-day counter)
    - promotion_check (micro_live → full_auto gate)

    Mirrors the inline pattern that previously lived at
    daily_progression_eval.py:63-91; extracted to a helper so both
    callers agree on the trade lens.

    Args:
        user_id: User UUID
        supabase: Supabase client instance
        since: Optional datetime; only return positions closed at/after
        until: Optional datetime; only return positions closed at/before
        strategy_name: Optional strategy filter (e.g. ``"IRON_CONDOR"``).
            When provided, restricts results to closed positions whose
            ``strategy`` column equals this value. Reads
            ``paper_positions.strategy`` directly — column verified
            populated 17/17 for Alpaca-real closed positions
            (2026-05-07 schema check) so a JOIN through
            ``trade_suggestions`` is unnecessary. ``None`` (default)
            preserves pre-#108 behavior verbatim.

    Returns:
        List of paper_positions row dicts with at least id, realized_pl,
        closed_at, and strategy. Empty list if no qualifying trades.
    """
    query = supabase.table("paper_positions") \
        .select("id, realized_pl, closed_at, strategy") \
        .eq("user_id", user_id) \
        .eq("status", "closed")
    if since is not None:
        query = query.gte("closed_at", since.isoformat())
    if until is not None:
        query = query.lte("closed_at", until.isoformat())
    if strategy_name is not None:
        query = query.eq("strategy", strategy_name)

    res = query.execute()
    all_closed = res.data or []
    if not all_closed:
        return []

    # Filter to Alpaca-only by checking the ENTRY (earliest) order per
    # position. Exit orders may also have execution_mode='alpaca_paper'
    # from the global env var even when entry was internal — the
    # earliest-order check is what distinguishes a real entry.
    alpaca_pos_ids = set()
    for pos in all_closed:
        try:
            entry_res = supabase.table("paper_orders") \
                .select("alpaca_order_id") \
                .eq("position_id", pos["id"]) \
                .order("created_at", desc=False) \
                .limit(1) \
                .execute()
            if entry_res.data and entry_res.data[0].get("alpaca_order_id"):
                alpaca_pos_ids.add(pos["id"])
        except Exception:
            # Graceful degradation per existing pattern — a per-position
            # entry-order lookup failure should not abort the whole sweep.
            pass

    return [p for p in all_closed if p["id"] in alpaca_pos_ids]


def cumulative_realized_pl(trades: List[Dict[str, Any]]) -> float:
    """Sum realized_pl across a list of trade rows.

    Treats None/missing realized_pl as 0.0. Empty list returns 0.0.
    """
    return sum(float(t.get("realized_pl") or 0) for t in trades)


# NOTE: As of #108 PR-1 (2026-05-07), this function has no callers in
# production code. It exists as foundation for #109 (strategy_lifecycle_states
# table + daily scheduler hook), which will be the first caller. If #109
# hasn't shipped within ~30 days of #108 PR-1's merge, revisit whether this
# orphan code should be removed or repurposed. See `docs/backlog.md` #108.
def get_strategy_eligibility(
    strategy_name: str,
    user_id: str,
    supabase,
) -> Dict[str, Any]:
    """Evaluate whether a strategy meets graduation criteria.

    Mirrors the tier-promotion gate shape from PR #883 but scoped to a
    single strategy. Used by future lifecycle gating (#109): an
    EXPERIMENTAL strategy graduates to LIVE_FULL when both gates pass:
      1. cumulative realized_pl > 0 across that strategy's
         Alpaca-real closed trades
      2. trade_count ≥ MIN_TRADES_FOR_STRATEGY_GRADUATION

    No side effects. No database writes. Pure read function.

    Args:
        strategy_name: Strategy identifier as stored in
            ``paper_positions.strategy`` (e.g. ``"IRON_CONDOR"``,
            ``"LONG_CALL_DEBIT_SPREAD"``). Caller is responsible for
            validity; an unknown name returns the empty-result shape.
        user_id: User UUID.
        supabase: Supabase client instance.

    Returns:
        Dict with:
          - ``eligible`` (bool): both gates pass
          - ``cumulative_pl`` (float): sum of realized_pl
          - ``trade_count`` (int): number of Alpaca-real closed trades
            for this strategy
          - ``min_required_trades`` (int): the threshold, exposed for
            caller observability + audit logging
    """
    trades = get_alpaca_real_closed_trades(
        user_id=user_id,
        supabase=supabase,
        strategy_name=strategy_name,
    )
    cumulative_pl = cumulative_realized_pl(trades)
    trade_count = len(trades)
    eligible = (
        cumulative_pl > 0
        and trade_count >= MIN_TRADES_FOR_STRATEGY_GRADUATION
    )
    return {
        "eligible": eligible,
        "cumulative_pl": cumulative_pl,
        "trade_count": trade_count,
        "min_required_trades": MIN_TRADES_FOR_STRATEGY_GRADUATION,
    }


# As of #109 PR-2 (2026-05-07), the seed migration places all 5
# currently-shipped strategies in LIVE_FULL state — there are zero
# EXPERIMENTAL strategies yet. evaluate_strategy_lifecycle() will
# return [] until either:
#   - A new strategy is added in EXPERIMENTAL state (#111 0DTE / #112 CSP)
#   - An existing strategy is manually demoted via SQL (operator action)
# The function is correct + tested; it's just waiting for work to do.
def _get_default_strategy_owner_user_id() -> Optional[str]:
    """Return the user_id whose closed-trade history backs strategy
    eligibility decisions.

    Single-tenant for now: the operator's UUID. Reads from env first
    (``STRATEGY_LIFECYCLE_OWNER_USER_ID``) then falls back to the
    canonical operator UUID documented in CLAUDE.md. Multi-tenant
    aggregation across users is deferred — the helper is the seam
    where that future change lands.
    """
    return (
        os.environ.get("STRATEGY_LIFECYCLE_OWNER_USER_ID")
        or "75ee12ad-b119-4f32-aeea-19b4ef55d587"
    )


def evaluate_strategy_lifecycle(supabase) -> List[Dict[str, Any]]:
    """Evaluate every EXPERIMENTAL strategy for graduation to LIVE_FULL.

    Reads ``strategy_lifecycle_states`` for current state, calls
    ``get_strategy_eligibility`` for each EXPERIMENTAL row, transitions
    eligible strategies to LIVE_FULL with audit trail, and returns the
    list of transition records.

    No ``user_id`` parameter: strategy lifecycle is global, not
    per-user. Trade history comes from the operator's user_id via
    ``_get_default_strategy_owner_user_id`` (single-tenant assumption
    documented at that helper).

    Idempotent. The WHERE filter ``current_state = 'experimental'``
    means a successful first run leaves nothing for a second run to
    pick up — re-run produces ``[]`` and writes no audit rows.

    Failure isolation: a single eligibility / DB error for one
    strategy is logged and skipped; the sweep continues for the
    remaining EXPERIMENTAL rows. Loud-Error Doctrine v1.0 anti-pattern
    4 (per-iteration swallow) — a ``strategy_lifecycle_eval_error``
    risk_alert is written so failures surface in the audit feed.

    Returns:
        List of transition dicts. Each entry:
            {
              "strategy_name": str,
              "previous_state": "experimental",
              "new_state": "live_full",
              "cumulative_realized_pl": float,
              "trade_count": int,
              "min_required_trades": int,
            }
    """
    try:
        experimental_res = (
            supabase.table("strategy_lifecycle_states")
            .select("strategy_name, current_state")
            .eq("current_state", "experimental")
            .execute()
        )
    except Exception as e:
        logger.exception(
            f"[STRATEGY_LIFECYCLE] Failed to read EXPERIMENTAL strategies: {e}"
        )
        _emit_lifecycle_alert(
            supabase=supabase,
            severity="warning",
            message=f"strategy_lifecycle_eval read failure: {e}",
            metadata={"phase": "read_experimental"},
        )
        return []

    rows = experimental_res.data or []
    if not rows:
        return []

    owner_user_id = _get_default_strategy_owner_user_id()
    transitions: List[Dict[str, Any]] = []

    for row in rows:
        strategy_name = row["strategy_name"]
        try:
            eligibility = get_strategy_eligibility(
                strategy_name=strategy_name,
                user_id=owner_user_id,
                supabase=supabase,
            )
        except Exception as e:
            logger.exception(
                f"[STRATEGY_LIFECYCLE] {strategy_name}: eligibility check failed: {e}"
            )
            _emit_lifecycle_alert(
                supabase=supabase,
                severity="warning",
                message=(
                    f"strategy_lifecycle_eval eligibility failure for "
                    f"{strategy_name}: {e}"
                ),
                metadata={
                    "phase": "eligibility_check",
                    "strategy_name": strategy_name,
                },
            )
            continue

        if not eligibility["eligible"]:
            continue

        try:
            transition = _promote_strategy_to_full(
                strategy_name=strategy_name,
                eligibility=eligibility,
                supabase=supabase,
            )
            transitions.append(transition)
        except Exception as e:
            logger.exception(
                f"[STRATEGY_LIFECYCLE] {strategy_name}: promotion write failed: {e}"
            )
            _emit_lifecycle_alert(
                supabase=supabase,
                severity="warning",
                message=(
                    f"strategy_lifecycle_eval promotion-write failure for "
                    f"{strategy_name}: {e}"
                ),
                metadata={
                    "phase": "promotion_write",
                    "strategy_name": strategy_name,
                    "cumulative_pl": eligibility.get("cumulative_pl"),
                    "trade_count": eligibility.get("trade_count"),
                },
            )

    return transitions


def _promote_strategy_to_full(
    strategy_name: str,
    eligibility: Dict[str, Any],
    supabase,
) -> Dict[str, Any]:
    """Update lifecycle row to LIVE_FULL + write audit alert.

    Caller (``evaluate_strategy_lifecycle``) wraps in try/except so
    a write failure here is logged + alerted but doesn't abort the
    sweep over other EXPERIMENTAL strategies.
    """
    transition_reason = {
        "reason": "graduation_eligible",
        "previous_state": "experimental",
        "cumulative_realized_pl": eligibility["cumulative_pl"],
        "trade_count": eligibility["trade_count"],
        "min_required_trades": eligibility["min_required_trades"],
    }

    supabase.table("strategy_lifecycle_states").update({
        "current_state": "live_full",
        "transitioned_at": datetime.now(timezone.utc).isoformat(),
        "transition_reason": transition_reason,
        "closed_trade_count": eligibility["trade_count"],
        "cumulative_realized_pl": eligibility["cumulative_pl"],
    }).eq("strategy_name", strategy_name).execute()

    _emit_lifecycle_alert(
        supabase=supabase,
        severity="info",
        message=(
            f"Strategy {strategy_name} graduated experimental -> live_full "
            f"(pl=${eligibility['cumulative_pl']:.2f}, "
            f"trades={eligibility['trade_count']})"
        ),
        metadata={
            "strategy_name": strategy_name,
            **transition_reason,
        },
        alert_type="strategy_graduated_to_full",
    )

    logger.warning(
        f"[STRATEGY_LIFECYCLE] {strategy_name} graduated "
        f"experimental -> live_full "
        f"(pl=${eligibility['cumulative_pl']:.2f}, "
        f"trades={eligibility['trade_count']})"
    )

    return {
        "strategy_name": strategy_name,
        "previous_state": "experimental",
        "new_state": "live_full",
        **{k: v for k, v in transition_reason.items() if k != "previous_state"},
    }


def _emit_lifecycle_alert(
    supabase,
    severity: str,
    message: str,
    metadata: Dict[str, Any],
    alert_type: str = "strategy_lifecycle_eval_error",
) -> None:
    """Wrapper around the canonical ``alert()`` helper for lifecycle
    audit + error rows. Soft-fails (logger.exception) on alert-write
    error per doctrine valid-pattern 5 (no recursion).
    """
    try:
        from packages.quantum.observability.alerts import alert
        alert(
            supabase,
            alert_type=alert_type,
            severity=severity,
            message=message,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "[STRATEGY_LIFECYCLE] alert write failed",
            extra={"alert_type": alert_type, "severity": severity},
        )


# Valid phase transitions
VALID_TRANSITIONS = {
    "alpaca_paper": "micro_live",
    "micro_live": "full_auto",
}

# Phase → execution mode mapping
PHASE_TO_EXECUTION_MODE = {
    "alpaca_paper": "alpaca_paper",
    "micro_live": "alpaca_live",
    "full_auto": "alpaca_live",
}


def _chicago_today() -> date:
    """Get today's date in Chicago timezone."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Chicago")).date()


class ProgressionService:
    """Single source of truth for go-live progression."""

    def __init__(self, supabase: Client):
        self.client = supabase

    def get_state(self, user_id: str) -> Dict[str, Any]:
        """Return current phase + gate status. Creates row if missing."""
        try:
            res = self.client.table(TABLE) \
                .select("*") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()

            if res.data:
                return res.data[0]

            # Auto-create for new users
            res = self.client.table(TABLE).insert({
                "user_id": user_id,
                "current_phase": "alpaca_paper",
                "alpaca_paper_started_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return res.data[0]
        except Exception as e:
            logger.error(f"[PROGRESSION] Failed to get state for {user_id}: {e}")
            return {
                "user_id": user_id,
                "current_phase": "alpaca_paper",
                "alpaca_paper_green_days": 0,
                "alpaca_paper_green_days_required": 4,
            }

    def record_trading_day(
        self,
        user_id: str,
        trade_date: date,
        realized_pnl: float,
    ) -> Dict[str, Any]:
        """
        Called at end of each trading day.

        If realized_pnl > 0 (green day), increment green_days counter.
        If green_days >= required, auto-promote to micro_live.

        Returns updated state + whether promotion happened.
        """
        state = self.get_state(user_id)
        current_phase = state.get("current_phase", "alpaca_paper")

        # Only track green days during alpaca_paper phase
        if current_phase != "alpaca_paper":
            return {"state": state, "promoted": False, "reason": "not_in_alpaca_paper"}

        is_green = realized_pnl > 0
        green_days = state.get("alpaca_paper_green_days", 0)
        required = state.get("alpaca_paper_green_days_required", 4)

        if is_green:
            green_days += 1
            event_type = "green_day"
        else:
            event_type = "red_day"

        # Update state
        update = {
            "alpaca_paper_green_days": green_days,
            "alpaca_paper_last_green_date": trade_date.isoformat() if is_green else state.get("alpaca_paper_last_green_date"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Log the day
        self._log_event(user_id, event_type, details={
            "trade_date": trade_date.isoformat(),
            "realized_pnl": realized_pnl,
            "green_days_after": green_days,
            "required": required,
        })

        logger.info(
            f"[PROGRESSION] {user_id[:8]}: {event_type} "
            f"pnl=${realized_pnl:+,.2f} green_days={green_days}/{required}"
        )

        # Check auto-promotion gate
        promoted = False
        if green_days >= required:
            update["alpaca_paper_completed_at"] = datetime.now(timezone.utc).isoformat()
            update["current_phase"] = "micro_live"
            update["micro_live_started_at"] = datetime.now(timezone.utc).isoformat()
            promoted = True

            self._log_event(user_id, "promotion", from_phase="alpaca_paper", to_phase="micro_live", details={
                "green_days": green_days,
                "required": required,
                "trigger": "auto_gate",
            })

            # Sync paper_baseline_capital to the micro_live starting balance.
            # This ensures CashService uses the correct capital base post-promotion.
            try:
                from packages.quantum.brokers.alpaca_client import get_alpaca_client
                alpaca = get_alpaca_client()
                if alpaca:
                    acct = alpaca.get_account()
                    micro_live_capital = acct.get("equity", 500.0)
                else:
                    micro_live_capital = 500.0  # Default micro_live cap from promotion path

                self.client.table("v3_go_live_state") \
                    .update({"paper_baseline_capital": micro_live_capital}) \
                    .eq("user_id", user_id) \
                    .execute()

                logger.info(
                    f"[PROGRESSION] Synced paper_baseline_capital={micro_live_capital} "
                    f"for micro_live transition user={user_id[:8]}"
                )
            except Exception as e:
                logger.error(f"[PROGRESSION] Failed to sync baseline capital: {e}")

            logger.info(
                f"[PROGRESSION] PROMOTION: {user_id[:8]} "
                f"alpaca_paper → micro_live ({green_days} green days)"
            )

        self.client.table(TABLE) \
            .update(update) \
            .eq("user_id", user_id) \
            .execute()

        state.update(update)
        return {"state": state, "promoted": promoted}

    def promote(
        self,
        user_id: str,
        to_phase: str,
        trigger_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Promote user to next phase. Validates the transition is allowed.

        trigger_details: optional dict written to go_live_progression_log
            for the audit trail. Defaults to {"trigger": "manual"} for
            backwards compatibility with manual operator bypass. Auto-
            promotion paths (e.g., evaluate_full_auto_promotion) pass
            their own trigger context (gate values, equity, etc.).
        """
        state = self.get_state(user_id)
        current = state.get("current_phase")

        expected_next = VALID_TRANSITIONS.get(current)
        if expected_next != to_phase:
            return {
                "error": f"Cannot promote from {current} to {to_phase}. "
                         f"Expected next phase: {expected_next}",
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        update: Dict[str, Any] = {
            "current_phase": to_phase,
            "updated_at": now_iso,
        }

        if to_phase == "micro_live":
            update["alpaca_paper_completed_at"] = now_iso
            update["micro_live_started_at"] = now_iso
        elif to_phase == "full_auto":
            update["micro_live_completed_at"] = now_iso
            update["full_auto_started_at"] = now_iso

        self.client.table(TABLE) \
            .update(update) \
            .eq("user_id", user_id) \
            .execute()

        details = trigger_details if trigger_details is not None else {"trigger": "manual"}
        self._log_event(user_id, "promotion", from_phase=current, to_phase=to_phase, details=details)

        trigger_label = details.get("trigger", "unspecified")
        logger.info(
            f"[PROGRESSION] PROMOTION ({trigger_label}): "
            f"{user_id[:8]} {current} → {to_phase}"
        )

        state.update(update)
        return {"state": state, "promoted": True}

    def is_eligible_for_full_auto(self, user_id: str) -> Dict[str, Any]:
        """Evaluate the three gates for micro_live → full_auto promotion.

        Gates (all must pass):
          1. broker equity ≥ EQUITY_THRESHOLD_FULL_AUTO ($1500)
          2. cumulative realized_pl > 0 across Alpaca-real closed trades
          3. alpaca_real_trade_count ≥ MIN_TRADES_FULL_AUTO (3)

        Equity is read from broker (Alpaca-authoritative, not DB cache)
        per the wrapper-drift fix in PR #864 + cash_service alert in
        PR #865. Cumulative P&L and trade count use the shared
        get_alpaca_real_closed_trades helper that filters out internal-
        paper era simulations.

        Returns dict with `eligible` bool plus all three gate values
        and a human-readable `reason` string for audit + alert metadata.
        """
        # Gate 1: equity from broker truth
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        equity = 0.0
        try:
            alpaca = get_alpaca_client()
            if alpaca:
                acct = alpaca.get_account()
                equity = float(acct.get("equity") or 0)
        except Exception as e:
            logger.warning(f"[PROGRESSION] Failed to read equity for eligibility: {e}")

        # Gates 2 + 3: shared helper + computation
        real_trades = get_alpaca_real_closed_trades(user_id, self.client)
        cumulative_pl = cumulative_realized_pl(real_trades)
        trade_count = len(real_trades)

        eligible = (
            equity >= EQUITY_THRESHOLD_FULL_AUTO
            and cumulative_pl > 0
            and trade_count >= MIN_TRADES_FULL_AUTO
        )

        return {
            "eligible": eligible,
            "equity": equity,
            "cumulative_realized_pl": cumulative_pl,
            "alpaca_real_trade_count": trade_count,
            "reason": _build_full_auto_reason(equity, cumulative_pl, trade_count),
        }


def _build_full_auto_reason(
    equity: float, cumulative_pl: float, trade_count: int,
) -> str:
    """Human-readable reason string for full_auto eligibility decision."""
    if equity < EQUITY_THRESHOLD_FULL_AUTO:
        return f"equity_below_threshold (${equity:.2f} < ${EQUITY_THRESHOLD_FULL_AUTO:.2f})"
    if cumulative_pl <= 0:
        return f"cumulative_pl_not_positive (${cumulative_pl:.2f})"
    if trade_count < MIN_TRADES_FULL_AUTO:
        return f"insufficient_trades ({trade_count}/{MIN_TRADES_FULL_AUTO} required)"
    return "all_gates_passed"

    def get_execution_mode(self, user_id: str) -> str:
        """
        Returns the execution mode for order routing based on current phase.

        alpaca_paper → 'alpaca_paper'
        micro_live   → 'alpaca_live'
        full_auto    → 'alpaca_live'
        """
        state = self.get_state(user_id)
        phase = state.get("current_phase", "alpaca_paper")
        return PHASE_TO_EXECUTION_MODE.get(phase, "alpaca_paper")

    # ── Internal helpers ────────────────────────────────────────────

    def _log_event(
        self,
        user_id: str,
        event_type: str,
        from_phase: Optional[str] = None,
        to_phase: Optional[str] = None,
        details: Optional[Dict] = None,
    ) -> None:
        """Append to audit log."""
        try:
            self.client.table(LOG_TABLE).insert({
                "user_id": user_id,
                "event_type": event_type,
                "from_phase": from_phase,
                "to_phase": to_phase,
                "details": details or {},
            }).execute()
        except Exception as e:
            logger.warning(f"[PROGRESSION] Failed to log event: {e}")
