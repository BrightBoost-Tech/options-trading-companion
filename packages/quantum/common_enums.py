from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, Optional, Any

class RegimeState(str, Enum):
    SUPPRESSED = "suppressed"
    NORMAL = "normal"
    ELEVATED = "elevated"
    SHOCK = "shock"
    REBOUND = "rebound"
    CHOP = "chop"

class StrategyType(str, Enum):
    SHORT_PUT_CREDIT_SPREAD = "short_put_credit_spread"
    SHORT_CALL_CREDIT_SPREAD = "short_call_credit_spread"
    IRON_CONDOR = "iron_condor"
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    # 2026-07-16 strategy-identity repair: typed members for the two
    # selector-emitted debit verticals. Before these existed,
    # LossMinimizer.get_strategy_type demoted "LONG_CALL_DEBIT_SPREAD" /
    # "LONG_PUT_DEBIT_SPREAD" to the naked LONG_CALL / LONG_PUT via
    # substring heuristics — a defined-risk spread classified as an
    # uncapped single leg. Additive string members; no existing branch
    # keys on them (verified: zero StrategyType branches outside
    # loss_minimizer + tests at b95d3a3).
    LONG_CALL_DEBIT_SPREAD = "long_call_debit_spread"
    LONG_PUT_DEBIT_SPREAD = "long_put_debit_spread"
    UNKNOWN = "unknown"

class OutcomeStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"

class UnifiedScoreComponent(BaseModel):
    ev: float
    execution_cost: float
    regime_penalty: float
    greek_penalty: float
    total_score: float
    roi_mode: Optional[str] = None
    roi_denom: Optional[float] = None

class UnifiedScore(BaseModel):
    score: float
    components: UnifiedScoreComponent
    badges: list[str] = []
    regime: RegimeState
    execution_cost_dollars: float = 0.0
