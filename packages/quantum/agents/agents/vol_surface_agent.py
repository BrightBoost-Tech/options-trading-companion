from typing import Dict, Any, List
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class VolSurfaceAgent(BaseQuantAgent):
    """
    Agent responsible for detecting Volatility Regime and setting bias constraints.
    """

    @property
    def id(self) -> str:
        return "vol_surface"

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        iv_rank = context.get("iv_rank")

        reasons = []
        veto = False
        score = 100.0
        metadata = {}

        if iv_rank is None:
            score = 50.0 # Neutral score for missing data
            reasons.append("Missing iv_rank in context")
            # Default to neutral if data missing
            metadata["vol.bias"] = "neutral"
            metadata["vol.require_defined_risk"] = False
        else:
            try:
                iv_rank_val = float(iv_rank)

                if iv_rank_val >= 60:
                    bias = "sell_premium"
                    require_defined_risk = True
                    reasons.append(f"High IV Rank ({iv_rank_val}) detected")
                elif iv_rank_val <= 30:
                    bias = "buy_premium"
                    require_defined_risk = False
                    reasons.append(f"Low IV Rank ({iv_rank_val}) detected")
                else:
                    bias = "neutral"
                    require_defined_risk = False
                    reasons.append(f"Neutral IV Rank ({iv_rank_val}) detected")

                metadata["vol.bias"] = bias
                metadata["vol.require_defined_risk"] = require_defined_risk

            except (ValueError, TypeError):
                score = 50.0
                reasons.append(f"Invalid iv_rank value: {iv_rank}")
                metadata["vol.bias"] = "neutral"
                metadata["vol.require_defined_risk"] = False

        return AgentSignal(
            agent_id=self.id,
            score=score,
            veto=veto,
            reasons=reasons,
            metadata=metadata
        )
