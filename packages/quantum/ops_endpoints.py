"""
Ops Console Endpoints (/ops/*)

v4-L5 Ops Console MVP: Mobile Commander remote control for trading operations.

Security: These endpoints require admin access (JWT with admin role or ADMIN_USER_IDS).

Endpoints:
- GET /ops/dashboard_state - Single-request dashboard data for mobile
- POST /ops/pause - Toggle pause state
- POST /ops/mode - Change operating mode (paper/micro_live/live)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime
import os

from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.security.admin_auth import (
    verify_admin_access,
    AdminAuthResult,
    log_admin_mutation,
)
from supabase import create_client, Client

router = APIRouter(
    prefix="/ops",
    tags=["ops"],
)

# ---------------------------------------------------------------------------
# Admin Client Init (same pattern as jobs/endpoints.py)
# ---------------------------------------------------------------------------

secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
_url = supa_secrets.url
_key = supa_secrets.service_role_key
supabase_admin: Client = create_client(_url, _key) if _url and _key else None


def get_admin_client() -> Client:
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")
    return supabase_admin


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class OpsControlState(BaseModel):
    mode: str
    paused: bool
    pause_reason: Optional[str] = None
    updated_at: datetime


class FreshnessItem(BaseModel):
    symbol: str
    freshness_ms: Optional[float] = None
    status: str  # OK, WARN, STALE, ERROR
    score: Optional[int] = None
    issues: Optional[List[str]] = None


class PipelineJobState(BaseModel):
    status: str
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class DashboardStateResponse(BaseModel):
    control: OpsControlState
    freshness: List[FreshnessItem]
    pipeline: Dict[str, PipelineJobState]


class PauseRequest(BaseModel):
    paused: bool
    reason: Optional[str] = None


class ModeRequest(BaseModel):
    mode: str  # paper, micro_live, live


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical job names for pipeline status
CANONICAL_JOB_NAMES = [
    "suggestions_close",
    "suggestions_open",
    "learning_ingest",
    "strategy_autotune",
]

# Market data freshness thresholds (ms)
FRESHNESS_OK_MS = 60_000       # < 60s = OK
FRESHNESS_WARN_MS = 120_000    # 60-120s = WARN
# > 120s = STALE


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _get_ops_control(client: Client) -> Dict[str, Any]:
    """Fetch global ops_control row."""
    res = client.table("ops_control").select("*").eq("key", "global").maybe_single().execute()
    if res.data:
        return res.data
    # If no row exists (shouldn't happen after migration), return safe defaults
    return {
        "key": "global",
        "mode": "paper",
        "paused": True,
        "pause_reason": "No control row found",
        "updated_at": datetime.now().isoformat(),
    }


def _get_market_freshness() -> List[FreshnessItem]:
    """
    Get market data freshness for key symbols.
    Uses MarketDataTruthLayer snapshot_many_v4.
    """
    try:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        # Check for API key
        api_key = os.getenv("POLYGON_API_KEY")
        if not api_key:
            return [
                FreshnessItem(
                    symbol="SPY",
                    freshness_ms=None,
                    status="ERROR",
                    score=None,
                    issues=["POLYGON_API_KEY not configured"]
                ),
                FreshnessItem(
                    symbol="QQQ",
                    freshness_ms=None,
                    status="ERROR",
                    score=None,
                    issues=["POLYGON_API_KEY not configured"]
                ),
            ]

        layer = MarketDataTruthLayer(api_key=api_key)
        symbols = ["SPY", "QQQ"]

        snapshots = layer.snapshot_many_v4(symbols)

        results = []
        for sym in symbols:
            snap = snapshots.get(sym)
            if not snap:
                results.append(FreshnessItem(
                    symbol=sym,
                    freshness_ms=None,
                    status="ERROR",
                    score=None,
                    issues=["No snapshot returned"]
                ))
                continue

            freshness_ms = snap.quality.freshness_ms
            score = snap.quality.quality_score
            issues = snap.quality.issues

            # Determine status badge
            if freshness_ms is None:
                status = "STALE"
            elif freshness_ms <= FRESHNESS_OK_MS:
                status = "OK"
            elif freshness_ms <= FRESHNESS_WARN_MS:
                status = "WARN"
            else:
                status = "STALE"

            # Override status if quality issues indicate fatal
            if snap.quality.is_stale:
                status = "STALE"

            results.append(FreshnessItem(
                symbol=sym,
                freshness_ms=freshness_ms,
                status=status,
                score=score,
                issues=issues if issues else None
            ))

        return results

    except Exception as e:
        return [
            FreshnessItem(
                symbol="SPY",
                freshness_ms=None,
                status="ERROR",
                score=None,
                issues=[str(e)]
            ),
            FreshnessItem(
                symbol="QQQ",
                freshness_ms=None,
                status="ERROR",
                score=None,
                issues=[str(e)]
            ),
        ]


def _get_pipeline_status(client: Client) -> Dict[str, PipelineJobState]:
    """
    Get most recent job run status for each canonical job.
    Fetches recent rows and reduces in Python (Supabase may not support DISTINCT ON).
    """
    pipeline = {}

    for job_name in CANONICAL_JOB_NAMES:
        try:
            # Fetch most recent job for this job_name
            res = client.table("job_runs") \
                .select("status, created_at, finished_at") \
                .eq("job_name", job_name) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            if res.data and len(res.data) > 0:
                row = res.data[0]
                pipeline[job_name] = PipelineJobState(
                    status=row.get("status", "unknown"),
                    created_at=row.get("created_at"),
                    finished_at=row.get("finished_at"),
                )
            else:
                pipeline[job_name] = PipelineJobState(
                    status="never_run",
                    created_at=None,
                    finished_at=None,
                )
        except Exception:
            pipeline[job_name] = PipelineJobState(
                status="error",
                created_at=None,
                finished_at=None,
            )

    return pipeline


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard_state", response_model=DashboardStateResponse)
async def get_dashboard_state(
    request: Request,
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Single-request dashboard state for mobile commander.

    Returns:
    - control: Current ops control state (mode, paused, etc.)
    - freshness: Market data freshness for key symbols
    - pipeline: Status of canonical job runs

    Auth: Requires admin access.
    """
    # 1. Get ops control state
    control_row = _get_ops_control(client)
    control = OpsControlState(
        mode=control_row.get("mode", "paper"),
        paused=control_row.get("paused", True),
        pause_reason=control_row.get("pause_reason"),
        updated_at=control_row.get("updated_at", datetime.now()),
    )

    # 2. Get market freshness
    freshness = _get_market_freshness()

    # 3. Get pipeline status
    pipeline = _get_pipeline_status(client)

    return DashboardStateResponse(
        control=control,
        freshness=freshness,
        pipeline=pipeline,
    )


