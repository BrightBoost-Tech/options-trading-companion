#!/usr/bin/env python3
"""
Run Signed Task - Security v4 HMAC Request Signing

Calls /tasks/* endpoints with X-Task-* headers using v4 HMAC signing.
Used by GitHub Actions workflows and local development.

Usage:
    python scripts/run_signed_task.py suggestions_close
    python scripts/run_signed_task.py suggestions_open --user-id <uuid>
    python scripts/run_signed_task.py suggestions_open --payload-json '{"skip_sync":true}'
    python scripts/run_signed_task.py suggestions_open --force-rerun
    DRY_RUN=1 python scripts/run_signed_task.py learning_ingest

Environment Variables:
    TASK_SIGNING_SECRET  - Single signing secret (simple setup)
    TASK_SIGNING_KEYS    - Multiple keys for rotation (kid1:secret1,kid2:secret2)
    BASE_URL             - API base URL (e.g., https://api.example.com)
    DRY_RUN              - Set to "1" to print request without sending
    USER_ID              - Optional: run for specific user only

Supported Tasks:
    suggestions_close              - POST /tasks/suggestions/close (8 AM Chicago)
    suggestions_open               - POST /tasks/suggestions/open (11 AM Chicago)
    learning_ingest                - POST /tasks/learning/ingest (4:10 PM Chicago)
    universe_sync                  - POST /tasks/universe/sync
    morning_brief                  - POST /tasks/morning-brief
    midday_scan                    - POST /tasks/midday-scan
    weekly_report                  - POST /tasks/weekly-report
    validation_eval                - POST /tasks/validation/eval
    strategy_autotune              - POST /tasks/strategy/autotune
    ops_health_check               - POST /tasks/ops/health_check (every 30 min)
    paper_auto_execute             - POST /tasks/paper/auto-execute (requires user_id)
    paper_auto_close               - POST /tasks/paper/auto-close (requires user_id)
    paper_process_orders           - POST /tasks/paper/process-orders (requires user_id)
    validation_shadow_eval         - POST /tasks/validation/shadow-eval (requires user_id)
    validation_cohort_eval         - POST /tasks/validation/cohort-eval (requires user_id)
    validation_autopromote_cohort  - POST /tasks/validation/autopromote-cohort (requires user_id)
    validation_preflight           - POST /tasks/validation/preflight (requires user_id)
    validation_init_window         - POST /tasks/validation/init-window (requires user_id)
    paper_safety_close_one         - POST /tasks/paper/safety-close-one (requires user_id)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

# Add packages to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from packages.quantum.security.task_signing_v4 import sign_task_request


# =============================================================================
# Verbose Response Tasks (Paper Pipeline Debugging)
# =============================================================================

# Tasks that always print full response JSON for debugging paper pipeline.
# These run synchronously without job_runs rows, so response details are
# critical for debugging stuck staged orders.
VERBOSE_RESPONSE_TASKS = {
    "paper_process_orders",
    "paper_auto_execute",
    "paper_auto_close",
    "paper_safety_close_one",
}

# Fields that should be redacted if present in response (safety measure)
REDACT_FIELDS = {"secret", "password", "token", "api_key", "apikey", "credential"}


def _should_print_response_json(task_name: str) -> bool:
    """
    Check if response JSON should be printed for this task.

    Returns True if:
    - PRINT_RESPONSE_JSON=1 env var is set, OR
    - task_name is in VERBOSE_RESPONSE_TASKS set
    """
    if os.environ.get("PRINT_RESPONSE_JSON", "").lower() in ("1", "true", "yes"):
        return True
    return task_name in VERBOSE_RESPONSE_TASKS


def _redact_sensitive_fields(data: dict) -> dict:
    """
    Recursively redact any sensitive fields from response data.

    This is a safety measure - response shouldn't contain secrets,
    but we redact just in case.
    """
    if not isinstance(data, dict):
        return data

    redacted = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(redact_word in key_lower for redact_word in REDACT_FIELDS):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_sensitive_fields(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_sensitive_fields(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


# =============================================================================
# Task Definitions
# =============================================================================

# User ID mode for each task:
#   "require" - task MUST have user_id, fail early if missing
#   "allow"   - task accepts user_id optionally, inject if provided
#   "none"    - task does NOT accept user_id, never inject it
#
# This prevents 422 errors when tasks with empty payload schemas
# (like universe_sync) receive unexpected user_id field.

TASKS = {
    "suggestions_close": {
        "path": "/tasks/suggestions/close",
        "scope": "tasks:suggestions_close",
        "description": "Generate CLOSE suggestions (8 AM Chicago)",
        "user_id_mode": "allow",
    },
    "suggestions_open": {
        "path": "/tasks/suggestions/open",
        "scope": "tasks:suggestions_open",
        "description": "Generate OPEN suggestions (11 AM Chicago)",
        "user_id_mode": "allow",
    },
    "learning_ingest": {
        "path": "/tasks/learning/ingest",
        "scope": "tasks:learning_ingest",
        "description": "Ingest learning outcomes (4:10 PM Chicago)",
        "user_id_mode": "allow",
    },
    "universe_sync": {
        "path": "/tasks/universe/sync",
        "scope": "tasks:universe_sync",
        "description": "Sync trading universe",
        "user_id_mode": "none",
    },
    "morning_brief": {
        "path": "/tasks/morning-brief",
        "scope": "tasks:morning_brief",
        "description": "Generate morning brief",
        "user_id_mode": "none",
    },
    "midday_scan": {
        "path": "/tasks/midday-scan",
        "scope": "tasks:midday_scan",
        "description": "Run midday market scan",
        "user_id_mode": "none",
    },
    "weekly_report": {
        "path": "/tasks/weekly-report",
        "scope": "tasks:weekly_report",
        "description": "Generate weekly report",
        "user_id_mode": "none",
    },
    "validation_eval": {
        "path": "/tasks/validation/eval",
        "scope": "tasks:validation_eval",
        "description": "Run validation evaluation",
        "user_id_mode": "allow",
    },
    "strategy_autotune": {
        "path": "/tasks/strategy/autotune",
        "scope": "tasks:strategy_autotune",
        "description": "Auto-tune strategy parameters",
        "user_id_mode": "none",
    },
    "ops_health_check": {
        "path": "/tasks/ops/health_check",
        "scope": "tasks:ops_health_check",
        "description": "Run ops health check (every 30 min)",
        "user_id_mode": "none",
    },
    "paper_auto_execute": {
        "path": "/tasks/paper/auto-execute",
        "scope": "tasks:paper_auto_execute",
        "description": "Auto-execute top paper suggestions (requires user_id)",
        "user_id_mode": "require",
    },
    "paper_auto_close": {
        "path": "/tasks/paper/auto-close",
        "scope": "tasks:paper_auto_close",
        "description": "Auto-close paper positions (requires user_id)",
        "user_id_mode": "require",
    },
    "paper_process_orders": {
        "path": "/tasks/paper/process-orders",
        "scope": "tasks:paper_process_orders",
        "description": "Process staged paper orders (requires user_id)",
        "user_id_mode": "require",
    },
    "validation_shadow_eval": {
        "path": "/tasks/validation/shadow-eval",
        "scope": "tasks:validation_shadow_eval",
        "description": "Run shadow checkpoint evaluation (requires user_id)",
        "user_id_mode": "require",
    },
    "validation_cohort_eval": {
        "path": "/tasks/validation/cohort-eval",
        "scope": "tasks:validation_cohort_eval",
        "description": "Run cohort evaluations (requires user_id)",
        "user_id_mode": "require",
    },
    "validation_autopromote_cohort": {
        "path": "/tasks/validation/autopromote-cohort",
        "scope": "tasks:validation_autopromote_cohort",
        "description": "Auto-promote best cohort policy (requires user_id)",
        "user_id_mode": "require",
    },
    "validation_preflight": {
        "path": "/tasks/validation/preflight",
        "scope": "tasks:validation_preflight",
        "description": "Preflight readiness report (requires user_id)",
        "user_id_mode": "require",
    },
    "validation_init_window": {
        "path": "/tasks/validation/init-window",
        "scope": "tasks:validation_init_window",
        "description": "Initialize forward checkpoint window (requires user_id)",
        "user_id_mode": "require",
    },
    "paper_safety_close_one": {
        "path": "/tasks/paper/safety-close-one",
        "scope": "tasks:paper_safety_close_one",
        "description": "Safety close one paper position (requires user_id)",
        "user_id_mode": "require",
    },
    "plaid_backfill": {
        "path": "/internal/tasks/plaid/backfill-history",
        "scope": "tasks:plaid_backfill",
        "description": "Backfill Plaid history",
        "user_id_mode": "allow",
    },
    "iv_daily_refresh": {
        "path": "/internal/tasks/iv/daily-refresh",
        "scope": "tasks:iv_daily_refresh",
        "description": "Refresh IV points",
        "user_id_mode": "none",
    },
    "learning_train": {
        "path": "/internal/tasks/train-learning-v3",
        "scope": "tasks:learning_train",
        "description": "Train learned nesting v3",
        "user_id_mode": "none",
    },
}


# =============================================================================
# Time Gate Logic (DST-aware)
# =============================================================================

CHICAGO_TZ = ZoneInfo("America/Chicago")


def is_market_day() -> bool:
    """Check if today is a market day (Mon-Fri, excluding holidays)."""
    now_chicago = datetime.now(CHICAGO_TZ)
    # Monday=0, Sunday=6
    if now_chicago.weekday() >= 5:
        return False
    # TODO: Add holiday calendar check if needed
    return True


def is_within_time_window(
    target_hour: int,
    target_minute: int = 0,
    window_minutes: int = 30
) -> bool:
    """
    Check if current Chicago time is within window of target time.

    Args:
        target_hour: Target hour in Chicago time (0-23)
        target_minute: Target minute (0-59)
        window_minutes: How many minutes after target to allow

    Returns:
        True if within window, False otherwise
    """
    now_chicago = datetime.now(CHICAGO_TZ)
    target_minutes_from_midnight = target_hour * 60 + target_minute
    current_minutes_from_midnight = now_chicago.hour * 60 + now_chicago.minute

    diff = current_minutes_from_midnight - target_minutes_from_midnight
    return 0 <= diff < window_minutes


def check_time_gate(task_name: str, skip_time_gate: bool = False) -> bool:
    """
    Check if task should run based on time gate.

    Args:
        task_name: Name of the task to run
        skip_time_gate: If True, skip time gate check

    Returns:
        True if task should run, False if time-gated out
    """
    if skip_time_gate:
        return True

    # Define time windows for scheduled tasks
    TIME_GATES = {
        "suggestions_close": (8, 0),   # 8:00 AM Chicago
        "suggestions_open": (11, 0),   # 11:00 AM Chicago
        "learning_ingest": (16, 10),   # 4:10 PM Chicago
    }

    if task_name not in TIME_GATES:
        # No time gate for this task
        return True

    if not is_market_day():
        print(f"[TIME-GATE] Skipping {task_name}: not a market day")
        return False

    target_hour, target_minute = TIME_GATES[task_name]
    if not is_within_time_window(target_hour, target_minute, window_minutes=30):
        now_chicago = datetime.now(CHICAGO_TZ)
        print(
            f"[TIME-GATE] Skipping {task_name}: current time {now_chicago.strftime('%H:%M')} "
            f"not within 30 min of {target_hour:02d}:{target_minute:02d} Chicago"
        )
        return False

    return True


# =============================================================================
# GitHub Step Summary
# =============================================================================

MAX_SNIPPET_LENGTH = 300

# Semantic error statuses that indicate task failure despite HTTP 200
SEMANTIC_ERROR_STATUSES = {"error", "cancelled"}


def extract_error_snippet(data: dict) -> Optional[str]:
    """
    Extract error details from response JSON.

    Checks common error fields in priority order.

    Args:
        data: Parsed JSON response

    Returns:
        Error snippet string or None if no error details found
    """
    # Priority order for error extraction
    for key in ("detail", "error", "reason", "cancelled_detail", "cancelled_reason", "message"):
        value = data.get(key)
        if value and isinstance(value, str):
            return value

    # Fallback: if we have status but no detail, summarize available keys
    if data.get("status") in SEMANTIC_ERROR_STATUSES:
        # Extract a few safe keys for context
        safe_keys = ["status", "reason", "cancelled_reason", "task", "user_id"]
        summary_parts = []
        for k in safe_keys:
            if k in data and data[k]:
                summary_parts.append(f"{k}={data[k]}")
        if summary_parts:
            return "; ".join(summary_parts)

    return None


def sanitize_snippet(s: str) -> str:
    """
    Truncate and escape snippet for safe display in markdown tables and logs.

    Args:
        s: Raw snippet string

    Returns:
        Sanitized string safe for markdown tables
    """
    if not s:
        return ""

    # Truncate first
    truncated = s[:MAX_SNIPPET_LENGTH]
    if len(s) > MAX_SNIPPET_LENGTH:
        truncated += "..."

    # Escape characters that break markdown tables
    sanitized = truncated.replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    # Remove any control characters
    sanitized = "".join(c if c.isprintable() or c == " " else " " for c in sanitized)

    return sanitized


def write_step_summary(
    task_name: str,
    status_code: Optional[int] = None,
    job_run_id: Optional[str] = None,
    result_status: Optional[str] = None,
    error_snippet: Optional[str] = None,
    skipped: bool = False,
    skip_reason: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    Write a concise summary to GITHUB_STEP_SUMMARY if available.

    This provides instant visibility in GitHub Actions UI without digging through logs.
    Safe: Never includes secrets, signing headers, or full response bodies.

    Shows error details for:
    - HTTP non-2xx responses
    - HTTP 2xx with semantic error status (status="error" or "cancelled")

    Args:
        task_name: Name of the task that ran
        status_code: HTTP response status code (None if no request made)
        job_run_id: JobRun ID from response (if present)
        result_status: Status field from response (if present)
        error_snippet: Truncated error message for errors (HTTP or semantic)
        skipped: Whether task was skipped (time-gate, etc.)
        skip_reason: Reason for skip
        dry_run: Whether this was a dry run
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return  # Not running in GitHub Actions

    try:
        # Build summary markdown
        lines = []
        lines.append(f"### Task: `{task_name}`")
        lines.append("")

        if dry_run:
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| **Mode** | 🔍 Dry Run |")
            lines.append(f"| **Result** | Request prepared but not sent |")
        elif skipped:
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| **Mode** | ⏭️ Skipped |")
            lines.append(f"| **Reason** | {skip_reason or 'Time gate'} |")
        elif status_code is not None:
            is_http_success = 200 <= status_code < 300
            is_semantic_error = result_status in SEMANTIC_ERROR_STATUSES

            # Show warning emoji for semantic errors even on HTTP 200
            if is_semantic_error:
                status_emoji = "⚠️"
            elif is_http_success:
                status_emoji = "✅"
            else:
                status_emoji = "❌"

            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| **Status** | {status_emoji} {status_code} |")

            if job_run_id:
                lines.append(f"| **JobRun ID** | `{job_run_id}` |")
            if result_status:
                result_emoji = "⚠️ " if is_semantic_error else ""
                lines.append(f"| **Result** | {result_emoji}{result_status} |")

            # Show error row for HTTP errors OR semantic errors
            if error_snippet and (not is_http_success or is_semantic_error):
                # Snippet should already be sanitized, but ensure safe for markdown
                safe_snippet = error_snippet[:MAX_SNIPPET_LENGTH]
                if len(error_snippet) > MAX_SNIPPET_LENGTH:
                    safe_snippet += "..."
                safe_snippet = safe_snippet.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| **Error** | {safe_snippet} |")
        else:
            # Request exception (no status code)
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.append(f"| **Status** | ❌ Request Failed |")
            if error_snippet:
                safe_snippet = error_snippet[:MAX_SNIPPET_LENGTH]
                if len(error_snippet) > MAX_SNIPPET_LENGTH:
                    safe_snippet += "..."
                safe_snippet = safe_snippet.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| **Error** | {safe_snippet} |")

        lines.append("")

        # Append to summary file
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    except Exception as e:
        # Don't fail the task if summary writing fails
        print(f"[WARN] Failed to write step summary: {e}")


# =============================================================================
# Request Execution
# =============================================================================

def get_signing_secret() -> tuple[str, Optional[str]]:
    """
    Get signing secret from environment.

    Returns:
        Tuple of (secret, key_id) - key_id may be None for single-key setup

    Raises:
        ValueError if no signing secret is configured
    """
    # Try multi-key format first
    keys_str = os.environ.get("TASK_SIGNING_KEYS", "")
    if keys_str:
        # Format: kid1:secret1,kid2:secret2
        # Use first key by default
        first_pair = keys_str.split(",")[0]
        if ":" in first_pair:
            key_id, secret = first_pair.split(":", 1)
            return secret.strip(), key_id.strip()

    # Fall back to single secret
    secret = os.environ.get("TASK_SIGNING_SECRET", "")
    if secret:
        return secret, None

    raise ValueError(
        "No signing secret configured. "
        "Set TASK_SIGNING_SECRET or TASK_SIGNING_KEYS environment variable."
    )


def build_payload(
    task_name: str,
    user_id: Optional[str] = None,
    payload_json: Optional[str] = None,
    skip_sync: bool = False,
    force_rerun: bool = False,
) -> dict:
    """
    Build the request payload for a task.

    Priority (later overrides earlier):
    1. Task-specific defaults (e.g., strategy_name)
    2. user_id from environment/CLI (only if task allows it)
    3. skip_sync flag
    4. force_rerun flag
    5. payload_json (if provided, merges and overrides all above)

    Args:
        task_name: Name of the task
        user_id: User ID from environment or CLI
        payload_json: Optional JSON string to parse and merge
        skip_sync: If True, adds skip_sync=true to payload
        force_rerun: If True, adds force_rerun=true to payload

    Returns:
        Combined payload dict

    Raises:
        ValueError: If payload_json is invalid JSON or task requires user_id but none provided
    """
    payload = {}

    # Get task config
    task = TASKS.get(task_name, {})
    user_id_mode = task.get("user_id_mode", "none")

    # 1. Add task-specific defaults
    if task_name in ("suggestions_close", "suggestions_open"):
        payload["strategy_name"] = "spy_opt_autolearn_v6"

    # 2. Handle user_id based on task's user_id_mode
    if user_id_mode == "require":
        if not user_id:
            raise ValueError(
                f"Task '{task_name}' requires user_id but none was provided. "
                f"Use --user-id or set USER_ID environment variable."
            )
        payload["user_id"] = user_id
    elif user_id_mode == "allow":
        # Only inject if provided
        if user_id:
            payload["user_id"] = user_id
    # user_id_mode == "none": never inject user_id automatically

    # 3. Add skip_sync if specified
    if skip_sync:
        payload["skip_sync"] = True

    # 4. Add force_rerun if specified
    if force_rerun:
        payload["force_rerun"] = True

    # 5. Merge payload_json (overrides all above)
    # Treat None, empty string, and whitespace-only as "not provided"
    if payload_json is not None:
        payload_json_stripped = payload_json.strip()
        if payload_json_stripped:
            try:
                custom = json.loads(payload_json_stripped)
                if not isinstance(custom, dict):
                    raise ValueError(
                        f"payload_json must be a JSON object, got {type(custom).__name__}"
                    )
                payload.update(custom)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in payload_json: {e}")

    return payload


def run_task(
    task_name: str,
    user_id: Optional[str] = None,
    dry_run: bool = False,
    skip_time_gate: bool = False,
    timeout: int = 120,
    payload_json: Optional[str] = None,
    skip_sync: bool = False,
    force_rerun: bool = False,
) -> int:
    """
    Run a signed task request.

    Args:
        task_name: Name of the task to run
        user_id: Optional user ID to run for
        dry_run: If True, print request without sending
        skip_time_gate: If True, skip time gate check
        timeout: Request timeout in seconds
        payload_json: Optional JSON string to merge into payload
        skip_sync: If True, adds skip_sync=true to payload
        force_rerun: If True, adds force_rerun=true to payload

    Returns:
        0 on success, 1 on failure
    """
    # Validate task name
    if task_name not in TASKS:
        print(f"[ERROR] Unknown task: {task_name}")
        print(f"Available tasks: {', '.join(TASKS.keys())}")
        return 1

    task = TASKS[task_name]

    # Check time gate
    if not check_time_gate(task_name, skip_time_gate):
        write_step_summary(task_name, skipped=True, skip_reason="Time gate")
        return 0  # Not an error, just skipped

    # Get base URL
    base_url = os.environ.get("BASE_URL", "")
    if not base_url:
        print("[ERROR] BASE_URL environment variable is required")
        return 1

    # Get signing secret
    try:
        secret, key_id = get_signing_secret()
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    # Build request
    method = "POST"
    path = task["path"]
    scope = task["scope"]
    try:
        payload = build_payload(task_name, user_id, payload_json, skip_sync, force_rerun)
    except ValueError as e:
        print(f"[ERROR] {e}")
        write_step_summary(
            task_name,
            skipped=True,
            skip_reason=str(e),
        )
        return 1
    body = json.dumps(payload).encode("utf-8") if payload else b"{}"

    # Sign request
    headers = sign_task_request(
        method=method,
        path=path,
        body=body,
        scope=scope,
        secret=secret,
        key_id=key_id,
    )
    headers["Content-Type"] = "application/json"

    url = f"{base_url.rstrip('/')}{path}"

    # Log request (without sensitive data)
    print(f"[REQUEST] {method} {url}")
    print(f"[REQUEST] Scope: {scope}")
    print(f"[REQUEST] Payload: {json.dumps(payload)}")
    print(f"[REQUEST] Headers: X-Task-Ts, X-Task-Nonce, X-Task-Scope, X-Task-Signature" +
          (", X-Task-Key-Id" if key_id else ""))

    if dry_run:
        print("[DRY-RUN] Request would be sent (not actually sending)")
        write_step_summary(task_name, dry_run=True)
        return 0

    # Send request
    try:
        print(f"[SENDING] Making request with {timeout}s timeout...")
        response = requests.post(
            url,
            data=body,
            headers=headers,
            timeout=timeout,
        )

        print(f"[RESPONSE] Status: {response.status_code}")

        if response.status_code >= 200 and response.status_code < 300:
            job_run_id = None
            result_status = None
            error_snippet = None

            try:
                result = response.json()
                # Extract standard fields
                job_run_id = result.get("job_run_id")
                result_status = result.get("status")

                # Check for semantic error (HTTP 200 but status=error/cancelled)
                if result_status in SEMANTIC_ERROR_STATUSES:
                    error_snippet = sanitize_snippet(
                        extract_error_snippet(result) or "Unknown error"
                    )
                    print(f"[WARN] Semantic failure: status={result_status}")
                    print(f"[WARN] Detail: {error_snippet}")
                else:
                    print(f"[SUCCESS] Task {task_name} completed successfully")
                    if job_run_id:
                        print(f"[SUCCESS] Job run ID: {job_run_id}")
                    if result_status:
                        print(f"[SUCCESS] Status: {result_status}")

                # Print full response JSON for verbose tasks (paper pipeline debugging)
                if _should_print_response_json(task_name):
                    try:
                        safe_result = _redact_sensitive_fields(result)
                        print(f"[RESPONSE-JSON] {task_name} response:")
                        print(json.dumps(safe_result, indent=2, sort_keys=True))
                    except Exception as json_err:
                        print(f"[RESPONSE-JSON] Failed to serialize response: {json_err}")

            except Exception:
                # JSON parsing failed, treat as success (no semantic error detectable)
                print(f"[SUCCESS] Task {task_name} completed (non-JSON response)")

            write_step_summary(
                task_name,
                status_code=response.status_code,
                job_run_id=job_run_id,
                result_status=result_status,
                error_snippet=error_snippet,
            )

            # Return 1 for semantic errors, 0 for success
            if result_status in SEMANTIC_ERROR_STATUSES:
                return 1
            return 0
        else:
            print(f"[ERROR] Request failed: {response.status_code}")
            error_snippet = None
            try:
                error_detail = response.json()
                error_snippet = str(error_detail.get("detail", response.text[:200]))
                print(f"[ERROR] Detail: {error_snippet}")
            except Exception:
                error_snippet = response.text[:200]
                print(f"[ERROR] Response: {error_snippet}")
            write_step_summary(
                task_name,
                status_code=response.status_code,
                error_snippet=error_snippet,
            )
            return 1

    except requests.exceptions.Timeout:
        print(f"[ERROR] Request timed out after {timeout}s")
        write_step_summary(
            task_name,
            error_snippet=f"Request timed out after {timeout}s",
        )
        return 1
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        write_step_summary(
            task_name,
            error_snippet=str(e),
        )
        return 1


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run signed task requests to /tasks/* endpoints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/run_signed_task.py suggestions_close
    python scripts/run_signed_task.py suggestions_open --user-id abc-123
    python scripts/run_signed_task.py suggestions_open --payload-json '{"skip_sync":true}'
    python scripts/run_signed_task.py suggestions_open --payload-json '{"user_id":"<uuid>","skip_sync":true}'
    python scripts/run_signed_task.py suggestions_open --force-rerun
    DRY_RUN=1 python scripts/run_signed_task.py learning_ingest
    python scripts/run_signed_task.py suggestions_close --skip-time-gate

Environment Variables:
    TASK_SIGNING_SECRET  - Single signing secret
    TASK_SIGNING_KEYS    - Multiple keys (kid1:secret1,kid2:secret2)
    BASE_URL             - API base URL
    DRY_RUN              - Set to "1" for dry run mode
    USER_ID              - Default user ID (can be overridden with --user-id or payload_json)
""",
    )

    parser.add_argument(
        "task",
        choices=list(TASKS.keys()),
        help="Task to run",
    )
    parser.add_argument(
        "--user-id",
        default=os.environ.get("USER_ID"),
        help="Run for specific user ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
        help="Print request without sending",
    )
    parser.add_argument(
        "--skip-time-gate",
        action="store_true",
        help="Skip time gate check (run regardless of current time)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--payload-json",
        type=str,
        default=None,
        help='Custom JSON payload to merge (e.g., \'{"skip_sync":true}\')',
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip holdings sync (adds skip_sync=true to payload)",
    )
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="Force new JobRun even if one exists for this day/config",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_tasks",
        help="List all available tasks",
    )

    args = parser.parse_args()

    if args.list_tasks:
        print("Available tasks:")
        for name, task in TASKS.items():
            print(f"  {name:20s} - {task['description']}")
            print(f"    Path:  {task['path']}")
            print(f"    Scope: {task['scope']}")
        return 0

    return run_task(
        task_name=args.task,
        user_id=args.user_id,
        dry_run=args.dry_run,
        skip_time_gate=args.skip_time_gate,
        timeout=args.timeout,
        payload_json=args.payload_json,
        skip_sync=args.skip_sync,
        force_rerun=args.force_rerun,
    )


if __name__ == "__main__":
    sys.exit(main())
