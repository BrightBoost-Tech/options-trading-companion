from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator
import math

class CandidateTrade(BaseModel):
    id: str
    symbol: str
    side: Literal['buy', 'sell']
    qty_max: int = Field(..., ge=0)
    ev_per_unit: float
    premium_per_unit: float
    delta: float
    gamma: float
    vega: float
    tail_risk_contribution: float
    metadata: Optional[Dict[str, Any]] = None

    @field_validator('ev_per_unit', 'premium_per_unit', 'delta', 'gamma', 'vega', 'tail_risk_contribution')
    @classmethod
    def check_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Values must be finite (no NaN or Inf)")
        return v

class DiscreteConstraints(BaseModel):
    max_cash: float
    max_vega: float
    max_delta_abs: float
    target_delta: Optional[float] = None
    max_gamma: float
    max_contracts: Optional[int] = None

    @field_validator('max_cash', 'max_vega', 'max_delta_abs', 'target_delta', 'max_gamma')
    @classmethod
    def check_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError("Values must be finite (no NaN or Inf)")
        return v

class DiscreteParameters(BaseModel):
    lambda_tail: float
    lambda_cash: float
    lambda_vega: float
    lambda_delta: float
    lambda_gamma: float
    num_samples: int = Field(20, gt=0)
    relaxation_schedule: Optional[int] = None
    mode: Literal['hybrid', 'classical_only', 'quantum_only']
    trial_mode: Optional[bool] = None
    max_candidates_for_dirac: int = Field(40, gt=0)
    max_dirac_calls: int = Field(2, gt=0)
    dirac_timeout_s: int = Field(10, gt=0)

    @field_validator('lambda_tail', 'lambda_cash', 'lambda_vega', 'lambda_delta', 'lambda_gamma')
    @classmethod
    def check_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Values must be finite (no NaN or Inf)")
        return v

class DiscreteSolveRequest(BaseModel):
    candidates: List[CandidateTrade]
    constraints: DiscreteConstraints
    parameters: DiscreteParameters

class SelectedTrade(BaseModel):
    id: str
    qty: int
    reason: str

class DiscreteSolveMetrics(BaseModel):
    expected_profit: float
    total_premium: float
    tail_risk_value: float
    delta: float
    gamma: float
    vega: float
    objective_value: float
    runtime_ms: float

    @field_validator('expected_profit', 'total_premium', 'tail_risk_value', 'delta', 'gamma', 'vega', 'objective_value', 'runtime_ms')
    @classmethod
    def check_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Values must be finite (no NaN or Inf)")
        return v

class DiscreteSolveResponse(BaseModel):
    status: str
    strategy_used: Literal['dirac3', 'classical']
    selected_trades: List[SelectedTrade]
    metrics: DiscreteSolveMetrics
    diagnostics: Dict[str, Any]
