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


def get_alpaca_real_closed_trades(
    user_id: str,
    supabase,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
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

    Returns:
        List of paper_positions row dicts with at least id and realized_pl.
        Empty list if no qualifying trades.
    """
    query = supabase.table("paper_positions") \
        .select("id, realized_pl, closed_at") \
        .eq("user_id", user_id) \
        .eq("status", "closed")
    if since is not None:
        query = query.gte("closed_at", since.isoformat())
    if until is not None:
        query = query.lte("closed_at", until.isoformat())

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
