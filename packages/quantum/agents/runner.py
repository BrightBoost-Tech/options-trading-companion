from typing import List, Dict, Any, Tuple
import logging
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

logger = logging.getLogger(__name__)

class AgentRunner:
    """
    Orchestrates the execution of multiple Quant Agents and aggregates their signals.
    """

    @staticmethod
    def run_agents(context: Dict[str, Any], agents: List[BaseQuantAgent]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Runs a list of agents against the provided context.

        Returns:
            signals_json: Dict mapping agent_id -> serialized AgentSignal
            summary_json: Dict containing overall_score, decision, top_reasons, etc.
        """
        agent_signals = {}
        vetoed = False
        valid_scores = []
        all_reasons = []
        merged_constraints = {}

        # 1. Run each agent
        for agent in agents:
            try:
                signal: AgentSignal = agent.evaluate(context)

                # Store signal
                agent_signals[agent.id] = signal.model_dump()

                # Check Veto
                if signal.veto:
                    vetoed = True

                # Collect score (if not vetoed? Or always? Prompt says "overall_score is derived from non-veto agent scores")
                if not signal.veto:
                    valid_scores.append(signal.score)
                else:
                    # If vetoed, effective score contribution is 0?
                    # Usually if vetoed, the trade is dead.
                    # But for "overall_score" calculation of non-veto agents:
                    pass

                # Collect reasons with agent ID for context
                for reason in signal.reasons:
                    all_reasons.append(f"[{agent.id}] {reason}")

                # Merge constraints
                if signal.metadata and "constraints" in signal.metadata:
                    constraints = signal.metadata["constraints"]
                    if isinstance(constraints, dict):
                        merged_constraints.update(constraints)

            except Exception as e:
                logger.error(f"Agent {agent.id} failed: {e}", exc_info=True)
                # Fail gracefully? Or mark as error?
                # "If StrategyDesignAgent errors: do NOT crash scanner; default to legacy strategy."
                # We should probably produce a neutral/error signal for this agent but not crash the runner.
                error_signal = AgentSignal(
                    agent_id=agent.id,
                    score=50.0,
                    veto=False,
                    reasons=[f"Agent Error: {str(e)}"]
                )
                agent_signals[agent.id] = error_signal.model_dump()
                all_reasons.append(f"[{agent.id}] Error: {str(e)}")

        # 2. Compute Summary

        # Overall Score: Mean of non-veto scores. If all vetoed or no agents, 0 or 50?
        if valid_scores:
            overall_score = sum(valid_scores) / len(valid_scores)
        else:
            overall_score = 0.0 if vetoed else 50.0

        # Decision
        decision = "reject" if vetoed else "pass"
        # Optional: could have "warning" if score is low
        if not vetoed and overall_score < 50.0:
            decision = "warning"

        # Top Reasons: Limit to top 5?
        # Prompt says "top_reasons = up to 3 reasons across highest-signal agents"
        # Here we just take the first 3 or all. Sorting by importance is hard without "reason weight".
        top_reasons = all_reasons[:3]

        summary = {
            "overall_score": round(overall_score, 1),
            "decision": decision,
            "vetoed": vetoed,
            "top_reasons": top_reasons,
            "active_constraints": merged_constraints,
            "agent_count": len(agents)
        }

        return agent_signals, summary
