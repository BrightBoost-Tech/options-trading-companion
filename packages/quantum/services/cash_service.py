from typing import Optional, List
from supabase import Client

class CashService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        # Constants
        self.TRADE_SUGGESTIONS_TABLE = "trade_suggestions"

    async def get_deployable_capital(self, user_id: str) -> float:
        """
        Calculates the amount of capital available for new trades.
        1. Look up user's latest portfolio snapshot for buying_power.
        2. Fallback: sum CUR:USD / CASH positions from the `positions` table.
        3. Read user_settings.cash_buffer if present, default buffer = 0.
        4. Subtract estimated capital reserved in pending trade_suggestions.
        Returns a float deployable_capital (>= 0).
        """
        buying_power = 0.0

        # 1. Try to get buying_power from latest snapshot or plaid_items (similar to api.py logic)
        try:
            # Check plaid_items first as it's often more up-to-date for buying_power
            res = (
                self.supabase.table("plaid_items")
                .select("buying_power")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if res.data and res.data.get("buying_power") is not None:
                buying_power = float(res.data.get("buying_power"))
            else:
                # Fallback to sum of CASH positions
                pos_res = (
                    self.supabase.table("positions")
                    .select("quantity, current_price, symbol")
                    .eq("user_id", user_id)
                    .execute()
                )
                if pos_res.data:
                    for p in pos_res.data:
                        symbol = p.get("symbol", "").upper()
                        if "CUR:USD" in symbol or symbol == "CASH" or symbol == "USD":
                            qty = float(p.get("quantity", 0))
                            price = float(p.get("current_price", 1))
                            buying_power += qty * price
        except Exception as e:
            print(f"Error fetching buying power: {e}")
            # If we can't get buying power, we default to 0 to be safe
            buying_power = 0.0

        # 2. Get Cash Buffer
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
            print(f"Error fetching cash buffer: {e}")

        # 3. Calculate Reserved Capital (Pending Suggestions)
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

        # 4. Final Calculation
        deployable = buying_power - cash_buffer - reserved_capital
        return max(0.0, deployable)

    def check_capital_guardrail(self, cost_basis: float, deployable: float) -> bool:
        """Return True if this trade fits within deployable capital."""
        return cost_basis <= deployable
