from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
from uuid import UUID
from enum import Enum

class UpgradeCapability(str, Enum):
    AGENT_SIZING = "AGENT_SIZING"
    COUNTERFACTUAL_ANALYSIS = "COUNTERFACTUAL_ANALYSIS"
    ADVANCED_EVENT_GUARDRAILS = "ADVANCED_EVENT_GUARDRAILS"

class CapabilityState(BaseModel):
    capability: UpgradeCapability
    is_active: bool
    reason: Optional[str] = None # e.g. "Account > $25k", "Data available"

class UserCapabilitiesResponse(BaseModel):
    capabilities: List[CapabilityState]

class OptionLeg(BaseModel):
    symbol: str
    action: Literal["buy", "sell"] = "buy"
    type: Literal["call", "put", "stock", "other"] = "call"
    strike: Optional[float] = None
    expiry: Optional[str] = None  # YYYY-MM-DD
    quantity: int = 1

class TradeTicket(BaseModel):
    # Core identity / linkage
    ticket_id: Optional[UUID] = None
    source_engine: Optional[str] = None  # "optimizer", "morning_suggestion", "weekly_scout", etc.
    source_ref_id: Optional[UUID] = None  # link to trade_suggestions.id if available

    # Strategy details
    strategy_type: Optional[str] = None  # "iron_condor", "vertical_spread", "long_call", etc.
    symbol: str
    legs: List[OptionLeg] = []

    # Execution parameters
    order_type: Literal["market", "limit"] = "limit"
    limit_price: Optional[float] = None
    quantity: int = 1  # number of spreads/contracts

    # Metadata for learning / context
    catalyst_window: Optional[str] = None  # "morning_limit", "midday_entry", etc.
    conviction_score: Optional[float] = None  # 0.0 - 1.0
    expected_value: Optional[float] = None
    risk_bracket: Optional[str] = None  # "conservative", "aggressive"
    regime_context: Dict[str, Any] = {}


class SuggestionLog(BaseModel):
    id: Optional[str] = None # UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str

    # Context
    regime_context: Dict[str, Any]

    # Suggestion identity
    symbol: str
    strategy_type: str
    direction: str

    # Plan
    target_price: float
    stop_loss: Optional[float] = None
    confidence_score: float

    # Linkage
    was_accepted: bool = False
    trade_execution_id: Optional[str] = None


class TradeExecution(BaseModel):
    id: Optional[str] = None # UUID
    user_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Broker / fill data
    symbol: str
    fill_price: float
    quantity: int
    fees: float = 0.0

    # Linkage
    suggestion_id: Optional[str] = None

    # Outcome
    realized_pnl: Optional[float] = None
    exit_timestamp: Optional[datetime] = None


class WeeklySnapshot(BaseModel):
    id: Optional[str] = None
    user_id: str
    week_id: str          # e.g. "2025-W48"
    date_start: datetime
    date_end: datetime

    dominant_regime: Optional[str] = None
    avg_ivr: Optional[float] = None

    user_metrics: Dict[str, Any]    # JSONB in DB
    system_metrics: Dict[str, Any]  # JSONB in DB
    synthesis: Dict[str, Any]       # JSONB in DB

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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

    # Phase 8.1
    asset_type: Literal["EQUITY", "OPTION", "CASH", "CRYPTO", "UNKNOWN"] = "UNKNOWN"
    sector: Optional[str] = None
    industry: Optional[str] = None
    strategy_tag: Optional[str] = None
    is_locked: bool = False
    optimizer_role: str = "TARGET" # 'TARGET', 'HEDGE', 'IGNORE'

class UnifiedPosition(BaseModel):
    symbol: str
    security_id: Optional[str] = None
    asset_type: str  # 'EQUITY' | 'OPTION' | 'CASH' | 'CRYPTO' | 'UNKNOWN'
    quantity: float
    cost_basis: float
    current_price: float

    sector: Optional[str] = None
    industry: Optional[str] = None
    strategy_tag: Optional[str] = None

    delta: float = 0.0
    beta_weighted_delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    is_locked: bool = False
    optimizer_role: str = "TARGET"  # 'TARGET' | 'HEDGE' | 'IGNORE'

class OptimizationRationale(BaseModel):
    status: Literal["OPTIMAL", "CONSTRAINED", "FAILED"]
    trace_id: Optional[str] = None
    regime_detected: Optional[str] = None
    conviction_used: Optional[float] = None
    alpha_score: Optional[float] = None
    risk_penalty: Optional[float] = None
    constraint_cost: Optional[float] = None
    active_constraints: List[str] = []

class RiskDashboardResponse(BaseModel):
    summary: Dict[str, Any]
    exposure: Dict[str, Any]
    greeks: Dict[str, float]

class SyncResponse(BaseModel):
    status: str
    count: int
    holdings: List[Holding]

class PortfolioSnapshot(BaseModel):
    id: Optional[str] = None
    user_id: str
    created_at: datetime
    # Make snapshot_type mandatory to force validation failure if missing in test
    snapshot_type: str = "on-sync"
    # Ensure holdings is a list of dicts, which might fail validation if data is malformed
    holdings: List[Dict[str, Any]]
    spreads: Optional[List[SpreadPosition]] = None
    risk_metrics: Optional[Dict[str, Any]] = None
    optimizer_status: Optional[str] = "pending"
    last_optimizer_run_at: Optional[datetime] = None
    buying_power: Optional[float] = None
