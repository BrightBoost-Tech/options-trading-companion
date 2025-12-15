from fastapi import APIRouter, Depends, Header, HTTPException, Body
from typing import Optional, Dict
from packages.quantum.security.task_auth import verify_internal_task_request
from packages.quantum.services.workflow_orchestrator import run_morning_cycle, run_midday_cycle, run_weekly_report
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.plaid_history_service import PlaidHistoryService
from packages.quantum.market_data import PolygonService
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
# Explicit import of PlaidService class to instantiate locally
from packages.quantum.plaid_service import client as plaid_api_client # importing the raw client object already init in plaid_service?
# The api.py imports `plaid_service` module. Let's see how api.py uses it.
# `from packages.quantum import plaid_service`
# `plaid_endpoints.register_plaid_endpoints(app, plaid_service, ...)`
# `plaid_service` module has module-level functions `create_link_token`, etc.
# So we can just import the module.
from packages.quantum import plaid_service

from datetime import datetime
import os

# Import shared dependencies from main API or re-instantiate securely
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client

# Analytics & Learning Dependencies
from packages.quantum.analytics.conviction_service import ConvictionService
from packages.quantum.services.analytics_service import AnalyticsService

# Attempt to import CalibrationService (provided by prompt 6)
try:
    from packages.quantum.analytics.calibration_service import CalibrationService
except ImportError:
    CalibrationService = None

router = APIRouter(
    prefix="/internal/tasks",
    tags=["internal-tasks"],
    include_in_schema=False, # Hidden from public OpenAPI docs
    dependencies=[Depends(verify_internal_task_request)]
)

# Admin Client Init
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key
supabase_admin: Client = create_client(url, key) if url and key else None

APP_VERSION = os.getenv("APP_VERSION", "v2-dev")

def get_admin_client():
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")
    return supabase_admin

def get_active_user_ids(client: Client) -> list[str]:
    """Helper to get list of active user IDs."""
    try:
        res = client.table("user_settings").select("user_id").execute()
        return [r["user_id"] for r in res.data or []]
    except Exception as e:
        print(f"Error fetching active users: {e}")
        return []

@router.post("/morning-brief")
async def morning_brief(
    client: Client = Depends(get_admin_client)
):
    active_users = get_active_user_ids(client)
    for uid in active_users:
        await run_morning_cycle(client, uid)
    return {"status": "ok", "processed": len(active_users)}

@router.post("/midday-scan")
async def midday_scan(
    client: Client = Depends(get_admin_client)
):
    active_users = get_active_user_ids(client)
    for uid in active_users:
        await run_midday_cycle(client, uid)
    return {"status": "ok", "processed": len(active_users)}

@router.post("/weekly-report")
async def weekly_report_task(
    client: Client = Depends(get_admin_client)
):
    active_users = get_active_user_ids(client)
    for uid in active_users:
        await run_weekly_report(client, uid)
    return {"status": "ok", "processed": len(active_users)}

@router.post("/universe/sync")
async def universe_sync_task(
    client: Client = Depends(get_admin_client)
):
    print("Universe sync task: starting")
    try:
        service = UniverseService(client)
        service.sync_universe()
        service.update_metrics()
        print("Universe sync task: complete")
        return {"status": "ok", "message": "Universe synced and metrics updated"}
    except Exception as e:
        print(f"Universe sync task failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")

@router.post("/plaid/backfill-history")
async def backfill_history(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
    client: Client = Depends(get_admin_client)
):
    user_ids = get_active_user_ids(client)
    # The plaid_service module exposes `client` which is the `plaid_api.PlaidApi` instance.
    service = PlaidHistoryService(plaid_service.client, client)
    counts = {}
    for uid in user_ids:
        counts[uid] = await service.backfill_snapshots(uid, start_date, end_date)
    return {"status": "ok", "counts": counts}

