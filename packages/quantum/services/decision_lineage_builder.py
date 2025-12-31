from typing import List, Dict, Any, Optional

class DecisionLineageBuilder:
    """
    Helper class to build a structured snapshot of the decision-making process for trade suggestions.
    Ensures deterministic output for comparison across time.
    """
    def __init__(self):
        self.agents_involved: List[str] = []
        self.vetoed_agents: List[str] = []
        self.active_constraints: Dict[str, Any] = {}
        self.strategy_chosen: str = "unknown"
        self.sizing_source: str = "unknown"
        self.fallback_reason: Optional[str] = None

    def add_agent(self, agent_name: str):
        """Records an agent that participated in the decision."""
        if agent_name not in self.agents_involved:
            self.agents_involved.append(agent_name)

    def mark_veto(self, agent_name: str):
        """Records an agent that vetoed the trade."""
        self.add_agent(agent_name)
        if agent_name not in self.vetoed_agents:
            self.vetoed_agents.append(agent_name)

    def set_strategy(self, strategy: str):
        """Sets the strategy chosen."""
        self.strategy_chosen = strategy

    def set_sizing_source(self, source: str):
        """Sets the source of sizing (e.g. 'SizingAgent', 'Classic')."""
        self.sizing_source = source

    def add_constraint(self, key: str, value: Any):
        """Adds a constraint active during the decision."""
        self.active_constraints[key] = value

    def set_fallback(self, reason: str):
        """Sets the fallback reason if a primary mechanism failed."""
        self.fallback_reason = reason

    def build(self) -> Dict[str, Any]:
        """
        Builds the compact, deterministic lineage object.
        Returns a dictionary suitable for JSON serialization.
        """
        # Sort constraints by key to ensure deterministic output
        sorted_constraints = dict(sorted(self.active_constraints.items()))

        return {
            "agents_involved": sorted(self.agents_involved),
            "vetoed_agents": sorted(self.vetoed_agents),
            "active_constraints": sorted_constraints,
            "strategy_chosen": self.strategy_chosen,
            "sizing_source": self.sizing_source,
            "fallback_reason": self.fallback_reason
        }
