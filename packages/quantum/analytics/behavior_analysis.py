from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from collections import Counter
from supabase import Client
from packages.quantum.services.analytics_service import AnalyticsService

class BehaviorAnalysisService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_behavior_summary(self, user_id: str, window_days: int = 7, strategy_family: str = None) -> Dict[str, Any]:
        """
        Aggregates system behavior:
        1. Veto Rate (% of trades rejected by agent)
        2. Top Active Constraints
        3. Most Common Fallback Strategies (or just strategies used)
        """
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

        # 1. Fetch Suggestions (Accepted/Pending/Rejected)
        suggestions_query = self.supabase.table("trade_suggestions") \
            .select("strategy,agent_summary,status") \
            .eq("user_id", user_id) \
            .gte("created_at", cutoff_date)

        if strategy_family:
            suggestions_query = suggestions_query.eq("strategy", strategy_family)

        suggestions = suggestions_query.execute().data

        # 2. Fetch Vetoes from Decision Logs
        vetoes_query = self.supabase.table("decision_logs") \
            .select("content") \
            .eq("user_id", user_id) \
            .eq("decision_type", "trade_veto") \
            .gte("created_at", cutoff_date)

        vetoes = vetoes_query.execute().data

        # Filter vetoes by strategy
        # We only include vetoes that explicitly match the strategy family if one is requested.
        # Global vetoes (strategy=None) are EXCLUDED when filtering by a specific family,
        # as they cannot be attributed to that specific strategy instance.
        if strategy_family:
            filtered_vetoes = []
            for v in vetoes:
                content = v.get("content", {})
                if content.get("strategy") == strategy_family:
                    filtered_vetoes.append(v)
            vetoes = filtered_vetoes

        # --- Aggregate: Veto Rate ---
        # Denominator = Suggestions + Vetoes
        num_suggestions = len(suggestions)
        num_vetoes = len(vetoes)
        total_opportunities = num_suggestions + num_vetoes

        veto_rate = 0.0
        if total_opportunities > 0:
            veto_rate = (num_vetoes / total_opportunities) * 100.0

        # Veto Breakdown by Agent
        veto_reasons = Counter()
        for v in vetoes:
            content = v.get("content", {})
            agent = content.get("agent", "Unknown")
            veto_reasons[agent] += 1

        # --- Aggregate: Active Constraints ---
        # From suggestions -> agent_summary -> active_constraints
        constraint_counts = Counter()
        for s in suggestions:
            summary = s.get("agent_summary") or {}
            constraints = summary.get("active_constraints") or {}
            for key in constraints.keys():
                constraint_counts[key] += 1

        top_constraints = [
            {"constraint": k, "count": v}
            for k, v in constraint_counts.most_common(5)
        ]

        # --- Aggregate: Fallback Strategies / Strategy Distribution ---

        fallback_logs_query = self.supabase.table("decision_logs") \
            .select("content") \
            .eq("user_id", user_id) \
            .eq("decision_type", "system_fallback") \
            .gte("created_at", cutoff_date)

        fallback_logs = fallback_logs_query.execute().data

        # Filter fallbacks by strategy
        if strategy_family:
            filtered_fallbacks = []
            for f in fallback_logs:
                content = f.get("content", {})
                if content.get("strategy") == strategy_family:
                    filtered_fallbacks.append(f)
            fallback_logs = filtered_fallbacks

        system_fallbacks = Counter()
        for f in fallback_logs:
            content = f.get("content", {})
            fb_type = content.get("fallback", "unknown")
            system_fallbacks[fb_type] += 1

        # Strategy Distribution (of Suggestions)
        strategy_counts = Counter()
        for s in suggestions:
            strat = s.get("strategy", "unknown")
            strategy_counts[strat] += 1

        most_common_strategies = [
            {"strategy": k, "count": v}
            for k, v in strategy_counts.most_common(5)
        ]

        most_common_fallbacks = [
            {"type": k, "count": v}
            for k, v in system_fallbacks.most_common(5)
        ]

        return {
            "window": f"{window_days}d",
            "veto_rate_pct": round(veto_rate, 2),
            "veto_breakdown": dict(veto_reasons),
            "top_active_constraints": top_constraints,
            "top_strategies": most_common_strategies,
            "system_fallbacks": most_common_fallbacks
        }