@router.post("/iv/daily-refresh")
async def iv_daily_refresh_task(
    client: Client = Depends(get_admin_client)
):
    """
    Refreshes IV points for universe.
    """
    print("[IV Task] Starting daily IV refresh...")
    try:
        universe_service = UniverseService(client)
        candidates = universe_service.get_scan_candidates(limit=200)
        symbols = list(set([c['symbol'] for c in candidates] + ['SPY', 'QQQ', 'IWM', 'DIA']))
        print(f"[IV Task] Found {len(symbols)} symbols to process.")
    except Exception as e:
        print(f"[IV Task] Error fetching universe: {e}")
        return {"status": "error", "message": "Failed to fetch universe"}

    poly_service = PolygonService()
    iv_repo = IVRepository(client)
    stats = {"ok": 0, "failed": 0, "errors": []}

    for sym in symbols:
        try:
            chain = poly_service.get_option_chain_snapshot(sym, strike_range=0.20)
            if not chain:
                stats["failed"] += 1
                continue

            quote = poly_service.get_recent_quote(sym)
            spot = (quote['bid'] + quote['ask']) / 2.0
            if spot <= 0:
                 hist = poly_service.get_historical_prices(sym, days=2)
                 if hist and hist.get('prices'): spot = hist['prices'][-1]

            if spot <= 0:
                stats["failed"] += 1
                continue

            result = IVPointService.compute_atm_iv_30d_from_chain(chain, spot, datetime.now())
            if result.get("iv_30d") is None:
                stats["failed"] += 1
            else:
                iv_repo.upsert_iv_point(sym, result, datetime.now())
                stats["ok"] += 1
        except Exception as e:
             stats["failed"] += 1
             stats["errors"].append(f"{sym}: {e}")

    return {"status": "ok", "stats": stats}

@router.post("/train-learning-v3")
async def train_learning_v3(
    lookback_days: int = Body(90, embed=True),
    min_samples: int = Body(40, embed=True),
    client: Client = Depends(get_admin_client)
):
    """
    Triggers Learned Nesting v3 training cycle:
    1. Calibrates probability models based on historical outcomes.
    2. Refreshes conviction multipliers.
    3. Emits audit events.
    """
    if not CalibrationService:
         raise HTTPException(status_code=500, detail="CalibrationService dependency missing (Prompt 6)")

    analytics = AnalyticsService(client)
    active_users = get_active_user_ids(client)

    total_buckets = 0
    total_conviction_rows = 0

    for uid in active_users:
        try:
            # Step 1: Start Event
            analytics.log_event(
                user_id=uid,
                event_name="learning_train_started",
                category="system",
                properties={
                    "model_version": APP_VERSION,
                    "lookback_days": lookback_days
                }
            )

            # Step 2: Calibration Training
            # Call CalibrationService.train_and_persist(user_id, lookback_days, min_samples)
            # Returns dict with stats (e.g., {'buckets_count': 12, 'error': 0.05})
            cal_stats = CalibrationService.train_and_persist(uid, lookback_days, min_samples)

            buckets = 0
            if isinstance(cal_stats, dict):
                buckets = cal_stats.get("buckets_count", 0)
            total_buckets += buckets

            # Step 3: Conviction Warmup
            conviction_svc = ConvictionService(supabase=client)
            multipliers = conviction_svc._get_performance_multipliers(uid)
            rows = len(multipliers)
            total_conviction_rows += rows

            # Step 4: Completion Event
            analytics.log_event(
                user_id=uid,
                event_name="learning_train_completed",
                category="system",
                properties={
                    "model_version": APP_VERSION,
                    "calibration_buckets": buckets,
                    "conviction_rows": rows,
                    "calibration_stats": cal_stats
                }
            )

        except Exception as e:
            error_msg = str(e)
            print(f"Training failed for user {uid}: {error_msg}")

            analytics.log_event(
                user_id=uid,
                event_name="learning_train_failed",
                category="system",
                properties={
                     "model_version": APP_VERSION,
                     "error": error_msg
                }
            )

            # Fail hard as per requirements: "If any step fails... return HTTP 500"
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "message": "Training cycle failed",
                    "user_id": uid,
                    "error": error_msg
                }
            )

    return {
        "status": "ok",
        "calibration_buckets": total_buckets,
        "conviction_rows": total_conviction_rows
    }
