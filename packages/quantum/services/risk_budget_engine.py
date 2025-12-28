from supabase import Client
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime

from packages.quantum.common_enums import RegimeState
from packages.quantum.models import SpreadPosition
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.risk_engine import RiskEngine
from packages.quantum.analytics.regime_engine_v3 import GlobalRegimeSnapshot

# --- Types ---

class RiskAllocations(BaseModel):
    used: float
    max_limit: float
    remaining: float
    pct_used: float

class GreeksRisk(BaseModel):
    delta: RiskAllocations
    vega: RiskAllocations

class RiskBudgetReport(BaseModel):
    user_id: str
    regime: str
    risk_profile: str
    total_equity: float
    deployable_capital: float

    # Global Allocations (Equity %)
    global_allocation: RiskAllocations

    # Granular Limits
    strategy_allocation: Dict[str, RiskAllocations]
    underlying_allocation: Dict[str, RiskAllocations]
    greeks: GreeksRisk

    # Per-Trade Limits
    max_risk_per_trade: float

    # Diagnostics
    diagnostics: List[str] = Field(default_factory=list)
    policy_applied: bool = False

    # Compatibility with legacy dict
    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)

# --- Helper Functions ---

def _normalize_position_value(pos: Union[Dict, SpreadPosition]) -> float:
    if isinstance(pos, SpreadPosition):
        return pos.current_value
    return float(pos.get("current_value", 0.0) or 0.0)

def _get_symbol(pos: Union[Dict, SpreadPosition]) -> str:
    if isinstance(pos, SpreadPosition):
        return pos.ticker or pos.underlying
    # Fallback for dict
    return str(pos.get("ticker") or pos.get("symbol") or pos.get("underlying") or "unknown")

def _get_strategy_type(pos: Union[Dict, SpreadPosition]) -> str:
    if isinstance(pos, SpreadPosition):
        return str(pos.spread_type or "unknown").lower()
    return str(pos.get("strategy") or pos.get("type") or pos.get("instrument_type") or "unknown").lower()

def _estimate_risk_usage_usd(pos: Union[Dict, SpreadPosition], underlying_price: float = None) -> float:
    """
    Returns risk usage in USD for this position.
    Prefer defined-risk: max_loss or collateral.
    """
    # 1. SpreadPosition object
    if isinstance(pos, SpreadPosition):
        # Explicit Risk Fields on SpreadPosition (if added in recent schema updates)
        # Note: Standard SpreadPosition model might not have max_loss/collateral fields directly unless extended.
        # We check dynamically.
        if hasattr(pos, "max_loss") and pos.max_loss is not None:
             return float(pos.max_loss)
        if hasattr(pos, "collateral") and pos.collateral is not None:
             return float(pos.collateral)

        # Fallback to leg analysis if possible, or convert to dict for shared logic
        # But converting to dict loses nothing if we just use the shared logic block below.
        # Let's map SpreadPosition to the dict structure expected below for safety/consistency.

        # We need to construct a robust dict representation
        # SpreadPosition usually has: ticker, spread_type, legs (list of objects/dicts)
        # But this function handles SINGLE positions usually?
        # Wait, SpreadPosition implies a multi-leg struct.
        # If it's a SpreadPosition, it aggregates legs.
        # Logic:
        # If it's a debit spread (long call/put spread), risk is usually cost basis (or current val if cost unknown).
        # If it's a credit spread, risk is width * 100 * qty.
        # If undefined, fallback to safe proxy.

        # Simple heuristic for SpreadPosition objects:
        # If 'net_cost' > 0 (Debit), risk is cost.
        # If 'net_cost' < 0 (Credit), risk is margin.

        qty = abs(pos.quantity or 1.0) # Spread quantity

        # Check spread type
        st = str(pos.spread_type or "").lower()
        if "vertical" in st or "spread" in st or "condor" in st or "butterfly" in st:
             # Defined Risk Spreads
             # If credit, we need width.
             # If we can't compute width easily here, we might under-estimate.
             # Ideally SpreadPosition has 'max_loss'.
             # If not, we fall back to generic logic which might fail for objects.
             pass

        # Delegate to the robust dict logic by dumping model if possible
        if hasattr(pos, "model_dump"):
            d = pos.model_dump()
        elif hasattr(pos, "dict"):
            d = pos.dict()
        else:
            d = vars(pos)

        # Re-enter with dict
        return _estimate_risk_usage_usd(d, underlying_price)

    # 2. Dictionary (Legacy logic preserved)
    qty = abs(float(pos.get("quantity") or pos.get("qty") or 0.0))
    if qty <= 0: return 0.0

    # Prefer defined risk
    max_loss = pos.get("max_loss_per_contract") or pos.get("max_loss")
    collateral = pos.get("collateral_required_per_contract") or pos.get("collateral_per_contract")

    if max_loss is not None:
        try:
             if float(max_loss) > 0: return float(max_loss) * qty
        except (ValueError, TypeError): pass

    if collateral is not None:
        try:
            if float(collateral) > 0: return float(collateral) * qty
        except (ValueError, TypeError): pass

    # Identify option-ness
    instr = str(pos.get("instrument_type") or pos.get("type") or pos.get("asset_type") or "").lower()
    symbol = str(pos.get("symbol", ""))
    strike = pos.get("strike")
    option_type_field = pos.get("option_type") or pos.get("right")

    is_option = ("option" in instr) or symbol.startswith("O:") or (len(symbol) > 6 and any(c.isdigit() for c in symbol)) or (strike is not None) or (option_type_field is not None)

    side = str(pos.get("side") or pos.get("action") or "").lower()
    is_short = side in ("sell", "short")
    is_long = side in ("buy", "long") or (not is_short)

    cost_basis = float(pos.get("cost_basis") or 0.0)

    if is_option:
        opt_type = str(option_type_field or "").lower()
        if is_long:
            return abs(cost_basis) * 100.0 * qty

        # Short Option Logic
        if strike is not None:
            try:
                strike_f = float(strike)
                if "put" in opt_type or opt_type == "p":
                    return strike_f * 100.0 * qty
                if "call" in opt_type or opt_type == "c":
                    und = float(underlying_price) if underlying_price is not None else strike_f
                    return max(und, strike_f) * 100.0 * qty
            except (ValueError, TypeError):
                pass

        # Fallback
        return abs(cost_basis) * 100.0 * qty

    # Stocks
    return abs(float(pos.get("current_value") or 0.0))


