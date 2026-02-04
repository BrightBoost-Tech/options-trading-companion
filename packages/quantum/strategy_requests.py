from typing import List, Optional
from pydantic import BaseModel

class BatchSimulationRequest(BaseModel):
    strategy_name: str
    start_date: str
    end_date: str
    ticker: str
    seed: Optional[int] = None
    # Add other necessary fields

class ResearchCompareRequest(BaseModel):
    baseline_backtest_id: str
    candidate_backtest_id: str
    metric_list: List[str]
    bootstrap_samples: int = 1000
    seed: int = 42
