"""
Ops Console Endpoints (/ops/*)

v4-L5 Ops Console MVP: Mobile Commander remote control for trading operations.

Security: These endpoints require admin access (JWT with admin role or ADMIN_USER_IDS).

Endpoints:
- GET /ops/dashboard_state - Single-request dashboard data for mobile
- GET /ops/health - Operational health status (spec-required shape)
- POST /ops/pause - Toggle pause state
- POST /ops/mode - Change operating mode (paper/micro_live/live)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel
from datetime import datetime, timezone
import os
import uuid
import logging

logger = logging.getLogger(__name__)

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


class HealthBlock(BaseModel):
    """
    PR B: Aggregated health status for mobile dashboard.
    Provides at-a-glance system health from all components.
    """
    status: str  # "healthy", "degraded", "unhealthy", "paused"
    issues: List[str]  # List of active issues/alerts
    checks: Dict[str, str]  # Component -> status mapping


class FreshnessMeta(BaseModel):
    """Phase 1.1.1: Metadata for expanded freshness universe."""
    universe_size: int
    total_stale_count: int
    stale_symbols: List[str]  # All stale symbols (capped to 10)


class DashboardStateResponse(BaseModel):
    control: OpsControlState
    freshness: List[FreshnessItem]
    freshness_meta: Optional[FreshnessMeta] = None  # Phase 1.1.1: Expanded universe metadata
    pipeline: Dict[str, PipelineJobState]
    health: HealthBlock  # PR B: Aggregated health status


class PauseRequest(BaseModel):
    paused: bool
    reason: Optional[str] = None


class ModeRequest(BaseModel):
    mode: str  # paper, micro_live, live


# ---------------------------------------------------------------------------
# OpsHealth Response Models (spec-required shape)
# ---------------------------------------------------------------------------

class DataFreshnessResponse(BaseModel):
    """Data freshness assessment."""
    is_stale: bool
    stale_reason: Optional[str] = None
    as_of: Optional[datetime] = None
    age_seconds: Optional[float] = None
    source: str  # "job_runs" | "trade_suggestions" | "none"


class ExpectedJobResponse(BaseModel):
    """Expected job status."""
    name: str
    cadence: str  # "daily" | "weekly"
    last_success_at: Optional[datetime] = None
    status: str  # "ok" | "late" | "never_run" | "error"


class JobsResponse(BaseModel):
    """Jobs status block."""
    expected: List[ExpectedJobResponse]
    recent_failures: List[Dict[str, Any]]


class IntegrityResponse(BaseModel):
    """Integrity incident tracking."""
    recent_incidents: int
    last_incident_at: Optional[datetime] = None


class SuggestionsStatsResponse(BaseModel):
    """Suggestion generation statistics."""
    last_cycle_date: Optional[str] = None
    count_last_cycle: int


class OpsHealthResponse(BaseModel):
    """
    Full operational health response.
    Spec-required shape for monitoring.
    """
    now: datetime
    paused: bool
    pause_reason: Optional[str] = None
    data_freshness: DataFreshnessResponse
    jobs: JobsResponse
    integrity: IntegrityResponse
    suggestions: SuggestionsStatsResponse


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


def _get_market_freshness(client: Client) -> Tuple[List[FreshnessItem], Optional[FreshnessMeta]]:
    """
    Get market data freshness using expanded universe.

    Phase 1.1.1: Uses build_freshness_universe() to check same symbols that
    ops_health_check uses for alerts, ensuring UI/alerts consistency.

    Args:
        client: Supabase client for building universe

    Returns:
        Tuple of (List[FreshnessItem], FreshnessMeta) for dashboard response
    """
    try:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.ops_health_service import build_freshness_universe

        # Check for API key
        api_key = os.getenv("POLYGON_API_KEY")
        if not api_key:
            return (
                [
                    FreshnessItem(
                        symbol="ALL",
                        freshness_ms=None,
                        status="ERROR",
                        score=None,
                        issues=["POLYGON_API_KEY not configured"]
                    ),
                ],
                FreshnessMeta(
                    universe_size=0,
                    total_stale_count=0,
                    stale_symbols=[]
                )
            )

        # Build expanded universe (SPY/QQQ + holdings + suggestions)
        universe = build_freshness_universe(client)
        logger.info(f"[FRESHNESS] Expanded universe: {len(universe)} symbols")

        layer = MarketDataTruthLayer(api_key=api_key)
        snapshots = layer.snapshot_many_v4(universe)

        results = []
        stale_symbols = []
        max_display = 10  # Cap for UI payload

        for sym in universe[:max_display]:
            snap = snapshots.get(sym)
            if not snap:
                results.append(FreshnessItem(
                    symbol=sym,
                    freshness_ms=None,
                    status="ERROR",
                    score=None,
                    issues=["No snapshot returned"]
                ))
                stale_symbols.append(sym)
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

            if status == "STALE":
                stale_symbols.append(sym)

            results.append(FreshnessItem(
                symbol=sym,
                freshness_ms=freshness_ms,
                status=status,
                score=score,
                issues=issues if issues else None
            ))

        # Check remaining symbols (beyond max_display) for staleness count
        for sym in universe[max_display:]:
            snap = snapshots.get(sym)
            if snap and (snap.quality.is_stale or (snap.quality.freshness_ms and snap.quality.freshness_ms > FRESHNESS_WARN_MS)):
                stale_symbols.append(sym)

        meta = FreshnessMeta(
            universe_size=len(universe),
            total_stale_count=len(stale_symbols),
            stale_symbols=stale_symbols[:max_display]  # Cap for payload
        )

        return results, meta

    except Exception as e:
        logger.error(f"[FRESHNESS] Market freshness check failed: {e}")
        return (
            [
                FreshnessItem(
                    symbol="ALL",
                    freshness_ms=None,
                    status="ERROR",
                    score=None,
                    issues=[f"Check failed: {str(e)[:50]}"]
                ),
            ],
            FreshnessMeta(
                universe_size=0,
                total_stale_count=0,
                stale_symbols=[]
            )
        )


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


def _compute_health(
    control: OpsControlState,
    freshness: List[FreshnessItem],
    pipeline: Dict[str, PipelineJobState]
) -> HealthBlock:
    """
    PR B: Compute aggregated system health from components.

    Status hierarchy:
    - "healthy": All systems nominal
    - "paused": Trading is paused (not necessarily unhealthy)
    - "degraded": Some warnings but operational
    - "unhealthy": Critical issues present

    Returns HealthBlock with status, issues list, and per-component checks.
    """
    issues = []
    checks = {}

    # Check 1: Pause state
    if control.paused:
        issues.append(f"Trading paused: {control.pause_reason or 'No reason provided'}")
        checks["trading"] = "paused"
    else:
        checks["trading"] = "active"

    # Check 2: Market data freshness
    stale_symbols = [f.symbol for f in freshness if f.status in ("STALE", "ERROR")]
    warn_symbols = [f.symbol for f in freshness if f.status == "WARN"]

    if stale_symbols:
        issues.append(f"Stale market data: {', '.join(stale_symbols)}")
        checks["market_data"] = "stale"
    elif warn_symbols:
        checks["market_data"] = "warn"
    else:
        checks["market_data"] = "ok"

    # Check 3: Pipeline jobs
    # Canonical failure statuses from DB enum: failed_retryable, dead_lettered
    # Note: "cancelled" is NOT a failure (used by pause gate for auditable records)
    # Note: "error" is a synthetic status meaning we couldn't fetch pipeline state
    failed_statuses = ("failed_retryable", "dead_lettered")
    failed_jobs = [name for name, state in pipeline.items() if state.status in failed_statuses]
    error_jobs = [name for name, state in pipeline.items() if state.status == "error"]
    running_jobs = [name for name, state in pipeline.items() if state.status == "running"]

    if error_jobs:
        issues.append(f"Pipeline fetch error: {', '.join(error_jobs)}")
        checks["pipeline"] = "error"
    elif failed_jobs:
        issues.append(f"Failed jobs: {', '.join(failed_jobs)}")
        checks["pipeline"] = "failed"
    elif running_jobs:
        checks["pipeline"] = "running"
    else:
        checks["pipeline"] = "ok"

    # Determine overall status
    has_critical = (
        checks.get("market_data") == "stale" or
        checks.get("pipeline") in ("failed", "error")
    )
    has_warning = checks.get("market_data") == "warn"
    is_paused = control.paused

    if has_critical:
        status = "unhealthy"
    elif is_paused:
        status = "paused"
    elif has_warning:
        status = "degraded"
    else:
        status = "healthy"

    return HealthBlock(status=status, issues=issues, checks=checks)


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
    - health: PR B - Aggregated system health status

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

    # 2. Get market freshness (Phase 1.1.1: expanded universe)
    freshness, freshness_meta = _get_market_freshness(client)

    # 3. Get pipeline status
    pipeline = _get_pipeline_status(client)

    # 4. PR B: Compute aggregated health
    health = _compute_health(control, freshness, pipeline)

    return DashboardStateResponse(
        control=control,
        freshness=freshness,
        freshness_meta=freshness_meta,  # Phase 1.1.1: expanded universe metadata
        pipeline=pipeline,
        health=health,
    )


@router.get("/health", response_model=OpsHealthResponse)
async def get_ops_health(
    request: Request,
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Operational health status for monitoring.

    Returns spec-required shape with:
    - now: Current timestamp
    - paused: Trading pause state
    - data_freshness: Data staleness assessment
    - jobs: Expected job status and recent failures
    - integrity: Audit log incident tracking
    - suggestions: Last cycle statistics

    Auth: Requires admin access.
    """
    from packages.quantum.services.ops_health_service import (
        compute_data_freshness,
        get_expected_jobs,
        get_recent_failures,
        get_suggestions_stats,
        get_integrity_stats,
    )

    # 1. Get ops control state
    control_row = _get_ops_control(client)

    # 2. Compute data freshness
    freshness = compute_data_freshness(client)

    # 3. Get expected jobs status
    expected_jobs = get_expected_jobs(client)

    # 4. Get recent failures
    recent_failures = get_recent_failures(client)

    # 5. Get integrity stats
    integrity = get_integrity_stats(client)

    # 6. Get suggestions stats
    suggestions = get_suggestions_stats(client)

    return OpsHealthResponse(
        now=datetime.now(timezone.utc),
        paused=control_row.get("paused", True),
        pause_reason=control_row.get("pause_reason"),
        data_freshness=DataFreshnessResponse(
            is_stale=freshness.is_stale,
            stale_reason=freshness.reason,
            as_of=freshness.as_of,
            age_seconds=freshness.age_seconds,
            source=freshness.source
        ),
        jobs=JobsResponse(
            expected=[
                ExpectedJobResponse(
                    name=j.name,
                    cadence=j.cadence,
                    last_success_at=j.last_success_at,
                    status=j.status
                )
                for j in expected_jobs
            ],
            recent_failures=recent_failures
        ),
        integrity=IntegrityResponse(
            recent_incidents=integrity.get("recent_incidents", 0),
            last_incident_at=integrity.get("last_incident_at")
        ),
        suggestions=SuggestionsStatsResponse(
            last_cycle_date=suggestions.get("last_cycle_date"),
            count_last_cycle=suggestions.get("count_last_cycle", 0)
        )
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

    # Audit log the mutation (stdout)
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

    # Write immutable audit event to decision_audit_events
    try:
        from packages.quantum.observability.audit_log_service import AuditLogService
        audit_service = AuditLogService(client)
        trace_id = str(uuid.uuid4())
        event_name = "ops.pause.toggled" if body.paused else "ops.pause.resumed"

        audit_service.log_audit_event(
            user_id=admin.user_id,
            trace_id=trace_id,
            event_name=event_name,
            payload={
                "paused": body.paused,
                "reason": body.reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            suggestion_id=None,
            strategy=None,
            regime=None
        )
        logger.info(f"[OPS] Audit event written for pause toggle: {event_name}")
    except Exception as e:
        # Log but don't fail the request
        logger.warning(f"Failed to write pause audit event: {e}")

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

    # Capture previous mode before update
    previous_state = _get_ops_control(client)
    previous_mode = previous_state.get("mode", "paper")

    update_data = {
        "mode": body.mode,
        "updated_by": admin.user_id,
    }

    res = client.table("ops_control") \
        .update(update_data) \
        .eq("key", "global") \
        .execute()

    # Audit log the mutation (stdout)
    log_admin_mutation(
        request=request,
        user_id=admin.user_id,
        action="set_mode",
        resource_type="ops_control",
        resource_id="global",
        details={
            "mode": body.mode,
            "previous_mode": previous_mode,
        }
    )

    # Write immutable audit event to decision_audit_events
    try:
        from packages.quantum.observability.audit_log_service import AuditLogService
        audit_service = AuditLogService(client)
        trace_id = str(uuid.uuid4())

        audit_service.log_audit_event(
            user_id=admin.user_id,
            trace_id=trace_id,
            event_name="ops.mode.changed",
            payload={
                "mode": body.mode,
                "previous_mode": previous_mode,
                "actor": admin.user_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            suggestion_id=None,
            strategy=None,
            regime=None
        )
        logger.info(f"[OPS] Audit event written for mode change: {previous_mode} -> {body.mode}")
    except Exception as e:
        # Log but don't fail the request
        logger.warning(f"Failed to write mode audit event: {e}")

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
