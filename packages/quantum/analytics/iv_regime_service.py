from typing import List, Dict, Optional
from supabase import Client

class IVRegimeService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_iv_context_for_symbols(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Returns { symbol: { iv_rank: float | None, iv_regime: str | None } }
        by querying scanner_universe for the given symbols.
        """
        if not symbols:
            return {}

        try:
            res = self.supabase.table("scanner_universe")\
                .select("symbol, iv_rank, iv_regime")\
                .in_("symbol", symbols)\
                .execute()

            result = {}
            for r in res.data or []:
                result[r["symbol"]] = {
                    "iv_rank": r.get("iv_rank"),
                    "iv_regime": r.get("iv_regime")
                }

            # Fill missing with None
            for s in symbols:
                if s not in result:
                    result[s] = {"iv_rank": None, "iv_regime": None}

            return result
        except Exception as e:
            print(f"Error fetching IV context: {e}")
            return {s: {"iv_rank": None, "iv_regime": None} for s in symbols}
