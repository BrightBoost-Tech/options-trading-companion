from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

class StrategyConfig(BaseModel):
    name: str
    version: int
    description: Optional[str] = None

    regime_whitelist: List[str] = Field(default_factory=list)
    conviction_floor: float
    conviction_slope: float

    max_risk_pct_per_trade: float
    max_risk_pct_portfolio: float
    max_concurrent_positions: int

    max_spread_bps: int
    max_days_to_expiry: int
    min_underlying_liquidity: float

    take_profit_pct: float
    stop_loss_pct: float
    max_holding_days: int

class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    ticker: str
    param_grid: Optional[Dict[str, List[Any]]] = None

class CostModelConfig(BaseModel):
    commission_per_contract: float = 0.65
    min_fee: float = 0.0
    spread_slippage_bps: int = 5
    fill_probability_model: Literal["conservative", "optimistic", "neutral"] = "neutral"

class WalkForwardConfig(BaseModel):
    train_days: int
    test_days: int
    step_days: int
    warmup_days: int = 0
    embargo_days: int = 0
    min_trades_per_fold: int = 5

class ParamSearchConfig(BaseModel):
    method: Literal["grid", "random"]
    n_samples: Optional[int] = None
    seed: Optional[int] = None
    space: Optional[Dict[str, Any]] = None

class BacktestRequestV3(BacktestRequest):
    engine_version: Literal["v3"] = "v3"
    run_mode: Literal["single", "walk_forward"]
    walk_forward: Optional[WalkForwardConfig] = None
    param_search: Optional[ParamSearchConfig] = None
    cost_model: CostModelConfig
    seed: int = 42
    initial_equity: float = 100000.0
