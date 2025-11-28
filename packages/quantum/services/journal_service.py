# packages/quantum/services/journal_service.py
from supabase import Client
from typing import List, Dict, Any
from datetime import datetime

class JournalService:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client

    def get_journal_entries(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves all journal entries for a given user."""
        response = self.supabase.table("trade_journal_entries").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
        return response.data

    def add_trade(self, user_id: str, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Adds a new trade to the journal."""
        trade_data['user_id'] = user_id

        # Ensure dates are in the correct format
        if 'entry_date' in trade_data:
            trade_data['entry_date'] = datetime.fromisoformat(trade_data['entry_date']).isoformat()

        response = self.supabase.table("trade_journal_entries").insert(trade_data).execute()
        return response.data[0] if response.data else None

    def close_trade(self, user_id: str, trade_id: int, exit_date: str, exit_price: float) -> Dict[str, Any]:
        """Closes an existing trade and calculates P&L."""
        # First, get the trade to calculate P&L
        response = self.supabase.table("trade_journal_entries").select("*").eq("user_id", user_id).eq("id", trade_id).single().execute()
        trade = response.data

        if not trade:
            raise ValueError(f"Trade {trade_id} not found or user does not have access.")

        entry_price = trade.get('entry_price', 0)
        pnl = exit_price - entry_price
        pnl_pct = (pnl / abs(entry_price)) * 100 if entry_price != 0 else 0

        update_data = {
            "status": "closed",
            "exit_date": datetime.fromisoformat(exit_date).isoformat(),
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct
        }

        response = self.supabase.table("trade_journal_entries").update(update_data).eq("id", trade_id).execute()
        return response.data[0] if response.data else None
