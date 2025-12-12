from typing import Dict, Any, Optional
from supabase import Client
import statistics

class ExitStatsService:
    @staticmethod
    def get_stats(
        underlying: str,
        regime: str,
        strategy: str,
        supabase_client: Optional[Client] = None
    ) -> Dict[str, Any]:
        """
        Retrieves historical performance stats for a given exit strategy.
        Queries trade_executions table for realized P&L on the symbol.
        """

        if not supabase_client:
             return {
                "win_rate": None,
                "avg_pnl": None,
                "sample_size": 0,
                "regime": regime,
                "insufficient_history": True
            }

        try:
            # Fetch completed trades for this symbol
            # We assume 'realized_pnl' is not null for completed trades
            response = supabase_client.table("trade_executions") \
                .select("realized_pnl") \
                .eq("symbol", underlying) \
                .not_.is_("realized_pnl", "null") \
                .execute()

            trades = response.data

            if not trades or len(trades) < 5:
                 return {
                    "win_rate": None,
                    "avg_pnl": None,
                    "sample_size": len(trades) if trades else 0,
                    "regime": regime,
                    "insufficient_history": True
                }

            outcomes = [t["realized_pnl"] for t in trades]
            sample_size = len(outcomes)
            wins = len([x for x in outcomes if x > 0])
            win_rate = wins / sample_size
            avg_pnl = statistics.mean(outcomes)

            return {
                "win_rate": win_rate,
                "avg_pnl": avg_pnl,
                "sample_size": sample_size,
                "regime": regime,
                "insufficient_history": False
            }

        except Exception as e:
            print(f"[ExitStatsService] Error fetching stats for {underlying}: {e}")
            return {
                "win_rate": None,
                "avg_pnl": None,
                "sample_size": 0,
                "regime": regime,
                "insufficient_history": True
            }