class RiskBudgetEngine:
    """
    Canonical Risk Budget Engine for the Quantum system.
    Unifies logic from midday, rebalance, and optimizer workflows.
    """

    def __init__(self, supabase: Client):
        self.supabase = supabase
        # Initialize truth layer lazily or allow it to fail gracefully if only static methods used?
        # Better: Instantiate, but maybe don't use it if not needed.
        # Optimizer calls calculate_strategy_cap which is static now, so it won't init this class.
        # Midday calls compute(), which needs it.
        self.truth_layer = MarketDataTruthLayer()

    def _resolve_regime(self, regime_input: Union[str, GlobalRegimeSnapshot, RegimeState]) -> RegimeState:
        if isinstance(regime_input, RegimeState):
            return regime_input
        if isinstance(regime_input, GlobalRegimeSnapshot):
            return regime_input.state

        # String parsing
        r_str = str(regime_input).upper()
        try:
            # Map legacy strings to Enum
            if "PANIC" in r_str or "SHOCK" in r_str: return RegimeState.SHOCK
            if "ELEVATED" in r_str or "HIGH_VOL" in r_str: return RegimeState.ELEVATED
            if "SUPPRESSED" in r_str: return RegimeState.SUPPRESSED
            if "NORMAL" in r_str: return RegimeState.NORMAL
            if "CHOP" in r_str: return RegimeState.CHOP
            if "REBOUND" in r_str: return RegimeState.REBOUND

            return RegimeState[r_str]
        except KeyError:
            return RegimeState.NORMAL

    @staticmethod
    def calculate_strategy_cap(strategy_type: str, regime: RegimeState, conviction: float = 1.0) -> float:
        """
        Returns adjusted_cap ∈ [0, 1.0] based on regime rules and conviction.
        """
        caps = {
            RegimeState.SUPPRESSED: {
                "debit_call": 0.12, "debit_put": 0.12, "credit_call": 0.06, "credit_put": 0.06,
                "iron_condor": 0.04, "single": 0.15
            },
            RegimeState.NORMAL: {
                "debit_call": 0.15, "debit_put": 0.15, "credit_call": 0.08, "credit_put": 0.08,
                "iron_condor": 0.06, "vertical": 0.10
            },
            RegimeState.ELEVATED: {
                 "credit_call": 0.12, "credit_put": 0.12, "debit_call": 0.06, "debit_put": 0.06,
                 "iron_condor": 0.08, "single": 0.05
            },
            RegimeState.SHOCK: {
                 "credit_call": 0.05, "credit_put": 0.02,
                 "debit_put": 0.10, "debit_call": 0.02,
                 "iron_condor": 0.00, "vertical": 0.03
            },
            RegimeState.REBOUND: {
                 "debit_call": 0.12, "credit_put": 0.12,
                 "debit_put": 0.04, "credit_call": 0.05,
                 "single": 0.08
            },
            RegimeState.CHOP: {
                 "iron_condor": 0.10, "calendar": 0.10,
                 "debit_call": 0.05, "debit_put": 0.05,
                 "credit_call": 0.08, "credit_put": 0.08
            }
        }

        regime_caps = caps.get(regime, caps[RegimeState.NORMAL])
        st = strategy_type.lower()
        base_cap = 0.05 # Default low

        # 1. Exact match
        if st in regime_caps:
            base_cap = regime_caps[st]
        else:
            # 2. Substring match
            for k, v in regime_caps.items():
                if k in st:
                    base_cap = v
                    break

        # Conviction Scaling (if needed, but usually this is a hard cap)
        # We'll stick to base caps for budget checks. Conviction scaling is for sizing.
        return base_cap

    def compute(
        self,
        user_id: str,
        deployable_capital: float,
        regime_input: Union[str, GlobalRegimeSnapshot, RegimeState],
        positions: List[Union[Dict, SpreadPosition]],
        risk_profile: str = "balanced"
    ) -> RiskBudgetReport:

        regime = self._resolve_regime(regime_input)
        diagnostics = []

        # 1. Calculate Total Equity & Current Usage
        positions_value = 0.0
        current_risk_usage = 0.0

        # Usage trackers
        strategy_usage = {}
        underlying_usage = {}
        delta_usage = 0.0
        vega_usage = 0.0

        # Pre-fetch for legacy dict positions if needed
        fetched_prices = {}
        legacy_dicts = [p for p in positions if isinstance(p, dict)]
        if legacy_dicts:
            # logic to fetch underlyings if missing (simplified from original)
            pass

        for p in positions:
            # Value & Risk
            val = _normalize_position_value(p)
            risk = _estimate_risk_usage_usd(p) # Approximate

            positions_value += val
            current_risk_usage += risk

            # Granular
            st = _get_strategy_type(p)
            sym = _get_symbol(p)

            strategy_usage[st] = strategy_usage.get(st, 0.0) + val
            underlying_usage[sym] = underlying_usage.get(sym, 0.0) + val

            # Greeks (if available)
            if isinstance(p, SpreadPosition):
                delta_usage += abs(p.delta)
                vega_usage += abs(p.vega)
            elif isinstance(p, dict):
                # Try to extract
                d = float(p.get("delta", 0.0) or 0.0)
                v = float(p.get("vega", 0.0) or 0.0)
                # If per-share, multiply by 100*qty
                qty = float(p.get("quantity", 0.0) or 0.0)
                # Assume stored greeks are total or per unit? Usually per unit in raw positions.
                # If raw position has 'delta', it's usually per share or per contract.
                # Assuming standard: delta is per share equivalent?
                # Let's keep it simple: if it's a dict, we might not have reliable greeks.
                pass

        total_equity = deployable_capital + positions_value
        if total_equity <= 0: total_equity = 1.0

        # 2. Determine Global Caps (Regime Based)
        global_caps_map = {
            RegimeState.SUPPRESSED: 0.50,
            RegimeState.NORMAL: 0.40,
            RegimeState.ELEVATED: 0.25,
            RegimeState.CHOP: 0.35,
            RegimeState.REBOUND: 0.30,
            RegimeState.SHOCK: 0.05
        }
        global_cap_pct = global_caps_map.get(regime, 0.40)

        # Risk Profile Adjustments for Granular Limits
        profile_mult = 1.0
        if risk_profile == "aggressive": profile_mult = 1.25
        elif risk_profile == "conservative": profile_mult = 0.75

        # 3. Apply Policy Overrides (LossMinimizer)
        policy = RiskEngine.get_active_policy(user_id, self.supabase, regime)
        policy_applied = False

        if policy:
            policy_max = policy.get("max_position_pct")
            if policy_max is not None:
                # This usually applies to per-position, but could imply global tightening
                # Let's respect it for global if it's very low, or just per-trade.
                # Policy usually returns 'max_position_pct' (per trade).
                pass

            # Banned structures?
            banned = policy.get("ban_structures", [])
            for b in banned:
                # If user holds banned strategy, flag it?
                # We won't force close here, but we can set remaining budget for that strategy to 0.
                pass

            policy_applied = True

        # 4. Construct Allocations

        # Global
        global_max = total_equity * global_cap_pct
        global_alloc = RiskAllocations(
            used=current_risk_usage,
            max_limit=global_max,
            remaining=max(0.0, global_max - current_risk_usage),
            pct_used=(current_risk_usage / global_max) if global_max > 0 else 0.0
        )

        # Strategies
        strat_allocs = {}
        all_strategies = set(strategy_usage.keys())
        # Add common ones so they appear in report even if 0 usage
        for s_key in ["vertical", "iron_condor", "calendar"]:
            all_strategies.add(s_key)

        for st in all_strategies:
            base_cap_pct = self.calculate_strategy_cap(st, regime)
            # Profile adjustment
            cap_pct = base_cap_pct * profile_mult

            limit = total_equity * cap_pct
            used = strategy_usage.get(st, 0.0)
            strat_allocs[st] = RiskAllocations(
                used=used,
                max_limit=limit,
                remaining=max(0.0, limit - used),
                pct_used=(used / limit) if limit > 0 else 0.0
            )

        # Underlyings
        und_allocs = {}
        default_und_cap = 0.20 * profile_mult # 20% default
        for sym, used in underlying_usage.items():
            limit = total_equity * default_und_cap
            und_allocs[sym] = RiskAllocations(
                used=used,
                max_limit=limit,
                remaining=max(0.0, limit - used),
                pct_used=(used / limit) if limit > 0 else 0.0
            )

        # Greeks (simplified caps)
        # Delta cap: roughly 1.0 * equity? No, usually absolute delta dollars or beta weighted.
        # Let's use a soft cap placeholder.
        delta_cap = total_equity * 0.5 * profile_mult # very rough
        vega_cap = total_equity * 0.01 * profile_mult # 1% of equity per vol point?

        greeks_risk = GreeksRisk(
            delta=RiskAllocations(used=delta_usage, max_limit=delta_cap, remaining=delta_cap-delta_usage, pct_used=delta_usage/delta_cap if delta_cap>0 else 0),
            vega=RiskAllocations(used=vega_usage, max_limit=vega_cap, remaining=vega_cap-vega_usage, pct_used=vega_usage/vega_cap if vega_cap>0 else 0)
        )

        # 5. Max Risk Per Trade (Sizing)
        # Based on profile and total equity
        if risk_profile == "aggressive":
            per_trade_pct = 0.05
        elif risk_profile == "conservative":
            per_trade_pct = 0.02
        else:
            per_trade_pct = 0.03

        # Policy override
        if policy and policy.get("max_position_pct"):
            per_trade_pct = min(per_trade_pct, policy.get("max_position_pct"))

        max_risk_trade = total_equity * per_trade_pct

        # Small Account Logic
        # If max_risk_trade is tiny (< $50), but we have some capital, allow a floor?
        # Say, if equity > 500, allow at least $50 risk (enough for a cheap spread).
        if max_risk_trade < 50.0 and total_equity > 500.0:
            max_risk_trade = 50.0
            diagnostics.append("small_account_floor_active")

        # 6. Global Remaining Check
        # If global remaining is 0, then per_trade should be 0 (unless small account override?)
        if global_alloc.remaining <= 10.0 and "small_account_floor_active" not in diagnostics:
             max_risk_trade = 0.0
             diagnostics.append("global_cap_reached")
        else:
             # Clamp to remaining
             max_risk_trade = min(max_risk_trade, global_alloc.remaining)

        return RiskBudgetReport(
            user_id=user_id,
            regime=regime.name,
            risk_profile=risk_profile,
            total_equity=total_equity,
            deployable_capital=deployable_capital,
            global_allocation=global_alloc,
            strategy_allocation=strat_allocs,
            underlying_allocation=und_allocs,
            greeks=greeks_risk,
            max_risk_per_trade=max_risk_trade,
            diagnostics=diagnostics,
            policy_applied=policy_applied
        )
