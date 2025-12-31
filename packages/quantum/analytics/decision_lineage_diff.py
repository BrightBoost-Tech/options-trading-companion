from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict

class DecisionLineage(BaseModel):
    """
    Represents the decision trace for a single symbol/strategy over a time step.
    This structure is designed to capture the inputs and outputs of the strategy selection
    and optimization process to allow for diffing and drift detection.
    """
    trace_id: str
    timestamp: str  # ISO 8601
    symbol: str
    strategy_name: str

    # Input Context
    regime: str  # e.g., "NORMAL", "SHOCK"
    iv_rank: float
    sentiment: str

    # Internal Logic State
    active_constraints: List[str] = []
    agent_scores: Dict[str, float] = {}  # e.g. {"trend": 0.8, "volatility": 0.2}

    # Outcome
    selected_strategy: str # The final strategy chosen (might differ from strategy_name if fallback)
    fallback_reason: Optional[str] = None

    model_config = ConfigDict(frozen=True) # Make it hashable/immutable for easier comparison

def diff_lineage(old: DecisionLineage, new: DecisionLineage) -> Dict[str, Any]:
    """
    Compares two decision lineages and returns a dictionary of differences.
    Detects:
    - Added / removed constraints
    - Agent dominance change
    - Strategy fallback change

    The output is deterministic and order-independent.
    """
    diffs = {}

    # 1. Added / Removed Constraints
    old_constraints = set(old.active_constraints)
    new_constraints = set(new.active_constraints)

    added_constraints = sorted(list(new_constraints - old_constraints))
    removed_constraints = sorted(list(old_constraints - new_constraints))

    if added_constraints:
        diffs["constraints_added"] = added_constraints
    if removed_constraints:
        diffs["constraints_removed"] = removed_constraints

    # 2. Agent Dominance Change
    # Dominant agent is the one with the highest score.
    # We only report if the dominant agent changes.

    def get_dominant_agent(scores: Dict[str, float]) -> Optional[str]:
        if not scores:
            return None
        # Sort by score desc, then name asc for determinism
        sorted_agents = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return sorted_agents[0][0]

    old_dominant = get_dominant_agent(old.agent_scores)
    new_dominant = get_dominant_agent(new.agent_scores)

    if old_dominant != new_dominant:
        diffs["agent_dominance_change"] = {
            "from": old_dominant,
            "to": new_dominant
        }

    # 3. Strategy Fallback Change
    # A fallback happens if selected_strategy != strategy_name.
    # We detect if the fallback state or reason has changed.

    old_is_fallback = old.selected_strategy != old.strategy_name
    new_is_fallback = new.selected_strategy != new.strategy_name

    if old_is_fallback != new_is_fallback:
         diffs["fallback_status_change"] = {
            "from": old_is_fallback,
            "to": new_is_fallback
        }
    elif old_is_fallback and new_is_fallback:
        # Both are fallbacks, check if the actual strategy or reason changed
        if old.selected_strategy != new.selected_strategy:
             diffs["fallback_strategy_change"] = {
                "from": old.selected_strategy,
                "to": new.selected_strategy
            }

        if old.fallback_reason != new.fallback_reason:
             diffs["fallback_reason_change"] = {
                "from": old.fallback_reason,
                "to": new.fallback_reason
            }

    return diffs
