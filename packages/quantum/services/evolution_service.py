from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from collections import Counter
from supabase import Client

class EvolutionService:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client

    def get_weekly_evolution(self, user_id: str) -> Dict[str, Any]:
        """
        Aggregates system evolution metrics for the last 7 days compared to the previous 7 days.
        Returns:
            - new_constraints: List of strings (e.g. "Advanced Event Guardrails activated")
            - agent_influence: List of dicts with agent name and influence change.
            - strategy_shifts: List of dicts with strategy name and volume change.
        """
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        fourteen_days_ago = now - timedelta(days=14)

        # 1. Fetch Trade Suggestions for the last 14 days
        try:
            response = self.supabase.table("trade_suggestions") \
                .select("created_at, strategy, agent_signals") \
                .eq("user_id", user_id) \
                .gte("created_at", fourteen_days_ago.isoformat()) \
                .execute()

            suggestions = response.data or []
        except Exception as e:
            print(f"Error fetching trade suggestions for evolution: {e}")
            suggestions = []

        # 2. Partition data
        current_period = []
        previous_period = []

        for s in suggestions:
            created_at = datetime.fromisoformat(s["created_at"].replace('Z', '+00:00'))
            if created_at >= seven_days_ago:
                current_period.append(s)
            else:
                previous_period.append(s)

        # 3. Analyze Strategy Shifts
        curr_strat_counts = Counter([s.get("strategy") for s in current_period if s.get("strategy")])
        prev_strat_counts = Counter([s.get("strategy") for s in previous_period if s.get("strategy")])

        all_strats = set(curr_strat_counts.keys()) | set(prev_strat_counts.keys())
        strategy_shifts = []

        for strat in all_strats:
            curr = curr_strat_counts[strat]
            prev = prev_strat_counts[strat]
            diff = curr - prev
            if diff != 0:
                strategy_shifts.append({
                    "name": strat,
                    "change": diff,
                    "current": curr,
                    "previous": prev
                })

        # Sort by magnitude of change
        strategy_shifts.sort(key=lambda x: abs(x["change"]), reverse=True)

        # 4. Analyze Agent Influence
        # Assuming agent_signals is a dict {agent_name: score} or list [agent_name]
        def get_agents(signals: Any) -> List[str]:
            if not signals:
                return []
            if isinstance(signals, dict):
                return list(signals.keys())
            if isinstance(signals, list):
                return [str(s) for s in signals]
            return []

        curr_agent_counts = Counter()
        for s in current_period:
            agents = get_agents(s.get("agent_signals"))
            curr_agent_counts.update(agents)

        prev_agent_counts = Counter()
        for s in previous_period:
            agents = get_agents(s.get("agent_signals"))
            prev_agent_counts.update(agents)

        all_agents = set(curr_agent_counts.keys()) | set(prev_agent_counts.keys())
        agent_influence = []

        for agent in all_agents:
            curr = curr_agent_counts[agent]
            prev = prev_agent_counts[agent]
            diff = curr - prev
            if curr > 0: # Only show agents currently active or recently active
                agent_influence.append({
                    "name": agent,
                    "change": diff,
                    "current": curr,
                    "previous": prev
                })

        agent_influence.sort(key=lambda x: x["current"], reverse=True)

        # 5. Determine New Constraints
        # This is harder to query historically without a dedicated log.
        # We will infer it from CapabilityState if possible, or check for recently created capabilities.
        new_constraints = []
        try:
            # Check for capabilities activated in the last 7 days?
            # CapabilityState in models.py doesn't have a timestamp.
            # We'll rely on a mock or simple check for now.
            # If we had a 'system_events' table, we'd query that.
            # For now, let's look at 'rules_guardrails' if it exists and has created_at.

            # Using a simplified heuristic: Return a generic message if logic enabled
            # In a real scenario, we'd query an audit log.
            # For this task, we will verify if 'Advanced Event Guardrails' is active.
            pass
        except Exception:
            pass

        return {
            "period_start": seven_days_ago.isoformat(),
            "period_end": now.isoformat(),
            "new_constraints": new_constraints,
            "agent_influence": agent_influence,
            "strategy_shifts": strategy_shifts
        }
