from typing import Dict, List, Any
from datetime import datetime, timedelta
from supabase import Client

class EvolutionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_system_evolution(self, user_id: str) -> Dict[str, Any]:
        """
        Aggregates system changes over the last 7 days.
        """
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        fourteen_days_ago = now - timedelta(days=14)

        # 1. New Constraints Activated
        # Query risk_budget_policies created in last 7 days
        constraints = []
        try:
            res = self.supabase.table("risk_budget_policies")\
                .select("*")\
                .eq("user_id", user_id)\
                .gte("created_at", seven_days_ago.isoformat())\
                .order("created_at", desc=True)\
                .execute()

            # If a policy was created, it implies constraints changed/activated
            for policy in res.data:
                # We can try to extract meaningful names or just use "Risk Policy Updated"
                # If policy_json has keys like "max_drawdown", we can list them.
                p_json = policy.get("policy_json", {})

                if p_json.get("max_drawdown_pct"):
                    constraints.append(f"Max Drawdown Limit: {p_json['max_drawdown_pct']}%")

                if p_json.get("max_position_size"):
                     constraints.append(f"Position Size Cap: {p_json['max_position_size']}")

                if not constraints:
                     constraints.append("Risk Policy Updated")
        except Exception as e:
            print(f"[EvolutionService] Error fetching constraints: {e}")


        # 2. Agents with Increased Influence
        # Query model_states updated in last 7 days.
        # Ideally check if weights increased, but we only have current snapshot in 'model_states'.
        # However, 'model_states' has 'last_updated'.
        agents = []
        try:
            res = self.supabase.table("model_states")\
                .select("*")\
                .gte("last_updated", seven_days_ago.isoformat())\
                .execute()

            for model in res.data:
                scope = model.get("scope", "Global")
                version = model.get("model_version", "v1")
                # We assume any update implies active influence or refinement
                agents.append(f"{scope} Adapter ({version})")
        except Exception as e:
            print(f"[EvolutionService] Error fetching agents: {e}")

        # 3. Strategies Reduced or Expanded
        # Compare count of suggestions by strategy_type in [now-7d, now] vs [now-14d, now-7d]
        strategies_expanded = []
        strategies_reduced = []

        try:
            # Current Period
            res_curr = self.supabase.table("trade_suggestions")\
                .select("strategy")\
                .eq("user_id", user_id)\
                .gte("created_at", seven_days_ago.isoformat())\
                .execute()

            # Previous Period
            res_prev = self.supabase.table("trade_suggestions")\
                .select("strategy")\
                .eq("user_id", user_id)\
                .lt("created_at", seven_days_ago.isoformat())\
                .gte("created_at", fourteen_days_ago.isoformat())\
                .execute()

            counts_curr = {}
            for row in res_curr.data:
                s = row.get("strategy") or "unknown"
                counts_curr[s] = counts_curr.get(s, 0) + 1

            counts_prev = {}
            for row in res_prev.data:
                s = row.get("strategy") or "unknown"
                counts_prev[s] = counts_prev.get(s, 0) + 1

            # Compare
            all_strats = set(counts_curr.keys()) | set(counts_prev.keys())
            for s in all_strats:
                c = counts_curr.get(s, 0)
                p = counts_prev.get(s, 0)

                if c > p:
                    strategies_expanded.append(f"{s} (+{c-p})")
                elif c < p:
                    strategies_reduced.append(f"{s} ({c-p})")

        except Exception as e:
            print(f"[EvolutionService] Error fetching strategy stats: {e}")

        return {
            "constraints_activated": list(set(constraints)), # Dedupe
            "agents_increased_influence": list(set(agents)),
            "strategies_expanded": strategies_expanded,
            "strategies_reduced": strategies_reduced
        }
