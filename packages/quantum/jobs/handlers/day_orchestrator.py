"""
Day Orchestrator Agent

Runs once at 7:30 AM CT. Coordinates the full trading day job chain
with explicit dependency tracking and missed-job recovery.

Does not execute business logic itself — calls existing internal task
endpoints in the right order via signed HTTP requests.

Feature-gated by ORCHESTRATOR_ENABLED (default 0).
"""

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import httpx

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.job_dependency_service import JobDependencyService

logger = logging.getLogger(__name__)

JOB_NAME = "day_orchestrator"
CHICAGO_TZ = ZoneInfo("America/Chicago")
ORCHESTRATOR_ENABLED = os.environ.get("ORCHESTRATOR_ENABLED", "0") == "1"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Main entry point."""
    if not ORCHESTRATOR_ENABLED:
        return {"ok": True, "status": "disabled", "note": "ORCHESTRATOR_ENABLED != 1"}

    start_time = time.time()
    try:
        orch = DayOrchestrator()
        result = orch.execute(payload)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result
    except Exception as e:
        logger.error(f"[ORCHESTRATOR] Fatal error: {e}", exc_info=True)
        return {
            "ok": False,
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000),
        }


class DayOrchestrator:

    def __init__(self):
        self.supabase = get_admin_client()
        self.deps = JobDependencyService(self.supabase)
        self.trade_date = datetime.now(CHICAGO_TZ).strftime("%Y-%m-%d")
        self.base_url = os.environ.get("SCHEDULER_BASE_URL", "http://127.0.0.1:8000")
        self.results: List[Dict] = []

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run boot check and record session. Actual scheduling is still APScheduler."""
        # Log session start
        session_id = self._log_session_start()

        # 1. Boot check — detect missed jobs from yesterday
        yesterday = (datetime.now(CHICAGO_TZ) - timedelta(days=1))
        # Skip weekends
        if yesterday.weekday() < 5:
            yesterday_str = yesterday.strftime("%Y-%m-%d")
            missed = self.deps.get_missed_jobs(yesterday_str)
            critical_missed = [j for j in missed if j in JobDependencyService.CRITICAL_JOBS]

            if critical_missed:
                msg = f"Critical jobs missed yesterday ({yesterday_str}): {critical_missed}"
                logger.critical(f"[ORCHESTRATOR] {msg}")
                self._write_alert(msg, severity="high")

            if missed:
                logger.warning(
                    f"[ORCHESTRATOR] {len(missed)} jobs missed yesterday: {missed}"
                )

        # 2. Show today's chain status
        chain_status = self.deps.get_chain_status(self.trade_date)

        # 3. Generate summary
        summary = {
            "trade_date": self.trade_date,
            "yesterday_missed": missed if yesterday.weekday() < 5 else [],
            "chain_status": chain_status,
            "boot_time": datetime.now(CHICAGO_TZ).isoformat(),
        }

        # Log session completion
        self._log_session_complete(session_id, summary)

        return {
            "ok": True,
            "status": "completed",
            "trade_date": self.trade_date,
            "missed_yesterday": len(missed) if yesterday.weekday() < 5 else 0,
            "critical_missed": len(critical_missed) if yesterday.weekday() < 5 else 0,
        }

    def _write_alert(self, message: str, severity: str = "high"):
        """Write alert to risk_alerts for visibility."""
        try:
            user_id = os.environ.get("USER_ID") or os.environ.get("TASK_USER_ID")
            if user_id:
                self.supabase.table("risk_alerts").insert({
                    "user_id": user_id,
                    "alert_type": "warn",
                    "severity": severity,
                    "message": f"[ORCHESTRATOR] {message}",
                    "metadata": {"trade_date": self.trade_date},
                }).execute()
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Failed to write alert: {e}")

    def _log_session_start(self) -> str:
        """Log orchestrator session start."""
        try:
            res = self.supabase.table("agent_sessions").insert({
                "agent_name": "orchestrator",
                "status": "started",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"trade_date": self.trade_date},
            }).execute()
            return res.data[0]["id"] if res.data else ""
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Failed to log session start: {e}")
            return ""

    def _log_session_complete(self, session_id: str, summary: Dict):
        """Log orchestrator session completion."""
        if not session_id:
            return
        try:
            self.supabase.table("agent_sessions") \
                .update({
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "summary": summary,
                }) \
                .eq("id", session_id) \
                .execute()
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Failed to log session complete: {e}")
