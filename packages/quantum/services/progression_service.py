"""
Progression Service — single source of truth for go-live state machine.

Phases: alpaca_paper → micro_live → full_auto

Gate from alpaca_paper → micro_live:
  - N consecutive green trading days (default 4)
  - A green day = total realized PnL from closed positions > $0

Gate from micro_live → full_auto:
  - Manual promotion (for now)

All trading-day calculations use Chicago timezone.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from supabase import Client

logger = logging.getLogger(__name__)

TABLE = "go_live_progression"
LOG_TABLE = "go_live_progression_log"

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

    def promote(self, user_id: str, to_phase: str) -> Dict[str, Any]:
        """
        Manual promotion (e.g., micro_live → full_auto).
        Validates the transition is allowed.
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

        self._log_event(user_id, "promotion", from_phase=current, to_phase=to_phase, details={
            "trigger": "manual",
        })

        logger.info(f"[PROGRESSION] MANUAL PROMOTION: {user_id[:8]} {current} → {to_phase}")

        state.update(update)
        return {"state": state, "promoted": True}

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
