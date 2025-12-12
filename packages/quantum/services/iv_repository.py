from typing import Dict, Optional, Any, List
from datetime import datetime
from supabase import Client

class IVRepository:
    """
    Handles persistence and retrieval of IV data for underlying assets.
    """

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.table = "underlying_iv_points"

    def upsert_iv_point(self, underlying: str, data: Dict[str, Any], as_of_ts: datetime) -> None:
        """
        Upserts an IV point record.
        """
        payload = {
            "underlying": underlying,
            "as_of_date": as_of_ts.strftime('%Y-%m-%d'),
            "as_of_ts": as_of_ts.isoformat(),
            "spot": data.get("inputs", {}).get("spot", 0),
            "iv_30d": data.get("iv_30d"),
            "iv_30d_method": data.get("iv_30d_method", "unknown"),
            "expiry1": data.get("expiry1"),
            "expiry2": data.get("expiry2"),
            "iv1": data.get("iv1"),
            "iv2": data.get("iv2"),
            "strike1": data.get("strike1"),
            "strike2": data.get("strike2"),
            "source": "polygon",
            "quality_score": data.get("quality_score"),
            "inputs": data.get("inputs"),
        }

        try:
            self.supabase.table(self.table).upsert(
                payload,
                on_conflict="underlying, as_of_date"
            ).execute()
        except Exception as e:
            print(f"[IVRepo] Upsert failed for {underlying}: {e}")

    def get_iv_context(self, underlying: str) -> Dict[str, Any]:
        """
        Retrieves the latest IV context including rank and regime.
        """
        try:
            # 1. Get latest point
            # We fetch 1 row ordered by date desc
            latest_res = self.supabase.table(self.table)\
                .select("*")\
                .eq("underlying", underlying)\
                .order("as_of_date", desc=True)\
                .limit(1)\
                .execute()

            latest = latest_res.data[0] if latest_res.data else None

            if not latest or not latest.get('iv_30d'):
                return {
                    "iv_30d": None,
                    "iv_rank": None,
                    "iv_regime": None,
                    "sample_size": 0
                }

            iv_30d_current = float(latest['iv_30d'])

            # 2. Get history for Rank
            # Fetch last 365 days of points where iv_30d is not null
            # Note: Supabase/PostgREST limit might apply, but we need enough samples.
            # Default limit is usually 1000, which covers > 2 years of daily data.
            history_res = self.supabase.table(self.table)\
                .select("iv_30d")\
                .eq("underlying", underlying)\
                .neq("iv_30d", "null")\
                .order("as_of_date", desc=True)\
                .limit(365)\
                .execute()

            history = [float(r['iv_30d']) for r in history_res.data if r.get('iv_30d') is not None]
            sample_size = len(history)

            iv_rank = None
            iv_regime = None

            if sample_size >= 60: # Min sample size from requirements
                min_iv = min(history)
                max_iv = max(history)

                if max_iv > min_iv:
                    iv_rank = (iv_30d_current - min_iv) / (max_iv - min_iv) * 100.0
                    iv_rank = max(0.0, min(100.0, iv_rank))

                    # Classify regime
                    # Using standardized thresholds from memory/constants
                    if iv_rank < 20:
                        iv_regime = "suppressed"
                    elif iv_rank < 60:
                        iv_regime = "normal"
                    else:
                        iv_regime = "elevated"

            return {
                "iv_30d": iv_30d_current,
                "iv_rank": round(iv_rank, 1) if iv_rank is not None else None,
                "iv_regime": iv_regime,
                "sample_size": sample_size,
                "as_of_date": latest['as_of_date']
            }

        except Exception as e:
            print(f"[IVRepo] Error fetching context for {underlying}: {e}")
            return {
                "iv_30d": None,
                "iv_rank": None,
                "iv_regime": None,
                "error": str(e)
            }
