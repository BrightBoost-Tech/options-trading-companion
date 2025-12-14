from typing import List, Dict, Any, Optional
from supabase import Client
import warnings

class IVRegimeService:
    """
    DEPRECATED: Use RegimeEngineV3 snapshots instead.
    This class is kept for backward compatibility but should not be used in new code.
    """
    def __init__(self, supabase: Client):
        warnings.warn(
            "IVRegimeService is deprecated. Use RegimeEngineV3 instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.supabase = supabase

    def get_iv_context_for_symbols(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Legacy method to fetch IV context.
        """
        if not symbols:
            return {}

        try:
            res = self.supabase.table("scanner_universe")\
                .select("symbol, iv_rank, iv_regime")\
                .in_("symbol", symbols)\
                .execute()

            results = {}
            for row in res.data or []:
                sym = row["symbol"]
                results[sym] = {
                    "iv_rank": row.get("iv_rank"),
                    "iv_regime": row.get("iv_regime")
                }
            return results
        except Exception as e:
            print(f"IVRegimeService Error: {e}")
            return {}
