import os
from datetime import datetime, date
from typing import Dict, Any, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class EventRiskAgent(BaseQuantAgent):
    @property
    def id(self) -> str:
        return "event_risk"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.lookahead_days = int(os.environ.get("QUANT_AGENT_EVENT_LOOKAHEAD_DAYS", "7"))
        self.veto_days = int(os.environ.get("QUANT_AGENT_EVENT_VETO_DAYS", "1"))

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        earnings_date_str = context.get("earnings_date")

        # If earnings_date is not directly provided, try to look it up in the map
        if not earnings_date_str:
            symbol = context.get("symbol")
            earnings_map = context.get("earnings_map", {})
            if symbol and earnings_map:
                earnings_date_str = earnings_map.get(symbol)

        if not earnings_date_str:
            return AgentSignal(
                agent_id=self.id,
                score=50.0,
                veto=False,
                reasons=["No earnings data found"],
                metadata={}
            )

        try:
            # Handle YYYY-MM-DD format
            if isinstance(earnings_date_str, (date, datetime)):
                 event_date = earnings_date_str
                 if isinstance(event_date, datetime):
                     event_date = event_date.date()
            else:
                event_date = datetime.strptime(str(earnings_date_str), "%Y-%m-%d").date()

            today = date.today()
            days_to_event = (event_date - today).days

            # Constraints dict
            constraints = {
                "event.is_event_window": False,
                "event.days_to_event": days_to_event,
                "event.require_defined_risk": False,
                "event.avoid_new_positions": False,
                "event.max_dte": None
            }

            # Logic
            if days_to_event < 0:
                # Event passed
                 return AgentSignal(
                    agent_id=self.id,
                    score=80.0, # Safe
                    veto=False,
                    reasons=["Event passed"],
                    metadata={"constraints": constraints}
                )

            if days_to_event <= self.lookahead_days:
                constraints["event.is_event_window"] = True

                if days_to_event <= self.veto_days:
                    return AgentSignal(
                        agent_id=self.id,
                        score=0.0,
                        veto=True,
                        reasons=[f"Earnings imminent in {days_to_event} days"],
                        metadata={"constraints": constraints}
                    )
                else:
                    # Within lookahead but not veto
                    constraints["event.require_defined_risk"] = True
                    constraints["event.avoid_new_positions"] = False

                    return AgentSignal(
                        agent_id=self.id,
                        score=40.0, # Caution
                        veto=False,
                        reasons=[f"Earnings approaching in {days_to_event} days"],
                        metadata={"constraints": constraints}
                    )

            # Outside lookahead
            return AgentSignal(
                agent_id=self.id,
                score=90.0,
                veto=False,
                reasons=["Earnings far out"],
                metadata={"constraints": constraints}
            )

        except ValueError:
             return AgentSignal(
                agent_id=self.id,
                score=50.0,
                veto=False,
                reasons=["Invalid earnings date format"],
                metadata={}
            )
        except Exception as e:
             return AgentSignal(
                agent_id=self.id,
                score=50.0,
                veto=False,
                reasons=[f"Error parsing date: {str(e)}"],
                metadata={}
            )
