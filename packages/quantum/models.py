from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
 
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
    risk_metrics: Optional[Dict[str, Any]] = None
    optimizer_status: Optional[str] = "pending"
    last_optimizer_run_at: Optional[datetime] = None
