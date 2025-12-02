from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone, date
from supabase import Client
import json

# --- Config / Defaults ---
DEFAULT_WEEKLY_METRICS = {
    "dominant_regime": "Neutral",
    "avg_ivr": 50.0,
    "execution_efficiency": 0.95,
    "overall_quality": 85.0,
    "score_outcome_corr": 0.1,
    "regime_stability": 0.8
}

def get_week_id_for_last_full_week(ref_date: Optional[date] = None) -> str:
    """
    Returns a canonical week id string like 'YYYY-Www' (ISO week) for the last full week.
    If ref_date is None, uses today.
    Last full week is defined as the most recently completed Monday-Sunday cycle.
    """
    if not ref_date:
        ref_date = datetime.now(timezone.utc).date()

    # ISO weekday: Mon=1, Sun=7
    # Go back to last Sunday
    days_since_sunday = ref_date.isoweekday() % 7 # 0=Sun, 1=Mon, ... 6=Sat?
    # Wait, isoweekday: Mon=1...Sun=7. 7%7 = 0.
    # If today is Monday(1), last Sunday was 1 day ago.
    # If today is Sunday(7), last Sunday was 0 days ago (today). But we want COMPLETED week.
    # So if today is Sunday, the last *full* week ended LAST Sunday (7 days ago).
    # Actually, standard logic:
    # A full week runs Mon-Sun.
    # If today is Wednesday, the last full week is the one that ended last Sunday.

    offset = ref_date.isoweekday() # 1..7
    last_sunday = ref_date - timedelta(days=offset)

    # The week ending on last_sunday is the one we want.
    # ISO week ID comes from any day in that week. Let's pick the Monday of that week.
    monday_of_that_week = last_sunday - timedelta(days=6)

    # Generate ID
    return monday_of_that_week.strftime("%Y-W%V")

