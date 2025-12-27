from pydantic import BaseModel, Field
from typing import List, Dict, Any
from abc import ABC, abstractmethod

class AgentSignal(BaseModel):
    agent_id: str
    score: float = Field(..., ge=0, le=100, description="0-100 score where 100 is best")
    veto: bool = Field(False, description="If True, this agent blocks the trade regardless of score")
    reasons: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BaseQuantAgent(ABC):
    """
    Base class for all Quant Agents.
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for the agent."""
        pass

    @abstractmethod
    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Evaluate the trade context and return a signal.
        Context is expected to contain 'legs' and other trade details.
        """
        pass
