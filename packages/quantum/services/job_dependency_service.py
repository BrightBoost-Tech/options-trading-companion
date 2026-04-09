"""
Job Dependency Service

Tracks job completion and enables dependency-based sequencing.
Used by the Day Orchestrator to verify job chain ordering.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobDependencyService:
    """Tracks and validates job execution dependencies."""

    # Define the dependency chain for the full trading day
    JOB_CHAIN = {
        "suggestions_close":           {"depends_on": None,                     "timeout_min": 15},
        "paper_exit_evaluate_morning":  {"depends_on": "suggestions_close",      "timeout_min": 10},
        "alpaca_order_sync":            {"depends_on": None,                     "timeout_min": 5},
        "suggestions_open":            {"depends_on": None,                     "timeout_min": 20},
        "paper_auto_execute":          {"depends_on": "suggestions_open",       "timeout_min": 15},
        "intraday_risk_monitor":       {"depends_on": None,                     "timeout_min": 5},
        "paper_exit_evaluate_afternoon":{"depends_on": None,                     "timeout_min": 10},
        "paper_mark_to_market":        {"depends_on": "paper_exit_evaluate_afternoon", "timeout_min": 10},
        "daily_progression_eval":      {"depends_on": "paper_mark_to_market",   "timeout_min": 5},
        "paper_learning_ingest":       {"depends_on": "daily_progression_eval", "timeout_min": 15},
        "post_trade_learning":         {"depends_on": "paper_learning_ingest",  "timeout_min": 20},
        "policy_lab_eval":             {"depends_on": "post_trade_learning",    "timeout_min": 10},
        "promotion_check":            {"depends_on": "policy_lab_eval",         "timeout_min": 5},
    }

    # Jobs whose failure should trigger an alert
    CRITICAL_JOBS = {
        "paper_learning_ingest", "daily_progression_eval",
        "paper_mark_to_market", "suggestions_open",
    }

    def __init__(self, supabase):
        self.supabase = supabase

    def is_dependency_met(self, job_name: str, trade_date: str) -> bool:
        """Check if the job's dependency has completed successfully today."""
        chain = self.JOB_CHAIN.get(job_name)
        if not chain or not chain["depends_on"]:
            return True

        dep = chain["depends_on"]
        try:
            res = self.supabase.table("job_runs") \
                .select("status") \
                .eq("job_name", dep) \
                .like("idempotency_key", f"%{trade_date}%") \
                .in_("status", ["succeeded", "partial_failure"]) \
                .limit(1) \
                .execute()
            return bool(res.data)
        except Exception as e:
            logger.warning(f"[DEP_CHECK] Failed to check {dep} for {job_name}: {e}")
            return True  # Fail open — don't block the chain

    def get_missed_jobs(self, trade_date: str) -> List[str]:
        """Return jobs expected but not run for a given trade date."""
        # Only check once-daily jobs (skip recurring ones like alpaca_order_sync)
        once_daily = [
            name for name, cfg in self.JOB_CHAIN.items()
            if name not in ("alpaca_order_sync", "intraday_risk_monitor")
        ]

        missed = []
        try:
            res = self.supabase.table("job_runs") \
                .select("job_name") \
                .like("idempotency_key", f"%{trade_date}%") \
                .in_("status", ["succeeded", "partial_failure"]) \
                .execute()

            completed = {r["job_name"] for r in (res.data or [])}
            missed = [j for j in once_daily if j not in completed]
        except Exception as e:
            logger.error(f"[DEP_CHECK] Failed to get missed jobs: {e}")

        return missed

    def get_chain_status(self, trade_date: str) -> Dict[str, str]:
        """Return full status of today's job chain."""
        status_map = {}
        try:
            res = self.supabase.table("job_runs") \
                .select("job_name, status") \
                .like("idempotency_key", f"%{trade_date}%") \
                .execute()

            for row in (res.data or []):
                status_map[row["job_name"]] = row["status"]
        except Exception as e:
            logger.error(f"[DEP_CHECK] Failed to get chain status: {e}")

        result = {}
        for job_name in self.JOB_CHAIN:
            result[job_name] = status_map.get(job_name, "pending")
        return result
