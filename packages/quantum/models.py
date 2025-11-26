from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Holding(BaseModel):
    symbol: str
    name: Optional[str] = None
    quantity: float
    cost_basis: float
    current_price: float
    currency: Optional[str] = "USD"
    institution_name: Optional[str] = None
    source: Optional[str] = "manual"
    account_id: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)
