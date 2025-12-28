from typing import Dict, Any
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class ExitPlanAgent(BaseQuantAgent):
    """
    Agent responsible for generating deterministic exit parameters based on strategy type.
    """

    @property
    def id(self) -> str:
        return "exit_plan"

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Context inputs:
        - strategy_type: str (e.g., "IRON CONDOR", "LONG CALL")

        Outputs (in metadata):
        - exit.profit_take_pct: float
        - exit.stop_loss_pct: float
        - exit.time_stop_days: int
        """
        strategy_type = str(context.get("strategy_type", "UNKNOWN")).upper()

        # Defaults
        profit_take_pct = 0.50
        stop_loss_pct = 1.00
        time_stop_days = 30

        reasons = []

        # Logic based on strategy family
        if any(s in strategy_type for s in ["CREDIT", "CONDOR", "SHORT"]):
            # Credit strategies (Short volatility)
            profit_take_pct = 0.50
            stop_loss_pct = 2.00  # 2x credit received
            time_stop_days = 45
            reasons.append(f"Strategy {strategy_type} mapped to Credit/Short Volatility template")

        elif any(s in strategy_type for s in ["DEBIT", "VERTICAL"]):
            # Debit Spreads (Defined risk directional)
            profit_take_pct = 0.50
            stop_loss_pct = 0.50
            time_stop_days = 45
            reasons.append(f"Strategy {strategy_type} mapped to Debit Spread template")

        elif any(s in strategy_type for s in ["LONG", "BUY"]):
            # Long Options (Long volatility/Directional)
            profit_take_pct = 1.00
            stop_loss_pct = 0.50
            time_stop_days = 30
            reasons.append(f"Strategy {strategy_type} mapped to Long Option template")

        else:
            reasons.append(f"Unknown strategy {strategy_type}, applying default template")

        exit_plan = {
            "exit.profit_take_pct": profit_take_pct,
            "exit.stop_loss_pct": stop_loss_pct,
            "exit.time_stop_days": time_stop_days
        }

        return AgentSignal(
            agent_id=self.id,
            score=100.0,  # Deterministic, always valid
            veto=False,
            reasons=reasons,
            metadata=exit_plan
        )
