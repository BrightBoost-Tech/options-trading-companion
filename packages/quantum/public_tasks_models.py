"""
Pydantic Models for /tasks/* Endpoints (Security v4)

These models provide strict validation for task payloads, replacing loose Dict[str, Any].
Each task endpoint has a corresponding model that validates its expected payload.

Usage:
    @router.post("/tasks/suggestions/open")
    async def task_suggestions_open(
        payload: SuggestionsOpenPayload = Body(default_factory=SuggestionsOpenPayload),
        auth: TaskSignatureResult = Depends(verify_task_signature("tasks:suggestions_open"))
    ):
        ...
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict


# =============================================================================
# Base Models
# =============================================================================

class TaskPayloadBase(BaseModel):
    """Base model for all task payloads."""
    model_config = ConfigDict(extra="forbid")  # Reject unknown fields


# =============================================================================
# Simple Date-based Tasks (no payload needed)
# =============================================================================

class UniverseSyncPayload(TaskPayloadBase):
    """Payload for /tasks/universe/sync - typically empty."""
    pass


class MorningBriefPayload(TaskPayloadBase):
    """Payload for /tasks/morning-brief - typically empty."""
    pass


class MiddayScanPayload(TaskPayloadBase):
    """Payload for /tasks/midday-scan - typically empty."""
    pass


class WeeklyReportPayload(TaskPayloadBase):
    """Payload for /tasks/weekly-report - typically empty."""
    pass


# =============================================================================
# Validation Task
# =============================================================================

class ValidationEvalPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/eval.

    Triggers go-live validation evaluation (Paper/Historical).
    """
    mode: Literal["paper", "historical"] = Field(
        default="paper",
        description="Validation mode: 'paper' for paper trading, 'historical' for backtest"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only. If None, runs for all users."
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate user_id is a valid UUID format if provided."""
        if v is not None and v != "all":
            # Basic UUID format check (not full validation)
            if len(v) < 32:
                raise ValueError("user_id must be a valid UUID or 'all'")
        return v


# =============================================================================
# Suggestion Tasks
# =============================================================================

DEFAULT_STRATEGY_NAME = "spy_opt_autolearn_v6"


class SuggestionsClosePayload(TaskPayloadBase):
    """
    Payload for /tasks/suggestions/close.

    8:00 AM Chicago - Generate CLOSE/manage existing positions suggestions.
    """
    strategy_name: str = Field(
        default=DEFAULT_STRATEGY_NAME,
        min_length=1,
        max_length=100,
        description="Strategy config name to use"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only"
    )
    skip_sync: bool = Field(
        default=False,
        description="Skip holdings sync before generating suggestions"
    )


class SuggestionsOpenPayload(TaskPayloadBase):
    """
    Payload for /tasks/suggestions/open.

    11:00 AM Chicago - Generate OPEN/new positions suggestions.
    """
    strategy_name: str = Field(
        default=DEFAULT_STRATEGY_NAME,
        min_length=1,
        max_length=100,
        description="Strategy config name to use"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only"
    )
    skip_sync: bool = Field(
        default=False,
        description="Skip holdings sync before generating suggestions"
    )


# =============================================================================
# Learning Tasks
# =============================================================================

class LearningIngestPayload(TaskPayloadBase):
    """
    Payload for /tasks/learning/ingest.

    Daily outcome ingestion - Maps executed trades to suggestions for learning.
    """
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only"
    )
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="How far back to look for transactions"
    )


class StrategyAutotunePayload(TaskPayloadBase):
    """
    Payload for /tasks/strategy/autotune.

    Weekly strategy auto-tuning based on live outcomes.
    """
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only"
    )
    strategy_name: str = Field(
        default=DEFAULT_STRATEGY_NAME,
        min_length=1,
        max_length=100,
        description="Strategy to tune"
    )
    min_samples: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Minimum trades required to trigger update"
    )


# =============================================================================
# Ops Tasks
# =============================================================================

class OpsHealthCheckPayload(TaskPayloadBase):
    """
    Payload for /tasks/ops/health_check.

    Scheduled ops health check that:
    - Computes data freshness
    - Checks job status
    - Sends alerts for issues
    - Writes audit events
    """
    force: bool = Field(
        default=False,
        description="Force run even if recently completed"
    )


# =============================================================================
# Scope Constants
# =============================================================================

# Mapping of endpoint paths to their required scopes
TASK_SCOPES = {
    "/tasks/universe/sync": "tasks:universe_sync",
    "/tasks/morning-brief": "tasks:morning_brief",
    "/tasks/midday-scan": "tasks:midday_scan",
    "/tasks/weekly-report": "tasks:weekly_report",
    "/tasks/validation/eval": "tasks:validation_eval",
    "/tasks/suggestions/close": "tasks:suggestions_close",
    "/tasks/suggestions/open": "tasks:suggestions_open",
    "/tasks/learning/ingest": "tasks:learning_ingest",
    "/tasks/strategy/autotune": "tasks:strategy_autotune",
    "/tasks/ops/health_check": "tasks:ops_health_check",
}


def get_scope_for_path(path: str) -> str:
    """Get the required scope for a given task path."""
    scope = TASK_SCOPES.get(path)
    if not scope:
        raise ValueError(f"Unknown task path: {path}")
    return scope
