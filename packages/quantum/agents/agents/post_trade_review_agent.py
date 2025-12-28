from typing import Dict, Any, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class PostTradeReviewAgent(BaseQuantAgent):
    """
    Agent responsible for analyzing closed trades to generate review artifacts
    for the learning loop.
    """

    @property
    def id(self) -> str:
        return "post_trade_review"

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Context inputs:
        - realized_pnl: float
        - mfe: float (Maximum Favorable Excursion)
        - mae: float (Maximum Adverse Excursion)
        - agent_signals: Optional[Dict[str, Any]] (snapshot of entry signals)

        Outputs (in metadata):
        - review.outcome: str ("WIN", "LOSS", "SCRATCH")
        - review.primary_cause: str
        - review.lessons: str
        """
        realized_pnl = float(context.get("realized_pnl", 0.0))
        mfe = float(context.get("mfe", 0.0))
        mae = float(context.get("mae", 0.0))
        entry_signals = context.get("agent_signals", {}) or {}

        # Determine Outcome
        if realized_pnl > 0:
            outcome = "WIN"
        elif realized_pnl < 0:
            outcome = "LOSS"
        else:
            outcome = "SCRATCH"

        primary_cause = "Unknown"
        lessons = "None"
        reasons = []

        if outcome == "WIN":
            primary_cause = "Strategy Alignment"
            lessons = "Trade thesis validated by market action."
            if mae < -0.5 * realized_pnl: # Just a heuristic, usually MAE is negative PnL wise?
                # Assuming MAE is typically a negative number representing draw-down relative to entry
                # Wait, MFE/MAE are usually absolute distances or PnL values.
                # Let's assume PnL units. MFE is positive max PnL, MAE is negative max PnL.
                pass

        elif outcome == "LOSS":
            # Heuristics for Loss Analysis

            # 1. Did we have a chance to profit?
            # If MFE was significant (e.g. > 50% of the loss magnitude)
            loss_mag = abs(realized_pnl)

            if mfe > (loss_mag * 0.5):
                primary_cause = "Missed Exit / Greed"
                lessons = "Review profit taking targets. Market gave an opportunity that was not captured."

            # 2. Was it a bad entry? (Immediate drawdown)
            # If MAE is roughly equal to Loss and MFE is near 0
            elif mfe < (loss_mag * 0.1):
                primary_cause = "Bad Entry / Timing"
                lessons = "Entry immediately went against position. Improve entry filters or wait for confirmation."

            # 3. Was confidence low at entry?
            elif entry_signals:
                # Check for low scores in entry signals
                low_score_agents = [k for k, v in entry_signals.items() if isinstance(v, dict) and v.get("score", 100) < 60]
                if low_score_agents:
                     primary_cause = f"Low Conviction Entry ({', '.join(low_score_agents)})"
                     lessons = "Adhere strictly to high-conviction setups."
                else:
                    primary_cause = "Market Reversal"
                    lessons = "Thesis failed due to market shift. Stop loss protected capital."
            else:
                primary_cause = "Market Reversal"
                lessons = "Standard stop loss. Validate if thesis was invalidated earlier."

        elif outcome == "SCRATCH":
            primary_cause = "Breakeven Stop / Churn"
            lessons = "Capital preserved. Review if trade had potential."

        review_artifacts = {
            "review.outcome": outcome,
            "review.primary_cause": primary_cause,
            "review.lessons": lessons
        }

        reasons.append(f"Classified as {outcome} due to PnL {realized_pnl}")
        reasons.append(f"Attributed to: {primary_cause}")

        return AgentSignal(
            agent_id=self.id,
            score=100.0,
            veto=False,
            reasons=reasons,
            metadata=review_artifacts
        )
