import logging
from typing import Optional, List
from supabase import Client

logger = logging.getLogger(__name__)


class CashService:
    # If buying_power is below this in paper mode and snapshot was missing,
    # fall back to paper_baseline_capital from v3_go_live_state.
    _PAPER_CAPITAL_THRESHOLD = 1.0

    def __init__(self, supabase: Client):
        self.supabase = supabase
        # Constants
        self.TRADE_SUGGESTIONS_TABLE = "trade_suggestions"

    async def get_deployable_capital(self, user_id: str) -> float:
        """
        Calculates the amount of capital available for new trades.
        1. Look up user's latest portfolio snapshot for buying_power.
        2. Fallback: sum CUR:USD / CASH positions from the `positions` table.
        2b. Paper-mode fallback: use paper_baseline_capital if buying_power
            is missing/tiny and ops mode is "paper".
        3. Read user_settings.cash_buffer if present, default buffer = 0.
        4. Subtract estimated capital reserved in pending trade_suggestions.
        Returns a float deployable_capital (>= 0).
        """
        buying_power = None
        snapshot_had_buying_power = False

        # 1. Try to get buying_power from latest portfolio_snapshots
        try:
            res = (
                self.supabase.table("portfolio_snapshots")
                .select("buying_power")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data and res.data[0].get("buying_power") is not None:
                buying_power = float(res.data[0]["buying_power"])
                snapshot_had_buying_power = True
        except Exception as e:
            print(f"CashService: error reading portfolio_snapshots.buying_power: {e}")

        # 2. Fallback: sum CUR:USD / CASH positions
        if buying_power is None:
            try:
                res = (
                    self.supabase.table("positions")
                    .select("symbol, quantity, current_price")
                    .eq("user_id", user_id)
                    .execute()
                )
                cash_total = 0.0
                for row in res.data or []:
                    sym = (row.get("symbol") or "").upper()
                    if sym in ["CUR:USD", "USD", "CASH", "MM", "USDOLLAR"]:
                        qty = float(row.get("quantity") or 0.0)
                        price = float(row.get("current_price") or 1.0)
                        cash_total += qty * price
                buying_power = cash_total
            except Exception as e:
                print(f"CashService: error aggregating cash from positions: {e}")
                buying_power = 0.0

        # 2b. Paper-mode fallback: if snapshot was missing and buying_power
        #     is still tiny, use paper_baseline_capital from v3_go_live_state.
        if not snapshot_had_buying_power and (buying_power or 0) < self._PAPER_CAPITAL_THRESHOLD:
            buying_power = self._paper_baseline_fallback(user_id, buying_power or 0.0)

        # 3. Get Cash Buffer
        cash_buffer = 0.0
        try:
            settings_res = (
                self.supabase.table("user_settings")
                .select("cash_buffer")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if settings_res.data and settings_res.data.get("cash_buffer") is not None:
                cash_buffer = float(settings_res.data.get("cash_buffer"))
        except Exception as e:
            # print(f"Error fetching cash buffer: {e}") # Harmless if missing
            pass

        # 4. Calculate Reserved Capital (Pending Suggestions)
        reserved_capital = 0.0
        try:
            pending_res = (
                self.supabase.table(self.TRADE_SUGGESTIONS_TABLE)
                .select("sizing_metadata")
                .eq("user_id", user_id)
                .eq("status", "pending")
                .execute()
            )
            if pending_res.data:
                for row in pending_res.data:
                    meta = row.get("sizing_metadata") or {}
                    # Assuming sizing_metadata has 'capital_required'
                    cap_req = meta.get("capital_required", 0.0)
                    reserved_capital += float(cap_req)
        except Exception as e:
            print(f"Error fetching reserved capital: {e}")

        # 5. Final Calculation
        deployable = buying_power - cash_buffer - reserved_capital
        return max(0.0, deployable)

    def _paper_baseline_fallback(self, user_id: str, current_buying_power: float) -> float:
        """
        Paper-mode fallback: read paper_baseline_capital from v3_go_live_state.
        Only applies when global ops mode == "paper".
        Returns current_buying_power unchanged if not in paper mode or on error.
        """
        try:
            from packages.quantum.ops_endpoints import get_global_ops_control
            ops = get_global_ops_control()
            if ops.get("mode") != "paper":
                return current_buying_power
        except Exception:
            return current_buying_power

        baseline = 100_000.0
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
        except Exception as e:
            logger.warning("[CAPITAL] Failed to read paper_baseline_capital, using default: %s", e)

        logger.info(
            "[CAPITAL] paper fallback used baseline=%s user_id=%s",
            baseline, user_id,
        )
        return baseline

    def check_capital_guardrail(self, cost_basis: float, deployable: float) -> bool:
        """Return True if this trade fits within deployable capital."""
        return cost_basis <= deployable
