import os
import math
from typing import Dict, Any, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class SizingAgent(BaseQuantAgent):
    """
    SizingAgent determines position sizing based on account capital,
    risk milestones, and confluence of other agent signals.
    """

    @property
    def id(self) -> str:
        return "sizing"

    def _get_milestone_limits(self, capital: float) -> tuple[float, float]:
        """
        Returns (min_risk_usd, max_risk_usd) based on capital milestones.
        Configurable via environment variables.
        """
        # Load config or defaults
        # <1000
        m1_min = float(os.getenv("SIZING_MILESTONE_1000_MIN", "10"))
        m1_max = float(os.getenv("SIZING_MILESTONE_1000_MAX", "35"))
        # 1000-5000
        m2_min = float(os.getenv("SIZING_MILESTONE_5000_MIN", "20"))
        m2_max = float(os.getenv("SIZING_MILESTONE_5000_MAX", "75"))
        # 5000-10000
        m3_min = float(os.getenv("SIZING_MILESTONE_10000_MIN", "35"))
        m3_max = float(os.getenv("SIZING_MILESTONE_10000_MAX", "150"))
        # >10000
        m4_min = float(os.getenv("SIZING_MILESTONE_BIG_MIN", "50"))
        m4_max = float(os.getenv("SIZING_MILESTONE_BIG_MAX", "250"))

        if capital < 1000:
            return m1_min, m1_max
        elif capital < 5000:
            return m2_min, m2_max
        elif capital < 10000:
            return m3_min, m3_max
        else:
            return m4_min, m4_max

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Determines sizing constraints.

        Context requires:
        - deployable_capital (float)
        - max_loss_per_contract (float)

        Optional context:
        - base_score (float): The scanner score (0-100). Default 50.
        - agent_signals (Dict[str, AgentSignal] or Dict): Other agent outputs.
        - collateral_required_per_contract (float)
        """
        capital = float(context.get("deployable_capital", 0.0))
        max_loss = float(context.get("max_loss_per_contract", 0.0))
        collateral = float(context.get("collateral_required_per_contract", 0.0)) or max_loss
        base_score = float(context.get("base_score", 50.0))

        # 1. Determine Risk Range
        min_risk, max_risk = self._get_milestone_limits(capital)

        # 2. Calculate Confluence Score
        agent_signals = context.get("agent_signals", {})
        scores = [base_score]

        veto_triggered = False

        if agent_signals:
            for agent_id, signal in agent_signals.items():
                # Signal can be dict or AgentSignal object
                if hasattr(signal, "veto") and signal.veto:
                    veto_triggered = True
                elif isinstance(signal, dict) and signal.get("veto"):
                    veto_triggered = True

                s_val = getattr(signal, "score", None)
                if s_val is None and isinstance(signal, dict):
                    s_val = signal.get("score")

                if s_val is not None:
                    scores.append(float(s_val))

        if veto_triggered:
            return AgentSignal(
                agent_id=self.id,
                score=0,
                veto=True,
                reasons=["Vetoed by another agent"],
                metadata={
                    "constraints": {
                        "sizing.target_risk_usd": 0.0,
                        "sizing.max_risk_usd": 0.0,
                        "sizing.recommended_contracts": 0,
                        "sizing.max_contracts": 0,
                        "sizing.risk_scale_factor": 0.0
                    }
                }
            )

        avg_score = sum(scores) / len(scores) if scores else 50.0

        # 3. Calculate Target Risk
        # Map avg_score (0-100) to range [min_risk, max_risk]
        # score 0 -> min_risk
        # score 100 -> max_risk
        # Use a simple linear interpolation
        scale_factor = max(0.0, min(1.0, avg_score / 100.0))
        target_risk = min_risk + (max_risk - min_risk) * scale_factor

        # 4. Convert to Contracts
        # Safety check: never exceed capital
        safe_risk_cap = capital * 0.95 # Safety buffer
        target_risk = min(target_risk, safe_risk_cap)

        if max_loss <= 0:
            # Undefined risk per contract? Fallback to 1 if safe, else 0
            # If price-based max loss is used, this shouldn't happen for long options.
            # Assuming max_loss is valid. If not, can't size.
            rec_contracts = 0
            reason = "Invalid max_loss_per_contract"
            # Special case: if we want to force at least 1 for tiny accounts/tests?
            # Prompt: "Missing per-contract risk -> recommended_contracts=1 with a reason"
            if max_loss <= 0:
                 rec_contracts = 1
                 reason = "Missing per-contract risk, default to 1"
        else:
            rec_contracts = math.floor(target_risk / max_loss)
            reason = f"Sized by risk ${target_risk:.2f} (score {avg_score:.1f})"

        # 5. Check Collateral/Buying Power
        if collateral > 0:
            max_contracts_bp = math.floor(capital / collateral)
            if rec_contracts > max_contracts_bp:
                rec_contracts = max_contracts_bp
                reason += " | Capped by Buying Power"

        rec_contracts = int(max(0, rec_contracts))

        # Max contracts constraint (hard cap from env or default)
        HARD_MAX = 100
        if rec_contracts > HARD_MAX:
            rec_contracts = HARD_MAX
            reason += " | Capped by global max"

        return AgentSignal(
            agent_id=self.id,
            score=avg_score, # The score reflects the conviction used for sizing
            veto=False,
            reasons=[reason],
            metadata={
                "constraints": {
                    "sizing.target_risk_usd": round(target_risk, 2),
                    "sizing.max_risk_usd": round(max_risk, 2),
                    "sizing.min_risk_usd": round(min_risk, 2),
                    "sizing.recommended_contracts": rec_contracts,
                    "sizing.max_contracts": HARD_MAX,
                    "sizing.risk_scale_factor": round(scale_factor, 2)
                }
            }
        )
