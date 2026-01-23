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

    v4-L1: Supports configurable checkpoint cadence for batch scheduling.
    """
    mode: Literal["paper", "historical"] = Field(
        default="paper",
        description="Validation mode: 'paper' for paper trading, 'historical' for backtest"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Run for specific user only. If None, runs for all users."
    )
    cadence: Literal["daily", "intraday"] = Field(
        default="daily",
        description="Checkpoint bucket cadence: 'daily' (default) or 'intraday' (hourly buckets)"
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
# Paper Autopilot Tasks (v4-L1C)
# =============================================================================

class PaperAutoExecutePayload(TaskPayloadBase):
    """
    Payload for /tasks/paper/auto-execute.

    Automatically executes top executable suggestions for paper trading.
    Part of Phase-3 streak automation.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires PAPER_AUTOPILOT_ENABLED=1
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


class PaperAutoClosePayload(TaskPayloadBase):
    """
    Payload for /tasks/paper/auto-close.

    Automatically closes paper positions before checkpoint.
    Part of Phase-3 streak automation.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires PAPER_AUTOPILOT_ENABLED=1
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


# =============================================================================
# Shadow Checkpoint Tasks (v4-L1D)
# =============================================================================

class ValidationShadowEvalPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/shadow-eval.

    Runs a shadow checkpoint evaluation that computes metrics WITHOUT
    mutating go-live streak state. Used for "what-if" analysis and
    intraday pacing visibility.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires SHADOW_CHECKPOINT_ENABLED=1
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )
    cadence: Literal["daily", "intraday"] = Field(
        default="intraday",
        description="Bucket cadence: 'intraday' (hourly) or 'daily'"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


class ValidationCohortEvalPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/cohort-eval.

    Runs multiple shadow evaluations with different threshold configurations
    (cohorts) to extract more learning per day. Returns a leaderboard of
    cohort results sorted by would_pass and margin_to_target.

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires SHADOW_CHECKPOINT_ENABLED=1
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )
    cadence: Literal["daily", "intraday"] = Field(
        default="intraday",
        description="Bucket cadence: 'intraday' (hourly) or 'daily'"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


class ValidationAutopromoteCohortPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/autopromote-cohort.

    v4-L1E: Evaluates whether to auto-promote a cohort's parameters to the
    official paper checkpoint configuration based on 3-day proof rule.

    Promotion criteria:
    - Same winner cohort for 3 consecutive trading-day buckets
    - No fail-fast on any of those days
    - Non-decreasing return_pct across the 3 days

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    - Requires AUTOPROMOTE_ENABLED=1
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


# =============================================================================
# 10-Day Readiness Hardening Tasks (v4-L1F)
# =============================================================================

class ValidationPreflightPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/preflight.

    v4-L1F: Computes and returns a layman-friendly preflight summary
    showing "on track vs at risk" status for the daily checkpoint.

    Outputs a markdown summary to GITHUB_STEP_SUMMARY showing:
    - outcomes_today_count, open_positions_count
    - return_pct, target_return_now, margin_to_target
    - max_drawdown_pct, fail_fast threshold
    - on_track boolean and reason
    - time until official checkpoint

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode
    - Respects pause gate
    - Idempotent (read-only, no state mutation)
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


class ValidationInitWindowPayload(TaskPayloadBase):
    """
    Payload for /tasks/validation/init-window.

    v4-L1F: Ensures forward checkpoint window fields are valid and
    initialized BEFORE Day 1 of the test. Prevents "repair window at
    checkpoint time" surprises.

    This task:
    - Validates/repairs paper_window_start and paper_window_end
    - Does NOT increment streak
    - Does NOT change readiness
    - Does NOT trigger fail-fast

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode
    - Respects pause gate
    - Idempotent once per day (UTC bucket)
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


class PaperSafetyCloseOnePayload(TaskPayloadBase):
    """
    Payload for /tasks/paper/safety-close-one.

    v4-L1F: Safety net to guarantee at least one paper close outcome
    exists before checkpoint time. Prevents "no outcomes = miss" resets.

    Behavior:
    - If there is at least one open paper position, closes exactly one
      (deterministically: oldest opened_at, then position_id asc)
    - If no open positions exist, no-ops without error
    - Idempotent once per day (UTC bucket)

    Requirements:
    - Requires specific user_id (not "all")
    - Must be in paper mode (ops_state.mode == "paper")
    - Respects pause gate
    """
    user_id: str = Field(
        ...,  # Required
        min_length=32,
        description="Target user UUID (required, cannot be 'all')"
    )

    @field_validator("user_id")
    @classmethod
    def validate_user_id_not_all(cls, v: str) -> str:
        """Validate user_id is a specific user, not 'all'."""
        if v == "all":
            raise ValueError("user_id must be a specific user UUID, not 'all'")
        if len(v) < 32:
            raise ValueError("user_id must be a valid UUID")
        return v


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
    "/tasks/validation/shadow-eval": "tasks:validation_shadow_eval",
    "/tasks/validation/cohort-eval": "tasks:validation_cohort_eval",
    "/tasks/validation/autopromote-cohort": "tasks:validation_autopromote_cohort",
    "/tasks/validation/preflight": "tasks:validation_preflight",
    "/tasks/validation/init-window": "tasks:validation_init_window",
    "/tasks/suggestions/close": "tasks:suggestions_close",
    "/tasks/suggestions/open": "tasks:suggestions_open",
    "/tasks/learning/ingest": "tasks:learning_ingest",
    "/tasks/strategy/autotune": "tasks:strategy_autotune",
    "/tasks/ops/health_check": "tasks:ops_health_check",
    "/tasks/paper/auto-execute": "tasks:paper_auto_execute",
    "/tasks/paper/auto-close": "tasks:paper_auto_close",
    "/tasks/paper/safety-close-one": "tasks:paper_safety_close_one",
}


def get_scope_for_path(path: str) -> str:
    """Get the required scope for a given task path."""
    scope = TASK_SCOPES.get(path)
    if not scope:
        raise ValueError(f"Unknown task path: {path}")
    return scope
