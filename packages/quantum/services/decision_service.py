from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from supabase import Client

class DecisionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_lineage_stats(self, user_id: str, window_days: int) -> Dict[str, Any]:
        """
        Aggregates lineage stats for the given window.
        """
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=window_days)

        try:
            # Query trade_suggestions for the window
            res = self.supabase.table("trade_suggestions") \
                .select("decision_lineage, strategy, created_at") \
                .eq("user_id", user_id) \
                .gte("created_at", start_date.isoformat()) \
                .execute()

            suggestions = res.data or []
            return self._aggregate_stats(suggestions)
        except Exception as e:
            print(f"Error fetching lineage stats: {e}")
            return self._empty_stats()

    def get_lineage_diff(self, user_id: str, window_str: str) -> Dict[str, Any]:
        """
        Compares lineage stats between the current window and the previous window of the same duration.
        Supported windows: '7d', '30d'
        """
        window_days = 7 if window_str == '7d' else 30

        current_stats = self.get_lineage_stats(user_id, window_days)

        # Calculate stats for the previous window (e.g. T-14 to T-7)
        now = datetime.now(timezone.utc)
        prev_end = now - timedelta(days=window_days)
        prev_start = prev_end - timedelta(days=window_days)

        try:
            res = self.supabase.table("trade_suggestions") \
                .select("decision_lineage, strategy, created_at") \
                .eq("user_id", user_id) \
                .gte("created_at", prev_start.isoformat()) \
                .lt("created_at", prev_end.isoformat()) \
                .execute()

            prev_suggestions = res.data or []
            prev_stats = self._aggregate_stats(prev_suggestions)
        except Exception as e:
            print(f"Error fetching previous lineage stats: {e}")
            prev_stats = self._empty_stats()

        diff = self._calculate_diff(current_stats, prev_stats)

        return {
            "window": window_str,
            "current": current_stats,
            "previous": prev_stats,
            "diff": diff
        }

    def _aggregate_stats(self, suggestions: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_count = len(suggestions)
        if total_count == 0:
            return self._empty_stats()

        agent_counts = {}
        strategy_counts = {}
        constraint_counts = {}
        sizing_source_counts = {}

        for s in suggestions:
            lineage = s.get("decision_lineage") or {}

            # Agents involved
            agents = lineage.get("agents_involved", [])
            for agent in agents:
                name = agent.get("name") if isinstance(agent, dict) else agent
                agent_counts[name] = agent_counts.get(name, 0) + 1

            # Strategy
            strat = lineage.get("strategy_chosen") or s.get("strategy") or "unknown"
            strategy_counts[strat] = strategy_counts.get(strat, 0) + 1

            # Constraints
            constraints = lineage.get("active_constraints") or {}
            for k in constraints.keys():
                constraint_counts[k] = constraint_counts.get(k, 0) + 1

            # Sizing Source
            source = lineage.get("sizing_source") or "unknown"
            sizing_source_counts[source] = sizing_source_counts.get(source, 0) + 1

        # Calculate percentages
        agent_dominance = {k: round(v / total_count * 100, 1) for k, v in agent_counts.items()}
        strategy_freq = {k: round(v / total_count * 100, 1) for k, v in strategy_counts.items()}
        constraint_freq = {k: round(v / total_count * 100, 1) for k, v in constraint_counts.items()}
        sizing_auth = {k: round(v / total_count * 100, 1) for k, v in sizing_source_counts.items()}

        return {
            "sample_size": total_count,
            "agent_dominance": agent_dominance,
            "strategy_frequency": strategy_freq,
            "active_constraints": constraint_freq, # Frequency of occurrence
            "unique_constraints": list(constraint_counts.keys()),
            "sizing_authority": sizing_auth
        }

    def _calculate_diff(self, current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
        # Agent Dominance Shifts
        agent_shifts = {}
        all_agents = set(current.get("agent_dominance", {}).keys()) | set(previous.get("agent_dominance", {}).keys())
        for agent in all_agents:
            curr_val = current.get("agent_dominance", {}).get(agent, 0.0)
            prev_val = previous.get("agent_dominance", {}).get(agent, 0.0)
            agent_shifts[agent] = round(curr_val - prev_val, 1)

        # Strategy Frequency Changes
        strategy_shifts = {}
        all_strats = set(current.get("strategy_frequency", {}).keys()) | set(previous.get("strategy_frequency", {}).keys())
        for s in all_strats:
            curr_val = current.get("strategy_frequency", {}).get(s, 0.0)
            prev_val = previous.get("strategy_frequency", {}).get(s, 0.0)
            strategy_shifts[s] = round(curr_val - prev_val, 1)

        # Added/Removed Constraints
        curr_constraints = set(current.get("unique_constraints", []))
        prev_constraints = set(previous.get("unique_constraints", []))

        added_constraints = list(curr_constraints - prev_constraints)
        removed_constraints = list(prev_constraints - curr_constraints)

        return {
            "agent_shifts": agent_shifts,
            "strategy_changes": strategy_shifts,
            "added_constraints": added_constraints,
            "removed_constraints": removed_constraints
        }

    def _empty_stats(self) -> Dict[str, Any]:
        return {
            "sample_size": 0,
            "agent_dominance": {},
            "strategy_frequency": {},
            "active_constraints": {},
            "unique_constraints": [],
            "sizing_authority": {}
        }
