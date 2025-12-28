import os
from datetime import datetime, date
from typing import Dict, Any, Optional
from packages.quantum.agents.models import AgentSignal

class EventRiskAgent:
    def __init__(self):
        self.agent_id = "event_risk"
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
                agent_id=self.agent_id,
                signal="neutral",
                score=0.5,
                reason="No earnings data found"
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
                    agent_id=self.agent_id,
                    signal="neutral",
                    score=0.5,
                    reason="Event passed",
                    constraints=constraints
                )

            if days_to_event <= self.lookahead_days:
                constraints["event.is_event_window"] = True

                if days_to_event <= self.veto_days:
                    return AgentSignal(
                        agent_id=self.agent_id,
                        signal="veto",
                        veto=True,
                        score=0.0,
                        reason=f"Earnings imminent in {days_to_event} days",
                        constraints=constraints
                    )
                else:
                    # Within lookahead but not veto
                    constraints["event.require_defined_risk"] = True
                    constraints["event.avoid_new_positions"] = False # Default per instructions "avoid_new_positions (maybe)" - sticking to prompt logic
                    # Prompt says: "If earnings in 3 days -> require_defined_risk true, veto false (default)"
                    # Maybe set max_dte to days_to_event? The prompt lists it as a constraint but doesn't specify logic.
                    # I'll leave max_dte as None unless logic dictates otherwise.
                    # Usually you want options to expire *after* earnings if you are playing it, or *before* if avoiding.
                    # Given "Event Risk Agent", implies avoiding risk. So maybe max_dte should be days_to_event - 1?
                    # But prompt just says "Output constraints like...".
                    # I will stick to "require_defined_risk" as the main one requested in the example.

                    return AgentSignal(
                        agent_id=self.agent_id,
                        signal="caution",
                        veto=False,
                        score=0.4, # Lower score for risk? Or neutral?
                        # "If earnings in 3 days -> require_defined_risk true, veto false (default)"
                        # "If no earnings data -> neutral signal (score ~0.5–0.7)"
                        # So caution might be lower or just tagged. I'll use 0.4.
                        reason=f"Earnings approaching in {days_to_event} days",
                        constraints=constraints
                    )

            # Outside lookahead
            return AgentSignal(
                agent_id=self.agent_id,
                signal="neutral",
                score=0.7,
                reason="Earnings far out",
                constraints=constraints
            )

        except ValueError:
             return AgentSignal(
                agent_id=self.agent_id,
                signal="neutral",
                score=0.5,
                reason="Invalid earnings date format"
            )
        except Exception as e:
             return AgentSignal(
                agent_id=self.agent_id,
                signal="neutral",
                score=0.5,
                reason=f"Error parsing date: {str(e)}"
            )
