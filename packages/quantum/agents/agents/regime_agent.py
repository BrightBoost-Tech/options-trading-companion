from typing import Dict, Any, List, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal
from packages.quantum.common_enums import RegimeState

class RegimeAgent(BaseQuantAgent):
    """
    Agent responsible for translating market regime and trend data into risk constraints and scoring.
    """

    @property
    def id(self) -> str:
        return "regime_agent"

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Evaluate market regime context.

        Expected context keys:
        - effective_regime: str (RegimeState value)
        - trend_strength: float (e.g., -1.0 to 1.0)
        - volatility_flags: List[str]
        """

        # 1. Extract and Validate Inputs
        raw_regime = context.get("effective_regime", "normal")
        trend_strength = float(context.get("trend_strength", 0.0))
        vol_flags = context.get("volatility_flags", [])

        # Normalize regime
        try:
            regime = RegimeState(raw_regime.lower()) if isinstance(raw_regime, str) else raw_regime
        except ValueError:
            regime = RegimeState.NORMAL

        # 2. Determine Bias from Trend
        # Assumption: trend_strength is signed (-1.0 to 1.0)
        # > 0.1: Bullish, < -0.1: Bearish, else Neutral
        bias = "neutral"
        if trend_strength > 0.1:
            bias = "bullish"
        elif trend_strength < -0.1:
            bias = "bearish"

        # 3. Determine Constraints & Base Score
        allow_new_risk = True
        base_score = 50.0

        if regime == RegimeState.SHOCK:
            allow_new_risk = False
            base_score = 0.0
            bias = "neutral" # Force neutral/defensive in shock

        elif regime == RegimeState.ELEVATED:
            allow_new_risk = True
            base_score = 70.0

        elif regime == RegimeState.NORMAL:
            allow_new_risk = True
            base_score = 90.0

        elif regime == RegimeState.SUPPRESSED:
            allow_new_risk = True
            base_score = 95.0

        elif regime == RegimeState.REBOUND:
            allow_new_risk = True
            base_score = 60.0

        elif regime == RegimeState.CHOP:
            allow_new_risk = True # Maybe allowed but tricky
            base_score = 50.0
            bias = "neutral" # Chop implies no clear trend

        # 4. Apply Penalties
        # Penalize for volatility flags
        penalty = len(vol_flags) * 10.0
        final_score = max(0.0, min(100.0, base_score - penalty))

        # 5. Construct Metadata
        constraints = {
            "regime.state": regime.value,
            "regime.allow_new_risk": allow_new_risk,
            "regime.bias": bias
        }

        # 6. Return Signal
        reasons = [f"Regime is {regime.value}"]
        if vol_flags:
            reasons.append(f"Volatility flags: {', '.join(vol_flags)}")
        if not allow_new_risk:
            reasons.append("New risk blocked by regime")

        # Veto if shock or score is very low
        veto = (regime == RegimeState.SHOCK) or (final_score < 20.0)

        return AgentSignal(
            agent_id=self.id,
            score=final_score,
            veto=veto,
            reasons=reasons,
            metadata={"constraints": constraints}
        )
