from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from supabase import Client
from packages.quantum.analytics.behavior_analysis import BehaviorAnalysisService
from packages.quantum.services.provider_guardrails import get_circuit_breaker
from packages.quantum.services.market_data_cache import get_market_data_cache

class SystemHealthService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.behavior_service = BehaviorAnalysisService(supabase)

    def get_system_health(self, user_id: str) -> Dict[str, Any]:
        """
        Aggregates system health metrics:
        - System Status (Normal, Conservative, Data-Limited)
        - Provider Health (Polygon status, failures)
        - Cache Stats
        - Veto Rate (7d / 30d)
        - Most Active Constraints
        - % NOT_EXECUTABLE suggestions
        - % PARTIAL outcomes
        """

        # 1. Calculate Veto Rates & Constraints (using BehaviorAnalysisService)
        # We fetch 30d to cover the long window and constraints
        stats_30d = self.behavior_service.get_behavior_summary(user_id, window_days=30)

        # We fetch 7d just for the veto rate
        stats_7d = self.behavior_service.get_behavior_summary(user_id, window_days=7)

        # 2. Check System Status
        status_label = "Normal"

        # Check Data-Limited: Universe Size
        # We count rows in scanner_universe. If 0 or low, it's data limited.
        try:
            universe_count = self.supabase.table("scanner_universe").select("ticker", count="exact").execute().count
            if universe_count is None or universe_count < 10:
                status_label = "Data-Limited"
        except Exception:
            # If query fails, assume data issues
            status_label = "Data-Limited"

        # Check Provider Health
        polygon_breaker = get_circuit_breaker("polygon")
        provider_metrics = polygon_breaker.get_metrics()

        if provider_metrics["state"] == "OPEN":
            status_label = "Data-Limited" # Provider down overrides normal

        # Check Conservative: Recent Regime from Suggestions
        # If not already Data-Limited, check if we are in a defensive regime
        if status_label == "Normal":
            try:
                # Get most recent suggestion to check regime context
                recent_suggestion = self.supabase.table("trade_suggestions") \
                    .select("agent_summary") \
                    .eq("user_id", user_id) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute().data

                if recent_suggestion:
                    summary = recent_suggestion[0].get("agent_summary", {})
                    # Check for explicit regime keys or risk overrides
                    regime = summary.get("regime_context", {}).get("regime", "").lower()
                    if regime in ["shock", "crash", "bear_volatile"]:
                        status_label = "Conservative"
            except Exception:
                pass

        # 3. % NOT_EXECUTABLE Suggestions (30d)
        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        try:
            suggestions_30d = self.supabase.table("trade_suggestions") \
                .select("status") \
                .eq("user_id", user_id) \
                .gte("created_at", cutoff_30d) \
                .execute().data

            total_suggestions = len(suggestions_30d)
            not_executable_count = sum(1 for s in suggestions_30d if s.get("status") == "NOT_EXECUTABLE")

            not_executable_pct = 0.0
            if total_suggestions > 0:
                not_executable_pct = (not_executable_count / total_suggestions) * 100.0
        except Exception:
            not_executable_pct = 0.0

        # 4. % PARTIAL Outcomes (30d)
        # Assuming outcomes_log tracks completed/partial trades
        try:
            outcomes_30d = self.supabase.table("outcomes_log") \
                .select("status") \
                .eq("user_id", user_id) \
                .gte("created_at", cutoff_30d) \
                .execute().data

            total_outcomes = len(outcomes_30d)
            partial_count = sum(1 for o in outcomes_30d if o.get("status") == "PARTIAL")

            partial_pct = 0.0
            if total_outcomes > 0:
                partial_pct = (partial_count / total_outcomes) * 100.0
        except Exception:
            partial_pct = 0.0

        # 5. Cache Stats
        cache_stats = get_market_data_cache().get_stats()

        return {
            "status": status_label,
            "provider_health": {
                "polygon": provider_metrics
            },
            "cache_stats": cache_stats,
            "veto_rate_7d": stats_7d["veto_rate_pct"],
            "veto_rate_30d": stats_30d["veto_rate_pct"],
            "active_constraints": stats_30d["top_active_constraints"],
            "not_executable_pct": round(not_executable_pct, 2),
            "partial_outcomes_pct": round(partial_pct, 2)
        }
