from typing import List, Dict, Optional
import os
from datetime import datetime, timedelta
from supabase import Client
import numpy as np
import sys
import os

# Fix import for when running from different contexts
from packages.quantum.market_data import PolygonService

class UniverseService:
    # Top 50 liquid tickers + broad market ETFs
    BASE_UNIVERSE = [
        "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "XLK", "XLF", "XLV", "XLY",
        "XLP", "XLE", "XLI", "XLB", "XLC", "XLU", "SMH", "HYG", "EEM", "FXI",
        "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "NVDA", "AMD",
        "NFLX", "INTC", "CSCO", "CMCSA", "PEP", "AVGO", "TXN", "ADBE", "QCOM",
        "COST", "TMUS", "AMGN", "CHTR", "SBUX", "PYPL", "INTU", "GILD", "FISV",
        "BKNG", "ADP", "ISRG", "MDLZ", "REGN", "VRTX", "CSX", "MU", "AMAT"
    ]

    def __init__(self, supabase: Client, polygon_service: PolygonService = None):
        self.supabase = supabase
        self.polygon = polygon_service or PolygonService()

    def sync_universe(self):
        """
        Upserts the base universe into scanner_universe table.
        This effectively 'seeds' the universe.
        """
        print("Syncing universe with base list...")
        data = []
        for symbol in self.BASE_UNIVERSE:
            data.append({
                "symbol": symbol,
                "is_active": True,
                "last_updated": datetime.now().isoformat()
            })

        try:
            # Upsert symbols. We preserve existing fields where not specified
            # but in Supabase upsert requires fetching or just overwrite.
            # We just overwrite 'is_active' and 'last_updated' effectively if conflict.
            self.supabase.table("scanner_universe").upsert(data, on_conflict="symbol").execute()
            print(f"Synced {len(data)} symbols to scanner_universe.")
        except Exception as e:
            print(f"Error syncing universe: {e}")

    @staticmethod
    def classify_iv_regime(iv_rank: float | None) -> str | None:
        # Thresholds defined locally or could be top-level constants.
        # Repeating for clarity if not top-level.
        IV_RANK_SUPPRESSED_THRESHOLD = 20
        IV_RANK_ELEVATED_THRESHOLD = 60

        if iv_rank is None:
            return None
        if iv_rank < IV_RANK_SUPPRESSED_THRESHOLD: return "suppressed"
        if iv_rank < IV_RANK_ELEVATED_THRESHOLD: return "normal"
        return "elevated"

    def update_metrics(self):
        """
        Iterates over active symbols and updates metrics using Polygon.
        """
        print("[UniverseService] Updating universe metrics...")
        try:
            res = self.supabase.table("scanner_universe").select("symbol").eq("is_active", True).execute()
            symbols = [r['symbol'] for r in res.data]
        except Exception as e:
            print(f"[UniverseService] Error fetching active symbols: {e}")
            return

        updates = []
        for sym in symbols:
            try:
                # 1. Basic Details (Sector, Market Cap)
                details = self.polygon.get_ticker_details(sym)
                market_cap = details.get("market_cap", 0)
                sector = details.get("sic_description", "Unknown")

                # 2. Volume (Avg 30d) & IV Rank
                # We use get_historical_prices which now returns volumes
                avg_vol = 0

                try:
                    hist = self.polygon.get_historical_prices(sym, days=30)
                    if hist and 'volumes' in hist:
                        vols = hist['volumes']
                        if vols:
                            avg_vol = int(np.mean(vols))
                except Exception as e:
                    # print(f"Error fetching history for {sym}: {e}")
                    pass

                iv_rank = self.polygon.get_iv_rank(sym)
                iv_regime = self.classify_iv_regime(iv_rank)

                # 3. Liquidity Score (0-100)
                # Heuristic:
                # - Market Cap (Max 40 pts): >100B=40, >10B=30, >2B=20
                # - Volume (Max 40 pts): >10M=40, >1M=30, >100k=10
                # - IV Rank Presence (Max 20 pts): If we have IV rank, data is good.

                l_score = 0

                # Market Cap Score
                if market_cap:
                    if market_cap > 100_000_000_000: l_score += 40
                    elif market_cap > 10_000_000_000: l_score += 30
                    elif market_cap > 2_000_000_000: l_score += 20

                # Volume Score
                if avg_vol > 10_000_000: l_score += 40
                elif avg_vol > 1_000_000: l_score += 30
                elif avg_vol > 200_000: l_score += 10

                # IV Rank Score
                if iv_rank is not None:
                    l_score += 20

                updates.append({
                    "symbol": sym,
                    "sector": sector,
                    "market_cap": market_cap,
                    "avg_volume_30d": avg_vol,
                    "iv_rank": iv_rank,
                    "iv_regime": iv_regime,
                    "liquidity_score": min(100, l_score),
                    "last_updated": datetime.now().isoformat()
                })

            except Exception as e:
                print(f"[UniverseService] Error updating {sym}: {e}")

        if updates:
            try:
                self.supabase.table("scanner_universe").upsert(updates).execute()
                print(f"[UniverseService] Updated metrics for {len(updates)} symbols.")
            except Exception as e:
                print(f"[UniverseService] Error saving metrics: {e}")

    def get_scan_candidates(self, limit: int = 30) -> List[Dict]:
        """
        Returns top candidates for scanning.
        Returns list of dicts: {'symbol': str, 'earnings_date': str | None}
        """
        try:
            # Query: active, sort by liquidity_score desc, limit
            res = self.supabase.table("scanner_universe")\
                .select("symbol, earnings_date")\
                .eq("is_active", True)\
                .order("liquidity_score", desc=True)\
                .limit(limit)\
                .execute()

            # Return dicts
            candidates = []
            for r in res.data:
                candidates.append({
                    "symbol": r["symbol"],
                    "earnings_date": r.get("earnings_date")
                })

            if candidates:
                return candidates
        except Exception as e:
            print(f"Error getting candidates from DB: {e}")

        # Fallback to a slice of BASE_UNIVERSE if DB fails or is empty
        print("Falling back to BASE_UNIVERSE")
        return [{"symbol": s, "earnings_date": None} for s in self.BASE_UNIVERSE[:limit]]
