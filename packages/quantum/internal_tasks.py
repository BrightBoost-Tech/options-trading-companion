from fastapi import APIRouter, Depends, Header, HTTPException, Body
from typing import Optional, Dict
from packages.quantum.security.task_signing_v4 import verify_task_signature, TaskSignatureResult
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client
from datetime import datetime, timedelta
import os

# Job Enqueue Dependencies
from packages.quantum.jobs.enqueue import enqueue_idempotent  # DB-only (legacy)
from packages.quantum.jobs.http_models import EnqueueResponse
from packages.quantum.public_tasks import enqueue_job_run  # DB + RQ (correct path)

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

@router.post("/alpaca/order-sync", status_code=202)
async def alpaca_order_sync_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:alpaca_order_sync"))
):
    now = datetime.now()
    return enqueue_job_run(
        job_name="alpaca_order_sync",
        idempotency_key=f"alpaca_order_sync-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/risk/intraday-monitor", status_code=202)
async def intraday_risk_monitor_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:intraday_risk_monitor"))
):
    now = datetime.now()
    # 15-min block key: e.g. intraday_risk_monitor-2026-04-09-10-30
    minute_block = (now.minute // 15) * 15
    return enqueue_job_run(
        job_name="intraday_risk_monitor",
        idempotency_key=f"intraday_risk_monitor-{now.strftime('%Y-%m-%d-%H')}-{minute_block:02d}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/learning/post-trade", status_code=202)
async def post_trade_learning_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:post_trade_learning")),
    trade_ids: list = Body(None, embed=True),
):
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "app_version": APP_VERSION,
        "trigger_ts": datetime.now().isoformat(),
    }
    if trade_ids:
        payload["trade_ids"] = trade_ids
    user_id = os.environ.get("USER_ID") or os.environ.get("TASK_USER_ID")
    if user_id:
        payload["user_id"] = user_id
    return enqueue_job_run(
        job_name="post_trade_learning",
        idempotency_key=f"post_trade_learning-{today}",
        payload=payload,
    )


@router.post("/orchestrator/start-day", status_code=202)
async def day_orchestrator_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:day_orchestrator"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="day_orchestrator",
        idempotency_key=f"day_orchestrator-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
        },
    )


@router.post("/progression/daily-eval", status_code=202)
async def daily_progression_eval_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:daily_progression_eval"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="daily_progression_eval",
        idempotency_key=f"daily_progression_eval-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
        },
    )


@router.post("/calibration/update", status_code=202)
async def calibration_update_task(
    window_days: int = Body(30, embed=True),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:calibration_update"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="calibration_update",
        idempotency_key=f"calibration_update-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "window_days": window_days,
        },
    )


@router.post("/promotion/check", status_code=202)
async def promotion_check_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:promotion_check"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="promotion_check",
        idempotency_key=f"promotion_check-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
        },
    )


@router.post("/heartbeat", status_code=202)
async def heartbeat_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:heartbeat"))
):
    """Scheduler liveness heartbeat — proves the scheduler is firing jobs."""
    now = datetime.now()
    return enqueue_job_run(
        job_name="scheduler_heartbeat",
        idempotency_key=f"heartbeat-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/phase2-precheck", status_code=202)
async def phase2_precheck_task(
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:phase2_precheck"))
):
    """PR #6 Phase 2 observation-window verification.

    Runs every 6 hours for 48h post-deploy. Self-expires when
    PR6_DEPLOY_TIMESTAMP + 48h is past. See
    docs/pr6_close_path_consolidation.md §5 for the 4 verification
    queries this exercises."""
    now = datetime.now()
    return enqueue_job_run(
        job_name="phase2_precheck",
        idempotency_key=f"phase2-precheck-{now.strftime('%Y-%m-%d-%H%M')}",
        payload={
            "trigger_ts": now.isoformat(),
        },
    )


@router.post("/autotune/walk-forward", status_code=202)
async def walk_forward_autotune_task(
    lookback_days: int = Body(60, embed=True),
    cohort_name: str = Body(None, embed=True),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:walk_forward_autotune"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="walk_forward_autotune",
        idempotency_key=f"walk_forward_autotune-{today}",
        payload={
            "app_version": APP_VERSION,
            "trigger_ts": datetime.now().isoformat(),
            "lookback_days": lookback_days,
            "cohort_name": cohort_name,
        },
    )


# Keep remaining endpoints unchanged as they were not in the target list
@router.post("/iv/daily-refresh", status_code=202)
async def iv_daily_refresh_task(
    client: Client = Depends(get_admin_client),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:iv_daily_refresh"))
):
    """
    Refreshes IV points for universe.
    Now enqueued as a background job to prevent blocking the API.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    job_name = "iv-daily-refresh"
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
