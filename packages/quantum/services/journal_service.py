# packages/quantum/services/journal_service.py
from supabase import Client
from typing import List, Dict, Any
from datetime import datetime

class JournalService:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client

    def _sanitize_for_json(self, data: Any) -> Any:
        """
        Recursively converts objects to JSON-serializable types.
        Handles Pydantic models, classes, Enums, and common types.
        """
        if isinstance(data, dict):
            return {k: self._sanitize_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_for_json(item) for item in data]
        elif hasattr(data, "model_dump"):  # Pydantic v2
            return self._sanitize_for_json(data.model_dump())
        elif hasattr(data, "dict"):  # Pydantic v1
            return self._sanitize_for_json(data.dict())
        elif hasattr(data, "__dict__"):
            return self._sanitize_for_json(vars(data))
        elif hasattr(data, "isoformat"):  # datetime, date
            return data.isoformat()

        # Handle simple types and fallback
        try:
            if isinstance(data, (str, int, float, bool, type(None))):
                return data
            return str(data)
        except Exception:
            return str(data)

    def get_journal_entries(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves all journal entries for a given user."""
        try:
            response = self.supabase.table("trade_journal_entries").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
            return response.data if response.data else []
        except Exception as e:
            # Log error if possible, or return empty list to prevent crash
            print(f"Error fetching journal entries: {e}")
            return []

    def get_journal_stats(self, user_id: str) -> Dict[str, Any]:
        """Calculates journal statistics for a given user."""
        try:
            # Fetch all trades
            response = self.supabase.table("trade_journal_entries").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
            trades = response.data if response.data else []

            if not trades:
                return {
                    "stats": {
                        "win_rate": 0.0,
                        "total_pnl": 0.0,
                        "trade_count": 0,
                    },
                    "recent_trades": [],
                }

            # Filter for closed trades for stats calculation
            closed_trades = [t for t in trades if t.get('status') == 'closed']
            total_closed = len(closed_trades)

            wins = len([t for t in closed_trades if t.get('pnl', 0) > 0])
            total_pnl = sum([t.get('pnl', 0) for t in closed_trades])
            win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

            # Recent trades (already sorted by entry_date desc from query)
            recent_trades = trades[:5]

            return {
                "stats": {
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "trade_count": total_closed,
                },
                "recent_trades": recent_trades,
            }

        except Exception as e:
            print(f"Error calculating journal stats: {e}")
            return {
                "stats": {
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "trade_count": 0,
                },
                "recent_trades": [],
            }

    def add_trade(self, user_id: str, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Adds a new trade to the journal."""
        trade_data['user_id'] = user_id

        # Sanitize entire payload to prevent "not JSON serializable" errors
        # This handles Pydantic models (e.g. StrategyConfig) or other objects passed by mistake
        trade_data = self._sanitize_for_json(trade_data)

        # Ensure dates are in the correct format
        if 'entry_date' in trade_data:
            # If it's already a string, validate/reformat it
            if isinstance(trade_data['entry_date'], str):
                try:
                    trade_data['entry_date'] = datetime.fromisoformat(trade_data['entry_date']).isoformat()
                except ValueError:
                    pass # Keep as is if parsing fails, let DB decide or fail

        try:
            response = self.supabase.table("trade_journal_entries").insert(trade_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"⚠️  Journal insertion failed softly: {e}")
            return None

    def close_trade(self, user_id: str, trade_id: int, exit_date: str, exit_price: float) -> Dict[str, Any]:
        """Closes an existing trade and calculates P&L."""
        # First, get the trade to calculate P&L
        response = self.supabase.table("trade_journal_entries").select("*").eq("user_id", user_id).eq("id", trade_id).single().execute()
        trade = response.data

        if not trade:
            raise ValueError(f"Trade {trade_id} not found or user does not have access.")

        entry_price = trade.get('entry_price', 0)
        direction = trade.get('direction', 'Long')

        # Calculate P&L based on direction
        # Assuming 'Short' or 'Sell' means short position
        if direction and direction.upper() in ['SHORT', 'SELL']:
            pnl = entry_price - exit_price
        else:
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
