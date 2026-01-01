from typing import List, Dict, Any, Optional

class DecisionLineageBuilder:
    """
    Helper class to build a structured snapshot of the decision-making process for trade suggestions.
    Ensures deterministic output for comparison across time.
    """
    def __init__(self):
        self.agents_involved: List[Dict[str, Any]] = []
        self.vetoed_agents: List[Dict[str, Any]] = []
        self.active_constraints: Dict[str, Any] = {}
        self.strategy_chosen: str = "unknown"
        self.sizing_source: str = "unknown"
        self.fallback_reason: Optional[str] = None

    def add_agent(self, agent_name: str, score: Optional[float] = None, metadata: Optional[Dict[str, Any]] = None):
        """Records an agent that participated in the decision."""
        # Check if already added to avoid duplicates, update if exists
        existing = next((a for a in self.agents_involved if a["name"] == agent_name), None)
        if existing:
            if score is not None:
                existing["score"] = score
            if metadata is not None:
                existing["metadata"] = metadata
        else:
            entry = {"name": agent_name}
            if score is not None:
                entry["score"] = score
            if metadata is not None:
                entry["metadata"] = metadata
            self.agents_involved.append(entry)

    def mark_veto(self, agent_name: str, reason: Optional[str] = None):
        """Records an agent that vetoed the trade."""
        # Ensure it's in involved list
        self.add_agent(agent_name)

        existing = next((a for a in self.vetoed_agents if a["name"] == agent_name), None)
        if not existing:
            entry = {"name": agent_name}
            if reason:
                entry["reason"] = reason
            self.vetoed_agents.append(entry)

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
        # Sort agents by name
        sorted_agents = sorted(self.agents_involved, key=lambda x: x["name"])
        sorted_vetoes = sorted(self.vetoed_agents, key=lambda x: x["name"])

        # Sort constraints by key to ensure deterministic output
        sorted_constraints = dict(sorted(self.active_constraints.items()))

        return {
            "agents_involved": sorted_agents,
            "vetoed_agents": sorted_vetoes,
            "active_constraints": sorted_constraints,
            "strategy_chosen": self.strategy_chosen,
            "sizing_source": self.sizing_source,
            "fallback_reason": self.fallback_reason
        }