@router.post("/pause", response_model=OpsControlState)
async def set_pause_state(
    request: Request,
    body: PauseRequest = Body(...),
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Toggle pause state for trading operations.

    When paused=true, new job enqueues will be blocked at the gate.

    Auth: Requires admin access.
    """
    update_data = {
        "paused": body.paused,
        "pause_reason": body.reason if body.paused else None,
        "updated_by": admin.user_id,
    }

    res = client.table("ops_control") \
        .update(update_data) \
        .eq("key", "global") \
        .execute()

    # Audit log the mutation
    log_admin_mutation(
        request=request,
        user_id=admin.user_id,
        action="set_pause",
        resource_type="ops_control",
        resource_id="global",
        details={
            "paused": body.paused,
            "reason": body.reason,
        }
    )

    # Fetch updated row
    updated = _get_ops_control(client)
    return OpsControlState(
        mode=updated.get("mode", "paper"),
        paused=updated.get("paused", True),
        pause_reason=updated.get("pause_reason"),
        updated_at=updated.get("updated_at", datetime.now()),
    )


@router.post("/mode", response_model=OpsControlState)
async def set_mode(
    request: Request,
    body: ModeRequest = Body(...),
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Change operating mode (paper/micro_live/live).

    Auth: Requires admin access.
    """
    valid_modes = ["paper", "micro_live", "live"]
    if body.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.mode}'. Must be one of: {valid_modes}"
        )

    update_data = {
        "mode": body.mode,
        "updated_by": admin.user_id,
    }

    res = client.table("ops_control") \
        .update(update_data) \
        .eq("key", "global") \
        .execute()

    # Audit log the mutation
    log_admin_mutation(
        request=request,
        user_id=admin.user_id,
        action="set_mode",
        resource_type="ops_control",
        resource_id="global",
        details={
            "mode": body.mode,
        }
    )

    # Fetch updated row
    updated = _get_ops_control(client)
    return OpsControlState(
        mode=updated.get("mode", "paper"),
        paused=updated.get("paused", True),
        pause_reason=updated.get("pause_reason"),
        updated_at=updated.get("updated_at", datetime.now()),
    )


# ---------------------------------------------------------------------------
# Ops Control Query Helper (for use by other modules)
# ---------------------------------------------------------------------------

def get_global_ops_control() -> Dict[str, Any]:
    """
    Fetch the global ops control state.
    Used by enqueue gate to check pause state.

    Returns dict with keys: mode, paused, pause_reason, updated_at
    Returns safe defaults if DB unavailable.
    """
    try:
        client = get_admin_client()
        return _get_ops_control(client)
    except Exception:
        # Safe defaults if DB unavailable
        return {
            "key": "global",
            "mode": "paper",
            "paused": True,  # Fail safe
            "pause_reason": "Unable to fetch ops control",
            "updated_at": datetime.now().isoformat(),
        }


def is_trading_paused() -> tuple[bool, Optional[str]]:
    """
    Check if trading is currently paused.

    Returns: (is_paused, reason)
    """
    control = get_global_ops_control()
    return control.get("paused", True), control.get("pause_reason")
