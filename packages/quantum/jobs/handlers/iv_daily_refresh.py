from typing import Dict, Any, List
from datetime import datetime, timedelta
import traceback

from supabase import Client

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService

JOB_NAME = "iv-daily-refresh"

def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Handler for iv-daily-refresh job.
    Refreshes IV points for universe.
    """
    print(f"[{JOB_NAME}] Starting job with payload: {payload}")

    try:
        # 1. Initialize Supabase Client
        client = get_admin_client()

        # 2. Fetch Universe
        try:
            universe_service = UniverseService(client)
            candidates = universe_service.get_scan_candidates(limit=200)
            symbols = list(set([c['symbol'] for c in candidates] + ['SPY', 'QQQ', 'IWM', 'DIA']))
            print(f"[{JOB_NAME}] Found {len(symbols)} symbols to process.")
        except Exception as e:
            print(f"[{JOB_NAME}] Error fetching universe: {e}")
            raise e

        # 3. Process Symbols
        truth_layer = MarketDataTruthLayer()
        iv_repo = IVRepository(client)
        stats = {"ok": 0, "failed": 0, "errors": []}

        for sym in symbols:
            try:
                # 1. Normalize symbol
                norm_sym = truth_layer.normalize_symbol(sym)

                # 2. Get Spot Price via Snapshot (TruthLayer)
                snapshots = truth_layer.snapshot_many([norm_sym])
                snap = snapshots.get(norm_sym, {})
                quote = snap.get("quote", {})
                spot = quote.get("mid") or quote.get("last") or 0.0

                # Fallback to history if spot missing
                if spot <= 0:
                    end_dt = datetime.now()
                    start_dt = end_dt - timedelta(days=5)
                    bars = truth_layer.daily_bars(norm_sym, start_dt, end_dt)
                    if bars:
                        spot = bars[-1]["close"]

                if spot <= 0:
                    stats["failed"] += 1
                    continue

                # 3. Get Chain via TruthLayer (pass spot to avoid redundant snapshot fetch)
                chain = truth_layer.option_chain(norm_sym, strike_range=0.20, spot=spot)

                if not chain:
                    stats["failed"] += 1
                    continue

                # 4. Adapt Chain for IVPointService (Legacy Compatibility)
                adapted_chain = []
                for c in chain:
                    adapted_chain.append({
                        "details": {
                            "expiration_date": c.get("expiry"),
                            "strike_price": c.get("strike"),
                            "contract_type": c.get("right")
                        },
                        "greeks": c.get("greeks") or {},
                        "implied_volatility": c.get("iv")
                    })

                result = IVPointService.compute_atm_iv_target_from_chain(adapted_chain, spot, datetime.now())
                if result.get("iv_30d") is None:
                    stats["failed"] += 1
                else:
                    iv_repo.upsert_iv_point(sym, result, datetime.now())
                    stats["ok"] += 1
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{sym}: {e}")

        print(f"[{JOB_NAME}] Finished. Stats: {stats}")
        return {"status": "ok", "stats": stats}

    except Exception as e:
        print(f"[{JOB_NAME}] Job failed: {e}")
        traceback.print_exc()
        raise e