class ProgressEngine:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.weekly_snapshots_table = "weekly_snapshots"
        self.logs_table = "suggestion_logs"
        self.executions_table = "trade_executions"
        self.snapshots_table = "portfolio_snapshots"

    def generate_weekly_snapshot(self, user_id: str, week_id: Optional[str] = None):
        """
        Aggregates metrics for a given week and upserts a WeeklySnapshot.
        week_id format: "YYYY-Wnn" (ISO week). Defaults to last full week.
        """
        # 1. Resolve Week ID and Dates
        if not week_id:
            week_id = get_week_id_for_last_full_week()

        # Parse start/end from week_id (ISO format)
        try:
            # Use manual parsing or fromisocalendar for portability
            # week_id format is "YYYY-Www"
            y_str, w_str = week_id.split('-W')
            iso_year = int(y_str)
            iso_week = int(w_str)

            # Monday is day 1
            # fromisocalendar(year, week, day) available in Python 3.8+
            start_date = datetime.combine(
                date.fromisocalendar(iso_year, iso_week, 1),
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)

            end_date = start_date + timedelta(days=7) # End is start of next week (exclusive upper bound)
        except (ValueError, AttributeError) as e:
            # Fallback if format is weird
            print(f"Invalid week_id {week_id} ({e}), falling back to last 7 days")
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=7)

        # 2. Fetch Data
        logs = self._fetch_logs(user_id, start_date, end_date)
        executions = self._fetch_executions(user_id, start_date, end_date)
        snapshots = self._fetch_snapshots(user_id, start_date, end_date)

        has_data = bool(logs or executions or snapshots)

        # 3. Compute Metrics
        if has_data:
            user_metrics = self._compute_user_metrics(logs, executions, snapshots)
            system_metrics = self._compute_system_metrics(logs, executions)
            synthesis = {
                "headline": f"Progress Report for {week_id}",
                "action_items": ["Review missed suggestions" if user_metrics['components']['adherence_ratio']['value'] < 0.8 else "Maintain discipline"]
            }
        else:
            # Graceful No-Data State
            user_metrics = {
                "overall_score": 0.0,
                "wow_change_pct": 0.0,
                "components": {
                    "adherence_ratio": {"value": 0.0, "label": "Plan Adherence"},
                    "risk_compliance": {"value": 0.0, "label": "Risk Compliance"}, # Neutral/Zero
                    "execution_efficiency": {"value": 0.0, "label": "Execution Quality"}
                },
                "pnl_attribution": {"realized_pnl": 0.0, "alpha_over_plan": 0.0}
            }
            system_metrics = {
                "overall_quality": 0.0,
                "wow_change_pct": 0.0,
                "components": {
                    "win_rate_high_confidence": {"value": 0.0, "label": "Win Rate (High Conf)"},
                    "score_outcome_corr": {"value": 0.0, "label": "Score-Outcome IC"},
                    "regime_stability": {"value": 0.0, "label": "Regime Stability"}
                }
            }
            synthesis = {
                "headline": f"No Data for {week_id}",
                "action_items": ["Activity will appear here once trading cycles complete."]
            }

        # 4. Upsert
        snapshot_data = {
            "user_id": user_id,
            "week_id": week_id,
            "date_start": start_date.isoformat(),
            "date_end": end_date.isoformat(),
            "dominant_regime": DEFAULT_WEEKLY_METRICS["dominant_regime"], # TODO: Derive from logs
            "avg_ivr": DEFAULT_WEEKLY_METRICS["avg_ivr"], # TODO: Derive
            "user_metrics": user_metrics,
            "system_metrics": system_metrics,
            "synthesis": synthesis,
            "has_data": has_data,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        try:
            self.supabase.table(self.weekly_snapshots_table)\
                .upsert(snapshot_data, on_conflict="user_id,week_id")\
                .execute()
        except Exception as e:
            print(f"Error upserting weekly snapshot: {e}")

        return snapshot_data

    def _fetch_logs(self, user_id, start, end):
        try:
            res = self.supabase.table(self.logs_table)\
                .select("*")\
                .eq("user_id", user_id)\
                .gte("created_at", start.isoformat())\
                .lt("created_at", end.isoformat())\
                .execute()
            return res.data or []
        except: return []

    def _fetch_executions(self, user_id, start, end):
        try:
            res = self.supabase.table(self.executions_table)\
                .select("*")\
                .eq("user_id", user_id)\
                .gte("timestamp", start.isoformat())\
                .lt("timestamp", end.isoformat())\
                .execute()
            return res.data or []
        except: return []

    def _fetch_snapshots(self, user_id, start, end):
        try:
            res = self.supabase.table(self.snapshots_table)\
                .select("*")\
                .eq("user_id", user_id)\
                .gte("created_at", start.isoformat())\
                .lt("created_at", end.isoformat())\
                .execute()
            return res.data or []
        except: return []

    def _compute_user_metrics(self, logs, executions, snapshots):
        # Adherence
        total_suggestions = len(logs)
        executed_suggestions = len([l for l in logs if l.get("was_accepted")])
        adherence = (executed_suggestions / total_suggestions) if total_suggestions > 0 else 0.0

        # Risk Compliance
        if not snapshots:
            risk_compliance = 0.5 # Neutral default if no snapshots
        else:
            compliant_snapshots = 0
            for s in snapshots:
                # Basic check: if risk_metrics exists and no error
                rm = s.get("risk_metrics", {})
                if rm and "error" not in rm:
                    compliant_snapshots += 1
            risk_compliance = compliant_snapshots / len(snapshots)

        return {
            "overall_score": round(adherence * 100, 1),
            "wow_change_pct": 0.0,
            "components": {
                "adherence_ratio": {"value": adherence, "label": "Plan Adherence"},
                "risk_compliance": {"value": risk_compliance, "label": "Risk Compliance"},
                "execution_efficiency": {"value": DEFAULT_WEEKLY_METRICS["execution_efficiency"], "label": "Execution Quality"}
            },
            "pnl_attribution": {
                "realized_pnl": sum([e.get("realized_pnl") or 0 for e in executions]),
                "alpha_over_plan": 0.0
            }
        }

    def _compute_system_metrics(self, logs, executions):
        # Win Rate High Confidence
        # Filter logs with high confidence (> 70)
        high_conf_logs = [l for l in logs if l.get("confidence_score", 0) > 70]
        wins = 0
        valid_samples = 0

        # In a real system, we'd link logs -> executions -> outcomes.
        # Here we approximate: if it was accepted, assume user followed it.
        # But we need outcome data (PnL).
        # We'll look for execution records that might match, or assume missing data means exclude.

        # Simplified logic:
        # If we have executions, try to match by symbol/time?
        # For now, let's just stick to the requested "accepted AND realized_pnl > 0" check
        # But logs don't have pnl. Executions do.

        # Heuristic: iterate executions, check if they match a high-conf suggestion
        # This requires matching logic.
        # Fallback: Just calculate win rate of ALL executions in this period,
        # assuming they came from suggestions.

        # Better: The user asked "Only count a suggestion as win if accepted AND realized_pnl > 0".
        # We can't know PnL without linking.
        # If we can't link, we return 0 or None.

        # Let's try to find if 'suggestion_id' is in execution
        linked_executions = [e for e in executions if e.get("suggestion_id")]

        if linked_executions:
            for exc in linked_executions:
                # Check if parent suggestion was high confidence
                # This requires fetching suggestion data again or having it in memory.
                # `logs` has all suggestions for this week.
                parent_suggestion = next((l for l in logs if l.get("id") == exc.get("suggestion_id")), None)

                if parent_suggestion and parent_suggestion.get("confidence_score", 0) > 70:
                    valid_samples += 1
                    if (exc.get("realized_pnl") or 0) > 0:
                        wins += 1

        win_rate = (wins / valid_samples) if valid_samples > 0 else 0.0

        return {
            "overall_quality": DEFAULT_WEEKLY_METRICS["overall_quality"],
            "wow_change_pct": 0.0,
            "components": {
                "win_rate_high_confidence": {"value": win_rate, "label": "Win Rate (High Conf)"},
                "score_outcome_corr": {"value": DEFAULT_WEEKLY_METRICS["score_outcome_corr"], "label": "Score-Outcome IC"},
                "regime_stability": {"value": DEFAULT_WEEKLY_METRICS["regime_stability"], "label": "Regime Stability"}
            }
        }
