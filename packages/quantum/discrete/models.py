from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class CandidateTrade(BaseModel):
    id: str
    ev_per_unit: float
    premium_per_unit: float
    tail_risk_contribution: float
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    qty_max: int = 1

class OptimizationParameters(BaseModel):
    lambda_tail: float = 0.0
    lambda_cash: float = 0.0
    lambda_vega: float = 0.0
    lambda_delta: float = 0.0
    lambda_gamma: float = 0.0

class OptimizationConstraints(BaseModel):
    max_cash: Optional[float] = None
    max_vega: Optional[float] = None
    max_delta_abs: Optional[float] = None
    max_gamma: Optional[float] = None
    max_contracts: Optional[int] = None

class DiscreteSolveRequest(BaseModel):
    candidates: List[CandidateTrade]
    parameters: OptimizationParameters = Field(default_factory=OptimizationParameters)
    constraints: OptimizationConstraints = Field(default_factory=OptimizationConstraints)
