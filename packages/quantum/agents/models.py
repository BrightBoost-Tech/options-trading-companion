from pydantic import BaseModel
from typing import Dict, Any, Optional

class AgentSignal(BaseModel):
    agent_id: str
    signal: str = "neutral"
    veto: bool = False
    score: float = 0.5
    constraints: Dict[str, Any] = {}
    reason: str = ""
