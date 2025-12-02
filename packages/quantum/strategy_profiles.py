from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

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
