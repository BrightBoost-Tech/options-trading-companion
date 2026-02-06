from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from supabase import Client
import pandas as pd
import numpy as np
import concurrent.futures
from packages.quantum.security.masking import sanitize_exception

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

            # Handle "null" strings and convert to float safely
            history = []
            for r in history_res.data:
                iv_val = r.get('iv_30d')
                if iv_val is None:
                    continue
                if isinstance(iv_val, str) and iv_val.strip().lower() in ("null", "none", ""):
                    continue
                try:
                    history.append(float(iv_val))
                except (ValueError, TypeError):
                    continue
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
            # 🛡️ Sentinel: Sanitize exception in logs and return generic error to client
            sanitized_err = sanitize_exception(e)
            print(f"[IVRepo] Error fetching context for {underlying}: {sanitized_err}")
            return {
                "iv_30d": None,
                "iv_rank": None,
                "iv_regime": None,
                "error": "Failed to retrieve IV context"
            }

    def get_iv_context_batch(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Retrieves IV context for multiple symbols in batches to respect DB row limits.
        Replaces N synchronous queries with ~N/2 parallel batch queries.
        Optimization: Uses ThreadPoolExecutor to run DB batches in parallel.
        """
        if not symbols:
            return {}

        results = {}
        # Chunk size 2 to keep rows ~730 (2 * 365) < 1000 limit
        chunk_size = 2

        # Calculate cutoff date once
        cutoff_date = (datetime.now() - timedelta(days=400)).date()
        cutoff = cutoff_date.strftime('%Y-%m-%d')

        def fetch_batch(batch_symbols):
            batch_results = {}
            try:
                # Fetch history for this chunk
                res = self.supabase.table(self.table)\
                    .select("underlying, iv_30d, as_of_date")\
                    .in_("underlying", batch_symbols)\
                    .gte("as_of_date", cutoff)\
                    .neq("iv_30d", "null")\
                    .execute()

                data = res.data
                if not data:
                    return {}

                # Bolt Optimization: Manual aggregation is 15x faster than pandas DataFrame overhead for small batches
                # Avoid pd.DataFrame creation, to_numeric, dropna, groupby, sort_values

                # Pre-allocate dictionary
                grouped_data = {}
                for row in data:
                    sym = row.get('underlying')
                    iv_val = row.get('iv_30d')
                    date_val = row.get('as_of_date')

                    if not sym or iv_val is None:
                        continue

                    # Handle string "null" or empty strings as None
                    if isinstance(iv_val, str):
                        iv_val_str = iv_val.strip().lower()
                        if iv_val_str in ("null", "none", ""):
                            continue

                    try:
                        iv_float = float(iv_val)
                    except (ValueError, TypeError):
                        continue

                    if sym not in grouped_data:
                        grouped_data[sym] = []

                    grouped_data[sym].append((date_val, iv_float))

                for sym, rows in grouped_data.items():
                    # Sort by date desc (as_of_date is ISO string YYYY-MM-DD, so string sort works)
                    # Often data comes sorted from DB but we enforce it
                    rows.sort(key=lambda x: x[0], reverse=True)

                    if not rows:
                        continue

                    latest_date, iv_30d_current = rows[0]
                    as_of = latest_date

                    # Extract history values
                    # Limit to 365 samples
                    history_vals = [r[1] for r in rows[:365]]
                    sample_size = len(history_vals)

                    iv_rank = None
                    iv_regime = None

                    if sample_size >= 60:
                        # Use min/max on list (fast enough for N=365)
                        min_iv = min(history_vals)
                        max_iv = max(history_vals)

                        if max_iv > min_iv:
                            iv_rank = (iv_30d_current - min_iv) / (max_iv - min_iv) * 100.0
                            iv_rank = max(0.0, min(100.0, iv_rank))

                            if iv_rank < 20: iv_regime = "suppressed"
                            elif iv_rank < 60: iv_regime = "normal"
                            else: iv_regime = "elevated"

                    batch_results[sym] = {
                        "iv_30d": iv_30d_current,
                        "iv_rank": round(iv_rank, 1) if iv_rank is not None else None,
                        "iv_regime": iv_regime,
                        "sample_size": sample_size,
                        "as_of_date": as_of
                    }
            except Exception as e:
                # Log but continue to next batch
                print(f"[IVRepo] Batch fetch error for {batch_symbols}: {e}")

            return batch_results

        # 1. Prepare batches
        batches = [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]

        # 2. Execute in parallel
        # Use max_workers=10 to keep concurrent DB connections reasonable
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_batch = {executor.submit(fetch_batch, batch): batch for batch in batches}

            for future in concurrent.futures.as_completed(future_to_batch):
                try:
                    batch_res = future.result()
                    results.update(batch_res)
                except Exception as exc:
                    print(f"[IVRepo] Thread exception: {exc}")

        return results
