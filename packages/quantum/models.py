from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

class SpreadLeg(BaseModel):
    symbol: str
    quantity: float
    strike: float
    expiry: str # YYYY-MM-DD
    type: str  # C or P
    side: str  # long or short
    current_price: Optional[float] = 0.0


class Spread(BaseModel):
    id: str # internal ID, e.g. "KURA 10C/15C" or UUID
    spread_type: str # debit_call, debit_put, credit, iron_condor, vertical, single
    underlying: str
    ticker: str # Display ticker
    legs: List[SpreadLeg]
    net_cost: float
    current_value: float
    delta: Optional[float] = 0.0
    gamma: Optional[float] = 0.0
    vega: Optional[float] = 0.0
    theta: Optional[float] = 0.0
    quantity: float = 1.0

class SpreadPosition(BaseModel):
    id: str  # synthetic id
    user_id: str
    spread_type: Literal["debit_call", "debit_put", "credit_call", "credit_put", "vertical", "iron_condor", "other", "single", "custom", "credit_spread", "debit_spread"]
    underlying: str
    ticker: Optional[str] = None # Display name
    legs: List[Dict[str, Any]]  # [{symbol, quantity, strike, expiry, side}, ...]
    net_cost: float
    current_value: float
    delta: float
    gamma: float
    vega: float
    theta: float
    quantity: float = 1.0

class Holding(BaseModel):
    symbol: str
    name: Optional[str] = None
    quantity: float
    cost_basis: Optional[float] = None
    current_price: float
    currency: str = "USD"
    institution_name: Optional[str] = "Plaid"
    source: str = Field(default="plaid", description="Source of the holding (plaid, robinhood-csv, manual)")
    account_id: Optional[str] = None
    last_updated: Optional[datetime] = None

class SyncResponse(BaseModel):
    status: str
    count: int
    holdings: List[Holding]

class PortfolioSnapshot(BaseModel):
    id: Optional[str] = None
    user_id: str
    created_at: datetime
    snapshot_type: str = "on-sync"
    holdings: List[Dict[str, Any]]
    spreads: Optional[List[SpreadPosition]] = None
    risk_metrics: Optional[Dict[str, Any]] = None
    optimizer_status: Optional[str] = "pending"
    last_optimizer_run_at: Optional[datetime] = None
