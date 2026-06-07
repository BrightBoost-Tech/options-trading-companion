"""vol_signal_snapshot — Stage 1 vol-signal OBSERVE job (research only).

Standalone scheduled job (the iv_daily_refresh pattern), NOT an in-engine
hook: it reads underlying_iv_points + market data, computes the synthetic
vol-signal components, writes one vol_signal_observations row, and
backfills forward outcomes on prior rows. It imports NOTHING from the
scanner, trading, exit, or regime paths (asserted by
test_vol_signal_observe.TestImportBoundary) and changes no live decision.

Flag: VOL_SIGNAL_OBSERVE_ENABLED (lenient 1/true/yes/on, default OFF —
the job no-ops cheaply when off). Fail-soft throughout: missing inputs
are flagged in input_status and left NULL, never fabricated (the
stale-VIX-20.0 anti-pattern).
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List
import traceback

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.analytics import vol_signal

JOB_NAME = "vol_signal_snapshot"


def _adapt_chain(chain: List[Dict]) -> List[Dict]:
    """TruthLayer canonical chain → IVPointService raw-ish schema (same
    adaptation as iv_daily_refresh)."""
    adapted = []
    for c in chain:
        adapted.append({
            "details": {
                "expiration_date": c.get("expiry"),
                "strike_price": c.get("strike"),
                "contract_type": c.get("right"),
            },
            "greeks": c.get("greeks") or {},
            "implied_volatility": c.get("iv"),
        })
    return adapted


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    print(f"[{JOB_NAME}] Starting job with payload: {payload}")

    if not vol_signal.is_observe_enabled():
        return {"status": "flag_off", "flag": vol_signal.FLAG_ENV}

    try:
        client = get_admin_client()
        truth_layer = MarketDataTruthLayer()
        now = datetime.now()
        as_of_date = now.strftime("%Y-%m-%d")

        # 1. IV30 histories (full available series, ascending) + SPY spots.
        iv_histories: Dict[str, List[float]] = {}
        spy_spots: List[float] = []
        iv_dates: List[str] = []
        iv_by_date: Dict[str, float] = {}
        spot_by_date: Dict[str, float] = {}
        for sym in vol_signal.IV_SYMBOLS:
            try:
                res = client.table("underlying_iv_points") \
                    .select("as_of_date, iv_30d, spot") \
                    .eq("underlying", sym) \
                    .order("as_of_date", desc=False) \
                    .execute()
                rows = list(res.data or [])
                iv_histories[sym] = [float(r["iv_30d"]) for r in rows
                                     if r.get("iv_30d") is not None]
                if sym == "SPY":
                    spy_spots = [float(r["spot"]) for r in rows
                                 if r.get("spot") is not None]
                    for r in rows:
                        d = str(r["as_of_date"])
                        if r.get("iv_30d") is not None:
                            iv_dates.append(d)
                            iv_by_date[d] = float(r["iv_30d"])
                        if r.get("spot") is not None:
                            spot_by_date[d] = float(r["spot"])
            except Exception as e:
                print(f"[{JOB_NAME}] iv history fetch failed for {sym}: {e}")
                iv_histories[sym] = []  # flagged missing downstream — never defaulted

        # 2. SPY skew/term from the chain (None on any failure — flagged).
        spy_skew_25d = None
        spy_term_slope = None
        try:
            spot = spy_spots[-1] if spy_spots else 0.0
            if spot > 0:
                chain = truth_layer.option_chain("SPY", strike_range=0.20, spot=spot)
                if chain:
                    adapted = _adapt_chain(chain)
                    spy_skew_25d = IVPointService.compute_skew_25d_from_chain(
                        adapted, spot, now, target_dte=30.0)
                    spy_term_slope = IVPointService.compute_term_slope(adapted, spot, now)
        except Exception as e:
            print(f"[{JOB_NAME}] SPY chain skew/term failed: {e}")

        # 3. ETP + cross-asset closes (10 calendar days covers 5d returns).
        def _closes(sym: str) -> List[float]:
            try:
                bars = truth_layer.daily_bars(sym, now - timedelta(days=14), now)
                return [float(b["close"]) for b in (bars or [])
                        if b.get("close") is not None]
            except Exception as e:
                print(f"[{JOB_NAME}] bars fetch failed for {sym}: {e}")
                return []

        etp_closes = {s: _closes(s) for s in vol_signal.ETP_SYMBOLS}
        cross_closes = {s: _closes(s) for s in vol_signal.CROSS_ASSET_SYMBOLS}

        # 4. Regime context — read the latest persisted decision (comparison
        # only; no regime computation here, by import-boundary design).
        live_regime_state = None
        try:
            res = client.table("job_runs") \
                .select("result") \
                .eq("job_name", "suggestions_open") \
                .eq("status", "succeeded") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            rows = list(res.data or [])
            if rows:
                live_regime_state = ((rows[0].get("result") or {})
                                     .get("cycle_metadata") or {}).get("regime")
        except Exception as e:
            print(f"[{JOB_NAME}] regime context read failed: {e}")

        # 5. Assemble + write the observation row (fail-soft upsert).
        row = vol_signal.build_observation(
            snapshot_ts=now.isoformat(),
            as_of_date=as_of_date,
            iv_histories=iv_histories,
            spy_skew_25d=spy_skew_25d,
            spy_term_slope=spy_term_slope,
            etp_closes=etp_closes,
            cross_asset_closes=cross_closes,
            live_regime_state=live_regime_state,
            spy_spots=spy_spots,
        )
        written = vol_signal.observe_vol_signal(client, row)

        # 6. Backfill forward outcomes on prior rows (book P&L from
        # paper_eod_snapshots aggregated by snapshot_date).
        book_pl_by_date: Dict[str, float] = {}
        try:
            res = client.table("paper_eod_snapshots") \
                .select("snapshot_date, unrealized_pl") \
                .execute()
            for r in (res.data or []):
                d = str(r.get("snapshot_date"))
                pl = r.get("unrealized_pl")
                if pl is not None:
                    book_pl_by_date[d] = book_pl_by_date.get(d, 0.0) + float(pl)
        except Exception as e:
            print(f"[{JOB_NAME}] book snapshot read failed: {e}")

        backfilled = vol_signal.backfill_forward_outcomes(
            client,
            iv_dates=iv_dates,
            iv_by_date=iv_by_date,
            spot_by_date=spot_by_date,
            book_pl_by_date=book_pl_by_date,
        )

        missing = [k for k, v in (row.get("input_status") or {}).items()
                   if v == "missing"]
        result = {
            "status": "ok",
            "as_of_date": as_of_date,
            "row_written": written is not None,
            "history_window_days": row.get("history_window_days"),
            "missing_inputs": missing,
            "forwards_backfilled": backfilled,
        }
        print(f"[{JOB_NAME}] Finished. {result}")
        return result

    except Exception as e:
        print(f"[{JOB_NAME}] Job failed: {e}")
        traceback.print_exc()
        raise e
