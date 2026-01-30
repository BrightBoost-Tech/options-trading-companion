from fastapi import APIRouter, Depends, Header, HTTPException, Body
from typing import Optional, Dict
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client
from datetime import datetime, timedelta
import os

# Job Enqueue Dependencies
from packages.quantum.jobs.enqueue import enqueue_idempotent
from packages.quantum.jobs.http_models import EnqueueResponse

# Keep imports that might be needed for other endpoints not being converted
# (e.g. IV daily refresh which was NOT in the target list, and train-learning-v3)
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
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

@router.post("/morning-brief", status_code=202)
async def morning_brief(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:morning_brief"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "morning-brief"
    key = f"{job_name}-{today}"

    job_id = enqueue_idempotent(
        client=client,
        job_name=job_name,
        idempotency_key=key,
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "task_name": job_name
        }
    )

    return {
        "job_run_id": str(job_id),
        "job_name": job_name,
        "idempotency_key": key,
        "status": "queued"
    }

@router.post("/midday-scan", status_code=202)
async def midday_scan(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:midday_scan"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "midday-scan"
    key = f"{job_name}-{today}"

    job_id = enqueue_idempotent(
        client=client,
        job_name=job_name,
        idempotency_key=key,
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "task_name": job_name
        }
    )

    return {
        "job_run_id": str(job_id),
        "job_name": job_name,
        "idempotency_key": key,
        "status": "queued"
    }

@router.post("/weekly-report", status_code=202)
async def weekly_report_task(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:weekly_report"))
):
    # Weekly bucket
    week = datetime.now().strftime("%Y-W%V")
    job_name = "weekly-report"
    key = f"{job_name}-{week}"

    job_id = enqueue_idempotent(
        client=client,
        job_name=job_name,
        idempotency_key=key,
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "task_name": job_name
        }
    )

    return {
        "job_run_id": str(job_id),
        "job_name": job_name,
        "idempotency_key": key,
        "status": "queued"
    }

@router.post("/universe/sync", status_code=202)
async def universe_sync_task(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:universe_sync"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "universe-sync"
    key = f"{job_name}-{today}"

    job_id = enqueue_idempotent(
        client=client,
        job_name=job_name,
        idempotency_key=key,
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "task_name": job_name
        }
    )

    return {
        "job_run_id": str(job_id),
        "job_name": job_name,
        "idempotency_key": key,
        "status": "queued"
    }

@router.post("/plaid/backfill-history", status_code=202)
async def backfill_history(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:plaid_backfill"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "plaid-backfill-history"
    key = f"{job_name}-{start_date}-{end_date}-{today}"

    job_id = enqueue_idempotent(
        client=client,
        job_name=job_name,
        idempotency_key=key,
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "task_name": job_name,
            "start_date": start_date,
            "end_date": end_date
        }
    )

    return {
        "job_run_id": str(job_id),
        "job_name": job_name,
        "idempotency_key": key,
        "status": "queued"
    }

# Keep remaining endpoints unchanged as they were not in the target list
@router.post("/iv/daily-refresh")
async def iv_daily_refresh_task(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:iv_daily_refresh"))
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

    truth_layer = MarketDataTruthLayer()
    iv_repo = IVRepository(client)
    stats = {"ok": 0, "failed": 0, "errors": []}

    for sym in symbols:
        try:
            # 1. Normalize symbol
            norm_sym = truth_layer.normalize_symbol(sym)

            # 2. Get Spot Price via Snapshot (TruthLayer)
            # Use snapshot_many for consistency (handles single list too)
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

            # 3. Get Chain via TruthLayer
            chain = truth_layer.option_chain(norm_sym, strike_range=0.20)

            if not chain:
                stats["failed"] += 1
                continue

            # 4. Adapt Chain for IVPointService (Legacy Compatibility)
            # IVPointService expects: details.expiration_date, details.strike_price, details.contract_type, greeks.iv
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

    return {"status": "ok", "stats": stats}

@router.post("/train-learning-v3")
async def train_learning_v3(
    lookback_days: int = Body(90, embed=True),
    min_samples: int = Body(40, embed=True),
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:learning_train"))
):
    """
    Triggers Learned Nesting v3 training cycle.
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
