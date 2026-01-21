"""
Market Hours Ops v4 Orchestrator Job Handler

Orchestrates v4 Accounting ops jobs (marks refresh, seed review) based on
market hours mode. Can be triggered by existing scheduler/cron/daily pipeline.

Usage:
    Enqueue: {"job_name": "run_market_hours_ops_v4"}
    Payload:
        - mode: str - "PREOPEN" | "INTRADAY" | "CLOSE" | "WEEKEND" (default "INTRADAY")
        - max_users: int | None (optional, cap on users)
        - max_symbols_per_user: int (default varies by mode)
        - batch_size: int (default 25)
        - include_seed_review: bool (default varies by mode)
        - seed_review_limit: int (default 50)

Modes:
    PREOPEN: Run marks refresh + seed review report (conservative throttles)
    INTRADAY: Run marks refresh only (standard throttles)
    CLOSE: Run marks refresh with higher cap for EOD snapshot
    WEEKEND: Run seed review report with include_resolved=true (audit mode)
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.jobs.handlers import refresh_ledger_marks_v4
from packages.quantum.jobs.handlers import report_seed_review_v4

JOB_NAME = "run_market_hours_ops_v4"

logger = logging.getLogger(__name__)

# Mode-specific defaults
MODE_DEFAULTS = {
    "PREOPEN": {
        "max_symbols_per_user": 50,
        "batch_size": 25,
        "include_seed_review": True,
        "seed_review_limit": 50,
        "marks_source": "MARKET",
    },
    "INTRADAY": {
        "max_symbols_per_user": 50,
        "batch_size": 25,
        "include_seed_review": False,
        "seed_review_limit": 50,
        "marks_source": "MARKET",
    },
    "CLOSE": {
        "max_symbols_per_user": 100,
        "batch_size": 50,
        "include_seed_review": False,
        "seed_review_limit": 50,
        "marks_source": "EOD",
    },
    "WEEKEND": {
        "max_symbols_per_user": 50,
        "batch_size": 25,
        "include_seed_review": True,
        "seed_review_limit": 100,
        "include_resolved": True,
        "skip_marks_refresh": True,  # Market closed, don't fetch quotes
        "marks_source": "EOD",
    },
}


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Orchestrate v4 Accounting ops jobs based on market hours mode.

    This job calls existing handlers directly with mode-appropriate parameters.
    It does NOT detect time of day - mode is passed by the scheduler/pipeline.

    Payload:
        mode: "PREOPEN" | "INTRADAY" | "CLOSE" | "WEEKEND" (default "INTRADAY")
        max_users: Optional cap on users to process
        max_symbols_per_user: Optional override for symbols per user
        batch_size: Optional override for batch size
        include_seed_review: Optional override for seed review flag
        seed_review_limit: Optional override for seed review limit
        user_id: Optional specific user (passed through to sub-jobs)

    Returns:
        Dict with sub-job results and summary
    """
    start_time = datetime.now(timezone.utc)

    mode = payload.get("mode", "INTRADAY").upper()
    if mode not in MODE_DEFAULTS:
        return {
            "success": False,
            "error": f"Invalid mode: {mode}. Valid modes: PREOPEN, INTRADAY, CLOSE, WEEKEND"
        }

    defaults = MODE_DEFAULTS[mode]

    # Extract parameters with mode-appropriate defaults
    max_users = payload.get("max_users")
    max_symbols_per_user = payload.get("max_symbols_per_user", defaults["max_symbols_per_user"])
    batch_size = payload.get("batch_size", defaults["batch_size"])
    include_seed_review = payload.get("include_seed_review", defaults["include_seed_review"])
    seed_review_limit = payload.get("seed_review_limit", defaults["seed_review_limit"])
    user_id = payload.get("user_id")
    skip_marks_refresh = defaults.get("skip_marks_refresh", False)
    include_resolved = defaults.get("include_resolved", False)
    marks_source = defaults.get("marks_source", "MARKET")

    logger.info(
        f"[MARKET_HOURS_OPS_V4] Starting mode={mode}, "
        f"max_users={max_users}, max_symbols={max_symbols_per_user}, "
        f"batch_size={batch_size}, include_seed_review={include_seed_review}"
    )

    results = {
        "mode": mode,
        "started_at": start_time.isoformat(),
        "marks_result": None,
        "seed_review_result": None,
        "errors": []
    }

    try:
        # 1. Run marks refresh (unless skipped for WEEKEND mode)
        if not skip_marks_refresh:
            marks_payload = {
                "source": marks_source,
                "max_users": max_users,
                "max_symbols_per_user": max_symbols_per_user,
                "batch_size": batch_size,
            }
            if user_id:
                marks_payload["user_id"] = user_id

            logger.info(f"[MARKET_HOURS_OPS_V4] Running refresh_ledger_marks_v4: {marks_payload}")
            try:
                marks_result = refresh_ledger_marks_v4.run(marks_payload)
                results["marks_result"] = marks_result

                if not marks_result.get("success"):
                    results["errors"].append(f"Marks refresh failed: {marks_result.get('error', 'Unknown')}")

            except Exception as e:
                logger.error(f"[MARKET_HOURS_OPS_V4] Marks refresh error: {e}")
                results["marks_result"] = {"success": False, "error": str(e)}
                results["errors"].append(f"Marks refresh exception: {str(e)}")
        else:
            logger.info("[MARKET_HOURS_OPS_V4] Skipping marks refresh (WEEKEND mode)")
            results["marks_result"] = {"skipped": True, "reason": "WEEKEND mode - market closed"}

        # 2. Run seed review report (if enabled for this mode)
        if include_seed_review:
            review_payload = {
                "limit": seed_review_limit,
                "include_resolved": include_resolved,
            }
            if user_id:
                review_payload["user_id"] = user_id

            logger.info(f"[MARKET_HOURS_OPS_V4] Running report_seed_review_v4: {review_payload}")
            try:
                review_result = report_seed_review_v4.run(review_payload)
                results["seed_review_result"] = review_result

                if review_result.get("status") == "failed":
                    results["errors"].append(f"Seed review failed: {review_result.get('error', 'Unknown')}")

            except Exception as e:
                logger.error(f"[MARKET_HOURS_OPS_V4] Seed review error: {e}")
                results["seed_review_result"] = {"status": "failed", "error": str(e)}
                results["errors"].append(f"Seed review exception: {str(e)}")
        else:
            logger.info("[MARKET_HOURS_OPS_V4] Skipping seed review (not enabled for this mode)")
            results["seed_review_result"] = {"skipped": True, "reason": f"Not enabled for {mode} mode"}

        # 3. Compute summary
        duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        results["duration_ms"] = duration_ms
        results["success"] = len(results["errors"]) == 0
        results["completed_at"] = datetime.now(timezone.utc).isoformat()

        logger.info(
            f"[MARKET_HOURS_OPS_V4] Completed mode={mode}, "
            f"success={results['success']}, duration_ms={duration_ms:.1f}"
        )

        return results

    except Exception as e:
        logger.error(f"[MARKET_HOURS_OPS_V4] Fatal error: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "mode": mode,
            "error": str(e),
            "traceback": traceback.format_exc()[:1000],
            "marks_result": results.get("marks_result"),
            "seed_review_result": results.get("seed_review_result"),
        }


# =============================================================================
# Convenience functions for specific modes
# =============================================================================

def run_preopen(
    max_users: Optional[int] = None,
    max_symbols_per_user: int = 50,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to run PREOPEN mode."""
    return run({
        "mode": "PREOPEN",
        "max_users": max_users,
        "max_symbols_per_user": max_symbols_per_user,
        "user_id": user_id,
    })


def run_intraday(
    max_users: Optional[int] = None,
    max_symbols_per_user: int = 50,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to run INTRADAY mode."""
    return run({
        "mode": "INTRADAY",
        "max_users": max_users,
        "max_symbols_per_user": max_symbols_per_user,
        "user_id": user_id,
    })


def run_close(
    max_users: Optional[int] = None,
    max_symbols_per_user: int = 100,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to run CLOSE mode."""
    return run({
        "mode": "CLOSE",
        "max_users": max_users,
        "max_symbols_per_user": max_symbols_per_user,
        "user_id": user_id,
    })


def run_weekend(
    seed_review_limit: int = 100,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to run WEEKEND mode (audit/review only)."""
    return run({
        "mode": "WEEKEND",
        "seed_review_limit": seed_review_limit,
        "user_id": user_id,
    })
