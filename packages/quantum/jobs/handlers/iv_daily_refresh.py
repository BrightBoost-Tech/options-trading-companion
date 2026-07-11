from typing import Dict, Any, List
from datetime import datetime, timedelta
import traceback

from supabase import Client

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService

JOB_NAME = "iv_daily_refresh"

def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Handler for iv_daily_refresh job.
    Refreshes IV points for universe.
    """
    print(f"[{JOB_NAME}] Starting job with payload: {payload}")

    try:
        # 1. Initialize Supabase Client
        client = get_admin_client()

        # 2. Fetch Universe
        try:
            universe_service = UniverseService(client)
            candidates = universe_service.get_scan_candidates(
                limit=200,
                caller="iv_daily_refresh.run",
            )
            symbols = list(set([c['symbol'] for c in candidates] + ['SPY', 'QQQ', 'IWM', 'DIA']))
            print(f"[{JOB_NAME}] Found {len(symbols)} symbols to process.")
        except Exception as e:
            print(f"[{JOB_NAME}] Error fetching universe: {e}")
            raise e

        # 3. Process Symbols.
        #
        # #115 PR-A Layer 4 fix (2026-05-09): per-symbol stats now
        # split into four buckets so the load-bearing ``ok`` count
        # reflects ACTUAL DB writes, not handler-side optimism. The
        # post-loop verification at the bottom compares ``stats["ok"]``
        # against ``count_rows_for_date`` and fires
        # ``iv_handler_accounting_mismatch`` if they disagree —
        # makes Layer 4 silent regression impossible.
        truth_layer = MarketDataTruthLayer()
        iv_repo = IVRepository(client)
        stats = {
            "ok": 0,           # confirmed DB writes
            "failed": 0,       # write attempted, repository returned False
            "missing_data": 0, # upstream produced no IV (skip pre-write)
            "errors": [],
        }
        failed_symbols: List[Dict[str, Any]] = []
        run_ts = datetime.now()
        as_of_date_str = run_ts.strftime('%Y-%m-%d')

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
                    stats["missing_data"] += 1
                    failed_symbols.append({"symbol": sym, "reason": "no_spot"})
                    continue

                # 3. Get Chain via TruthLayer (pass spot to avoid redundant snapshot fetch)
                chain = truth_layer.option_chain(norm_sym, strike_range=0.20, spot=spot)

                if not chain:
                    stats["missing_data"] += 1
                    failed_symbols.append({"symbol": sym, "reason": "no_chain"})
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
                    stats["missing_data"] += 1
                    failed_symbols.append({"symbol": sym, "reason": "iv_30d_none"})
                    continue

                # #115 PR-A Layer 4: check upsert return value.
                # Pre-fix the handler trusted the wrapper's None
                # return and incremented ok regardless.
                write_succeeded = iv_repo.upsert_iv_point(sym, result, run_ts)
                if write_succeeded:
                    stats["ok"] += 1
                else:
                    stats["failed"] += 1
                    failed_symbols.append({"symbol": sym, "reason": "db_write_failed"})
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{sym}: {e}")
                failed_symbols.append({"symbol": sym, "reason": f"exception:{type(e).__name__}"})

        # #115 PR-A Layer 4 — accounting verification.
        # Query the table for actual rows written this cycle and
        # compare against handler-reported ok count. Disagreement
        # means the handler is lying (silent wrapper failure,
        # Layer 5 wrapper-drift, etc.) — fire critical alert so
        # the regression surfaces at the next monitoring sweep
        # rather than waiting for downstream consumers to notice
        # the empty pipeline.
        actual_rows = iv_repo.count_rows_for_date(as_of_date_str)
        accounting_match = (actual_rows == stats["ok"])
        if not accounting_match and actual_rows >= 0:
            try:
                from packages.quantum.observability.alerts import (
                    alert, _get_admin_supabase,
                )
                alert(
                    _get_admin_supabase(),
                    alert_type="iv_handler_accounting_mismatch",
                    severity="critical",
                    message=(
                        f"iv_daily_refresh handler reported "
                        f"{stats['ok']} writes but DB has {actual_rows} "
                        f"rows for {as_of_date_str}"
                    ),
                    metadata={
                        "stats_ok": stats["ok"],
                        "actual_rows": actual_rows,
                        "delta": stats["ok"] - actual_rows,
                        "as_of_date": as_of_date_str,
                        "doctrine_ref": "wrapper-drift Layer 4 / anti-pattern 2",
                    },
                )
            except Exception as alert_err:
                # Per loud-error doctrine valid-pattern 5: alert
                # write failure must not undo the handler result.
                print(f"[{JOB_NAME}] accounting alert write failed: {alert_err}")

        print(f"[{JOB_NAME}] Finished. Stats: {stats}, "
              f"actual_rows={actual_rows}, match={accounting_match}")
        # ALL-MISSING → NOT GREEN (2026-07-11, F-A4-1 cousin): a refresh where
        # EVERY symbol produced no IV (ok==0 with symbols present) is a producer
        # failure, not a healthy no-op. Emit counts.errors so the runner's typed
        # contract records it PARTIAL (visible). Some-missing (ok>0) stays green —
        # individual symbols lacking IV history (new adds seasoning to 60d) is
        # normal and must not alarm.
        _all_missing = stats["ok"] == 0 and len(symbols) > 0
        return {
            "status": "ok",
            "counts": {"errors": stats["missing_data"] if _all_missing else 0},
            "stats": stats,
            "failed_symbols": failed_symbols[:20],  # truncate huge payloads
            "actual_rows_written": actual_rows,
            "accounting_match": accounting_match,
            "as_of_date": as_of_date_str,
            "total_processed": len(symbols),
        }

    except Exception as e:
        print(f"[{JOB_NAME}] Job failed: {e}")
        traceback.print_exc()
        raise e
