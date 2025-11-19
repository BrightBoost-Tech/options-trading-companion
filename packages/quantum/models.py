from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
 
class Holding(BaseModel):
    symbol: str
    name: Optional[str] = None
    quantity: float
    cost_basis: Optional[float] = None
    current_price: float
    currency: str = "USD"
    institution_name: Optional[str] = "Plaid"

class SyncResponse(BaseModel):
    status: str
    count: int
    holdings: List[Holding]
