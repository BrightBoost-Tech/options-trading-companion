import logging
from typing import Optional, List
from supabase import Client

logger = logging.getLogger(__name__)


class CashService:
    # If buying_power is below this in paper mode, fall back to
    # paper_baseline_capital from v3_go_live_state.  Matches the micro-tier
    # scan minimum so paper accounts are never blocked by stale snapshots.
    _PAPER_CAPITAL_THRESHOLD = 15.0

    def __init__(self, supabase: Client):
        self.supabase = supabase
        # Constants
        self.TRADE_SUGGESTIONS_TABLE = "trade_suggestions"

    async def get_deployable_capital(self, user_id: str) -> float:
        """Return deployable capital for sizing.

        Reads Alpaca `options_buying_power` as the authoritative source.
        Falls back to `v3_go_live_state.paper_baseline_capital` if Alpaca
        is unavailable (paper-mode operation, missing options approval,
        or transient API failure).

        #93 fix (2026-05-01): replaced DB-derived computation that read
        `portfolio_snapshots.buying_power` (or summed CUR:USD positions)
        and subtracted `SUM(pending trade_suggestions.sizing_metadata
        .capital_required)`. The old logic produced phantom reservations
        because suggestions could stay `pending` indefinitely on
        paper_autopilot status-update bypass, and the buying_power source
        could lag broker truth (yesterday: stale Plaid CUR:USD = $247.84
        from 2026-03-26 against live Alpaca = $500). Same architectural
        pattern as 2026-04-16 `_compute_weekly_pnl` fix (commit 83872db)
        — DB-derived state diverging from broker truth resolved by
        reading broker-authoritative.

        Returns:
            float: deployable capital in dollars (>= 0)
        """
        from packages.quantum.services.equity_state import (
            get_alpaca_options_buying_power,
        )

        obp = get_alpaca_options_buying_power(user_id, supabase=self.supabase)
        if obp is not None:
            return max(0.0, float(obp))

        # Fallback: paper baseline (used when Alpaca unreachable, missing
        # options approval, or in paper-mode operation without a live
        # connection). Returns 0.0 if no baseline configured — caller's
        # `CapitalScanPolicy.can_scan` then skips the cycle, which is the
        # safe failure mode.
        return self._read_paper_baseline(user_id)

    def _read_paper_baseline(self, user_id: str) -> float:
        """Read `paper_baseline_capital` from `v3_go_live_state` regardless
        of ops mode. Used as the fallback when Alpaca is unavailable.

        Distinct from `_paper_baseline_fallback` (kept for backwards
        compat) which gates on ops.mode=="paper" and applies a
        `max(buying_power, baseline)` floor against an existing
        buying_power input. The new path has no buying_power input
        (Alpaca call already failed) and must work in any ops mode.
        """
        try:
            res = (
                self.supabase.table("v3_go_live_state")
                .select("paper_baseline_capital")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if res.data and res.data[0].get("paper_baseline_capital"):
                return float(res.data[0]["paper_baseline_capital"])
        except Exception as e:
            logger.warning(
                "[CashService] paper_baseline read failed: %s", e
            )
        return 0.0

    def _paper_baseline_fallback(self, user_id: str, current_buying_power: float) -> float:
        """
        Paper-mode capital consistency.

        - alpaca_paper phase: baseline = Alpaca paper balance (~$100k).
          Use max(buying_power, baseline) to handle stale snapshots.
        - micro_live / live phases: baseline should be synced to actual
          account balance at promotion time. Trust buying_power directly
          if baseline hasn't been updated from the $100k default.

        Returns adjusted buying_power based on current phase and baseline.
        """
        try:
            from packages.quantum.ops_endpoints import get_global_ops_control
            ops = get_global_ops_control()
            if ops.get("mode") != "paper":
                return current_buying_power
        except Exception:
            return current_buying_power

        baseline = 100_000.0
        current_phase = "alpaca_paper"
        try:
            res = (
                self.supabase.table("v3_go_live_state")
                .select("paper_baseline_capital")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if res.data and res.data[0].get("paper_baseline_capital"):
                baseline = float(res.data[0]["paper_baseline_capital"])

            # Check current phase from go_live_progression
            phase_res = (
                self.supabase.table("go_live_progression")
                .select("current_phase")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if phase_res.data and phase_res.data[0].get("current_phase"):
                current_phase = phase_res.data[0]["current_phase"]
        except Exception as e:
            logger.warning("[CAPITAL] Failed to read baseline/phase: %s", e)

        # In alpaca_paper, use max(buying_power, baseline) for stale snapshot protection
        if current_phase == "alpaca_paper":
            result = max(current_buying_power, baseline)
            if result > current_buying_power:
                logger.info(
                    "[CAPITAL] alpaca_paper: baseline=%s over buying_power=%s",
                    baseline, current_buying_power,
                )
            return result

        # In micro_live/live: if baseline was explicitly set (not default $100k),
        # use it as floor. Otherwise trust buying_power directly.
        if baseline != 100_000.0:
            return max(current_buying_power, baseline)

        return current_buying_power

    def check_capital_guardrail(self, cost_basis: float, deployable: float) -> bool:
        """Return True if this trade fits within deployable capital."""
        return cost_basis <= deployable
