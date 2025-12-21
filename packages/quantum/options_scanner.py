import os
import requests
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
import logging
import concurrent.futures

from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.ev_calculator import calculate_ev, calculate_condor_ev
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.regime_integration import map_market_regime
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, GlobalRegimeSnapshot, RegimeState
from packages.quantum.analytics.scoring import calculate_unified_score
from packages.quantum.services.execution_service import ExecutionService
from packages.quantum.analytics.guardrails import earnings_week_penalty

# Configuration
SCANNER_LIMIT_DEV = int(os.getenv("SCANNER_LIMIT_DEV", "40")) # Limit universe in dev
SCANNER_MIN_DTE = 25
SCANNER_MAX_DTE = 45

logger = logging.getLogger(__name__)

def _select_best_expiry_chain(chain: List[Dict[str, Any]], target_dte: int = 35) -> tuple[Optional[str], List[Dict[str, Any]]]:
    if not chain:
        return None, []

    # Group by expiry
    buckets = {}
    for c in chain:
        exp = c.get("expiration")
        if not exp: continue
        if exp not in buckets:
            buckets[exp] = []
        buckets[exp].append(c)

    if not buckets:
        return None, []

    # Helper to get DTE diff
    def get_dte_diff(exp_str):
        try:
            exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").date()
            return abs((exp_dt - datetime.now().date()).days - target_dte)
        except ValueError:
            return 9999

    # Sort keys:
    # 1. Count (descending) -> -len
    # 2. DTE diff (ascending)
    # 3. Expiry string (ascending)
    sorted_expiries = sorted(
        buckets.keys(),
        key=lambda e: (-len(buckets[e]), get_dte_diff(e), e)
    )

    best_expiry = sorted_expiries[0]
    return best_expiry, buckets[best_expiry]

def _select_legs_from_chain(
    calls: List[Dict[str, Any]],
    puts: List[Dict[str, Any]],
    leg_defs: List[Dict[str, Any]],
    current_price: float
) -> tuple[List[Dict[str, Any]], float]:
    """
    Selects legs using pre-sorted call/put lists to avoid repeated filtering/sorting.
    calls: sorted by strike (asc)
    puts: sorted by strike (asc)
    """
    legs = []
    total_cost = 0.0

    for leg_def in leg_defs:
        target_delta = leg_def["delta_target"]
        side = leg_def["side"]
        op_type = leg_def["type"]

        # 1. Select the relevant pre-filtered list
        candidates = calls if op_type == "call" else puts
        if not candidates:
             continue

        # 2. Find best contract (Delta or Moneyness)
        # Note: Optimization - candidates are sorted by strike.
        # But we search by Delta mostly. Delta is monotonic with strike (mostly).
        # Calls: Low Strike = High Delta (~1.0) -> High Strike = Low Delta (~0.0)
        # Puts: Low Strike = Low Delta (~0.0) -> High Strike = High Delta (~1.0, abs)
        # For now, linear scan for Delta is fine as N is small per expiry (e.g. 50 items).
        # We save the repeated [c for c in chain if ...] allocation.

        has_delta = any('delta' in c and c['delta'] is not None for c in candidates)

        if has_delta:
            target_d = abs(target_delta)
            best_contract = min(candidates, key=lambda x: abs(abs(x.get('delta') or 0) - target_d))
        else:
            moneyness = 1.0
            if op_type == 'call':
                if target_delta > 0.5: moneyness = 0.95
                elif target_delta < 0.5: moneyness = 1.05
            else:
                if target_delta > 0.5: moneyness = 1.05
                elif target_delta < 0.5: moneyness = 0.95

            target_k = current_price * moneyness
            # Binary search could be used here since sorted by strike, but min() is robust and fast enough for N=50
            best_contract = min(candidates, key=lambda x: abs(x['strike'] - target_k))

        premium = best_contract.get('price') or best_contract.get('close') or 0.0

        bid = best_contract.get('bid')
        ask = best_contract.get('ask')
        mid = None
        if bid is not None and ask is not None:
             mid = (float(bid) + float(ask)) / 2.0

        legs.append({
            "symbol": best_contract['ticker'],
            "strike": best_contract['strike'],
            "expiry": best_contract['expiration'],
            "type": op_type,
            "side": side,
            "premium": premium,
            "delta": best_contract.get('delta') or target_delta,
            "gamma": best_contract.get('gamma') or 0.0,
            "vega": best_contract.get('vega') or 0.0,
            "theta": best_contract.get('theta') or 0.0,
            "bid": bid,
            "ask": ask,
            "mid": mid
        })

        if side == "buy":
            total_cost += premium
        else:
            total_cost -= premium

    return legs, total_cost

def _select_iron_condor_legs(
    calls: List[Dict[str, Any]],
    puts: List[Dict[str, Any]],
    current_price: float,
    target_delta: float = 0.15
) -> tuple[List[Dict[str, Any]], float]:
    """
    Selects 4 legs for an Iron Condor using pre-sorted lists.
    calls: sorted by strike
    puts: sorted by strike
    """
    legs = []
    total_cost = 0.0

    if not calls or not puts:
        return [], 0.0

    # 2. Select Shorts by Delta
    # Target delta is usually ~0.15 (abs)
    # Short Call: delta ~ 0.15
    short_call = min(calls, key=lambda x: abs(abs(x.get("delta") or 0) - target_delta))
    # Short Put: delta ~ -0.15
    short_put = min(puts, key=lambda x: abs(abs(x.get("delta") or 0) - target_delta))

    # 3. Determine Width
    width = 5.0 if current_price >= 50.0 else 2.5

    # 4. Select Longs by Strike
    # Long Call: Strike > Short Call Strike
    target_long_call_strike = short_call["strike"] + width
    # Filter for strikes >= target (or just closest)
    # Ideally strictly > short strike
    valid_long_calls = [c for c in calls if c["strike"] > short_call["strike"]]
    if not valid_long_calls:
        # Fallback to just closest if no strictly greater exists (unlikely if chain is deep)
        long_call = min(calls, key=lambda x: abs(x["strike"] - target_long_call_strike))
    else:
        long_call = min(valid_long_calls, key=lambda x: abs(x["strike"] - target_long_call_strike))

    # Long Put: Strike < Short Put Strike
    target_long_put_strike = short_put["strike"] - width
    valid_long_puts = [c for c in puts if c["strike"] < short_put["strike"]]
    if not valid_long_puts:
        long_put = min(puts, key=lambda x: abs(x["strike"] - target_long_put_strike))
    else:
        long_put = min(valid_long_puts, key=lambda x: abs(x["strike"] - target_long_put_strike))

    # Check that we didn't pick the same strike (should be handled by valid_ filters but verify)
    if long_call["strike"] <= short_call["strike"] or long_put["strike"] >= short_put["strike"]:
        # Failed to find appropriate wings
        return [], 0.0

    # 5. Build Legs List (Sell Shorts, Buy Longs)
    # Order: Short Put, Long Put, Short Call, Long Call (or any consistent order)
    # Let's do: Sell Put, Buy Put, Sell Call, Buy Call

    selected_contracts = [
        (short_put, "sell"),
        (long_put, "buy"),
        (short_call, "sell"),
        (long_call, "buy")
    ]

    for contract, side in selected_contracts:
        # Use mid from bid/ask if available, otherwise 'price'/'close'
        bid = contract.get("bid")
        ask = contract.get("ask")
        mid_calc = None
        if bid is not None and ask is not None and ask >= bid:
            mid_calc = (float(bid) + float(ask)) / 2.0

        premium = mid_calc if mid_calc is not None else (contract.get("price") or contract.get("close") or 0.0)

        leg = {
            "symbol": contract['ticker'],
            "strike": contract['strike'],
            "expiry": contract['expiration'],
            "type": contract['type'],
            "side": side,
            "premium": premium,
            "delta": contract.get('delta') or 0.0,
            "gamma": contract.get('gamma') or 0.0,
            "vega": contract.get('vega') or 0.0,
            "theta": contract.get('theta') or 0.0,
            # Pass through bid/ask for width calculation later
            "bid": contract.get("bid"),
            "ask": contract.get("ask"),
            "mid": premium
        }
        legs.append(leg)

        if side == "buy":
            total_cost += premium
        else:
            total_cost -= premium

    return legs, total_cost

def _validate_iron_condor_invariants(legs: List[Dict[str, Any]]) -> bool:
    """
    Validates Iron Condor invariants:
    1. 4 unique legs
    2. Shared expiry
    3. Correct types and sides
    4. Strict strike ordering: Long Put < Short Put < Short Call < Long Call
    """
    if len(legs) != 4:
        return False

    symbols = {l["symbol"] for l in legs}
    if len(symbols) != 4:
        return False

    expiries = {l["expiry"] for l in legs}
    if len(expiries) != 1:
        return False

    # Categorize
    calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
    puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

    if len(calls) != 2 or len(puts) != 2:
        return False

    # Check Calls: Short (lower k) < Long (higher k)
    # Short Call should be SELL, Long Call should be BUY
    short_call = calls[0]
    long_call = calls[1]

    if short_call["side"] != "sell" or long_call["side"] != "buy":
        return False
    if not (short_call["strike"] < long_call["strike"]): # Strict inequality already from sort if unique, but check
        return False

    # Check Puts: Long (lower k) < Short (higher k)
    # Long Put should be BUY, Short Put should be SELL
    long_put = puts[0]
    short_put = puts[1]

    if long_put["side"] != "buy" or short_put["side"] != "sell":
        return False
    if not (long_put["strike"] < short_put["strike"]):
        return False

    # Check Put Wing < Call Wing (Strict ordering of wings)
    # Short Put < Short Call
    if not (short_put["strike"] < short_call["strike"]):
        return False

    return True
def _validate_spread_economics(legs: List[Dict[str, Any]], total_cost: float) -> tuple[bool, str]:
    if not legs:
        return False, "no_legs"

    # Common validation: Expiry
    expiries = {l.get("expiry") for l in legs if l.get("expiry")}
    if len(expiries) > 1:
        return False, "expiry_mismatch"

    if len(legs) == 2:
        long_leg = next((l for l in legs if l["side"] == "buy"), None)
        short_leg = next((l for l in legs if l["side"] == "sell"), None)

        if not long_leg or not short_leg:
            return False, "missing_long_or_short"

        width = abs(long_leg["strike"] - short_leg["strike"])
        premium_share = abs(float(total_cost))

        if width <= 1e-9:
            return False, "zero_width"
        if premium_share <= 1e-9:
            return False, "zero_premium"
        if premium_share >= width:
            return False, "premium_ge_width"

        return True, ""

    elif len(legs) == 4:
        # Condor validation
        if not _validate_iron_condor_invariants(legs):
            return False, "iron_condor_invariants"

        if total_cost is None or total_cost >= 0:
            return False, "iron_condor_not_credit"

        # Identify legs
        calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
        puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

        # Already validated 2 calls 2 puts in invariants
        # Short Call (lower k), Long Call (higher k)
        short_call = calls[0]
        long_call = calls[1]

        # Long Put (lower k), Short Put (higher k)
        long_put = puts[0]
        short_put = puts[1]

        width_put = short_put["strike"] - long_put["strike"]
        width_call = long_call["strike"] - short_call["strike"]
        max_width = max(width_put, width_call)

        if max_width <= 0:
            return False, "iron_condor_invalid_width"

        credit = abs(total_cost)
        if credit >= max_width:
            return False, "iron_condor_credit_ge_width"

        return True, ""

    return True, ""

def _map_single_leg_strategy(leg: Dict[str, Any]) -> Optional[str]:
    """Maps scanner leg attributes to calculate_ev strategy types."""
    side = str(leg.get("side") or "").lower()
    opt_type = str(leg.get("type") or "").lower()

    if side == "buy" and opt_type == "call":
        return "long_call"
    elif side == "buy" and opt_type == "put":
        return "long_put"
    elif side == "sell" and opt_type == "call":
        return "short_call"
    elif side == "sell" and opt_type == "put":
        return "short_put"
    else:
        return None

def _compute_risk_primitives_usd(legs: List[Dict[str, Any]], total_cost: float, current_price: float) -> Dict[str, float]:
    """
    Computes max loss, max profit, and collateral required in contract USD terms.
    Always returns valid float values for 1-leg and 2-leg strategies.
    """
    max_loss = 0.0
    max_profit = 0.0
    collateral_required = 0.0

    if len(legs) == 1:
        leg = legs[0]
        premium = float(leg.get("premium") or 0.0)
        strike = float(leg.get("strike") or 0.0)
        side = leg["side"]
        opt_type = leg["type"]

        if side == "buy":
            max_loss = premium * 100.0
            collateral_required = max_loss # Debit paid
            if opt_type == "call":
                max_profit = float("inf")
            else: # put
                max_profit = max(0.0, (strike - premium)) * 100.0
        else: # side == "sell"
            max_profit = premium * 100.0
            if opt_type == "call":
                max_loss = float("inf")
                # Crude placeholder for naked call capital
                collateral_required = current_price * 100.0
            else: # put
                max_loss = max(0.0, (strike - premium)) * 100.0
                # Cash-secured put approximation
                collateral_required = strike * 100.0

    elif len(legs) == 2:
        long_leg = next((l for l in legs if l["side"] == "buy"), None)
        short_leg = next((l for l in legs if l["side"] == "sell"), None)

        if long_leg and short_leg:
            width = abs(long_leg["strike"] - short_leg["strike"])
            # total_cost > 0 is DEBIT, < 0 is CREDIT

            if total_cost > 0: # DEBIT SPREAD
                debit = abs(total_cost)
                max_loss = debit * 100.0
                max_profit = max(0.0, (width - debit)) * 100.0
                collateral_required = max_loss # Capital is the debit paid
            else: # CREDIT SPREAD
                credit = abs(total_cost)
                max_loss = max(0.0, (width - credit)) * 100.0
                max_profit = credit * 100.0
                collateral_required = width * 100.0 # Margin is usually the width

    elif len(legs) == 4:
        # Iron Condor Risk Primitives
        # Expecting negative total_cost (Credit)
        credit_share = abs(total_cost) if total_cost < 0 else 0.0

        # Identify legs
        calls = [l for l in legs if l["type"] == "call"]
        puts = [l for l in legs if l["type"] == "put"]

        if len(calls) == 2 and len(puts) == 2:
            # Sort by strike
            calls.sort(key=lambda x: x["strike"]) # Short Call is lower strike, Long Call is higher
            puts.sort(key=lambda x: x["strike"])  # Long Put is lower strike, Short Put is higher

            # Call Spread: Short (lower k) - Long (higher k)
            short_call = calls[0] # Should be the short one
            long_call = calls[1]

            # Put Spread: Short (higher k) - Long (lower k)
            long_put = puts[0]
            short_put = puts[1] # Should be the short one

            # Verify sides if possible, but strike logic is robust for standard condors

            width_call = abs(long_call["strike"] - short_call["strike"])
            width_put = abs(short_put["strike"] - long_put["strike"])

            width_max = max(width_call, width_put)

            max_profit = credit_share * 100.0
            max_loss = max(0.0, (width_max - credit_share)) * 100.0
            collateral_required = width_max * 100.0

    return {
        "max_loss_per_contract": max_loss,
        "max_profit_per_contract": max_profit,
        "collateral_required_per_contract": collateral_required,
    }

def _estimate_probability_of_profit(candidate: Dict[str, Any], global_snapshot: Optional[Dict[str, Any]] = None) -> float:
    """
    Estimates the Probability of Profit (PoP) for a trade candidate.
    Returns a float in [0.01, 0.99].
    """
    score = candidate.get("score", 50.0)

    # 1. Base from score: sigmoid centered at 50
    # p = 1 / (1 + exp(-(score - 50) / 12))
    p = 1.0 / (1.0 + np.exp(-(score - 50.0) / 12.0))

    # 2. Strategy adjustments
    strategy = str(candidate.get("strategy", "")).lower()
    c_type = str(candidate.get("type", "")).lower()

    # Concatenate fields to ensure we catch the strategy name even if 'strategy' key is missing/empty
    # In scan_for_opportunities, 'strategy' key is populated, but we check both for safety.
    combined = f"{strategy} {c_type}"

    # Credit spreads / Iron Condors: +0.08
    if "credit" in combined or "condor" in combined:
        p += 0.08
    # Debit spreads / Calls / Puts: -0.05
    elif "debit" in combined or "call" in combined or "put" in combined:
        p -= 0.05

    # 3. Regime adjustment
    if global_snapshot:
        state = global_snapshot.get("state")
        # state can be an Enum or string. Convert to string safely.
        state_str = str(state).upper()

        # Check for SHOCK or HIGH_VOL
        if "SHOCK" in state_str or "HIGH_VOL" in state_str or "EXTREME" in state_str:
            p -= 0.07

    # 4. Clamp
    return float(np.clip(p, 0.01, 0.99))

def _combo_width_share_from_legs(truth_layer, legs, fallback_width_share):
    leg_syms = [l.get("symbol") for l in legs if l.get("symbol")]
    if not leg_syms:
        return float(fallback_width_share or 0.0)

    # First attempt: use leg quotes if available
    widths = []
    all_legs_ok = True
    for l in legs:
        bid = l.get("bid")
        ask = l.get("ask")
        if bid is not None and ask is not None:
            try:
                bid = float(bid)
                ask = float(ask)
                if bid > 0 and ask >= bid:
                    widths.append(ask - bid)
                else:
                    all_legs_ok = False
                    break
            except (ValueError, TypeError):
                all_legs_ok = False
                break
        else:
            all_legs_ok = False
            break

    if all_legs_ok and len(widths) == len(legs):
        return sum(widths)

    # Batch fetch snapshots for efficiency
    snaps = truth_layer.snapshot_many(leg_syms) or {}

    total = 0.0
    found = 0
    for l in legs:
        sym = l.get("symbol")
        key = truth_layer.normalize_symbol(sym) if hasattr(truth_layer, "normalize_symbol") else sym
        s = snaps.get(key) or snaps.get(sym) or {}

        q = (s.get("quote") or {}) if isinstance(s, dict) else {}
        bid = q.get("bid")
        ask = q.get("ask")

        if bid is not None and ask is not None:
            bid = float(bid)
            ask = float(ask)
            if bid > 0 and ask > 0 and ask >= bid:
                total += (ask - bid)
                found += 1

    return total if found > 0 else float(fallback_width_share or 0.0)

def _determine_execution_cost(
    drag_map: Dict[str, Any],
    symbol: str,
    combo_width_share: float,
    num_legs: int
) -> Dict[str, Any]:
    """
    Determines the execution cost to use for scoring and rejection.
    Logic: max(history_cost, proxy_cost).
    """
    # 1. Compute Proxy Cost ALWAYS
    # Formula: (combo_width_share * 0.5) + (num_legs * 0.0065) -> per share
    # Multiplied by 100 for contract dollars
    proxy_cost_share = (combo_width_share * 0.5) + (num_legs * 0.0065)
    proxy_cost_contract = proxy_cost_share * 100.0

    # 2. Fetch History Cost
    stats = drag_map.get(symbol)
    history_cost_contract = 0.0
    history_samples = 0
    has_history = False

    if stats and isinstance(stats, dict):
        history_cost_contract = float(stats.get("avg_drag") or 0.0)
        history_samples = int(stats.get("n", stats.get("N", 0)) or 0)
        has_history = True

    # execution_drag_source: "where history came from"
    execution_drag_source = "history" if has_history else "proxy"

    # 3. Choose Cost Used
    if history_cost_contract >= proxy_cost_contract and history_samples > 0:
        expected_execution_cost = history_cost_contract
        execution_cost_source_used = "history"
        execution_cost_samples_used = history_samples
    else:
        expected_execution_cost = proxy_cost_contract
        execution_cost_source_used = "proxy"
        execution_cost_samples_used = 0

    return {
        "expected_execution_cost": expected_execution_cost,
        "execution_cost_source_used": execution_cost_source_used,
        "execution_cost_samples_used": execution_cost_samples_used,
        "execution_drag_source": execution_drag_source
    }

def scan_for_opportunities(
    symbols: List[str] = None,
    supabase_client: Client = None,
    user_id: str = None,
    global_snapshot: GlobalRegimeSnapshot = None
) -> List[Dict[str, Any]]:
    """
    Scans the provided symbols (or universe) for option trade opportunities.
    Returns a list of trade candidates (dictionaries) with risk primitives.

    Output Schema:
    - symbol, ticker, strategy, ev, score
    - max_loss_per_contract (USD)
    - max_profit_per_contract (USD)
    - collateral_required_per_contract (USD)
    - net_delta_per_contract (shares-equivalent)
    - net_vega_per_contract (USD per 1% vol change per contract)
    - data_quality: "realtime" | "degraded"
    - pricing_mode: "exact" | "approximate"
    """
    candidates = []

    # Initialize services
    market_data = PolygonService()
    strategy_selector = StrategySelector()
    universe_service = UniverseService(supabase_client) if supabase_client else None
    execution_service = ExecutionService(supabase_client) if supabase_client else None

    # Unified Regime Engine
    truth_layer = MarketDataTruthLayer()
    regime_engine = RegimeEngineV3(
        supabase_client=supabase_client,
        market_data=truth_layer,
        iv_repository=IVRepository(supabase_client) if supabase_client else None,
        iv_point_service=IVPointService(supabase_client) if supabase_client else None,
    )

    # 1. Determine Universe & Earnings Map
    earnings_map = {}

    if not symbols:
        if universe_service:
            try:
                universe = universe_service.get_scan_candidates(limit=30)
                symbols = [u['symbol'] for u in universe]
                earnings_map = {u["symbol"]: u.get("earnings_date") for u in universe}
            except Exception as e:
                print(f"[Scanner] UniverseService failed: {e}. Using fallback.")
                symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
        else:
             symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]

    # Dev mode limit
    if os.getenv("APP_ENV") != "production":
        symbols = symbols[:SCANNER_LIMIT_DEV]

    print(f"[Scanner] Processing {len(symbols)} symbols...")

    # 2. Compute Global Regime Snapshot ONCE
    if global_snapshot is None:
        try:
            global_snapshot = regime_engine.compute_global_snapshot(datetime.now())
            print(f"[Scanner] Global Regime: {global_snapshot.state}")
        except Exception as e:
            print(f"[Scanner] Regime computation failed: {e}. Using default.")
            global_snapshot = regime_engine._default_global_snapshot(datetime.now())
    else:
        print(f"[Scanner] Using provided Global Regime: {global_snapshot.state}")

    # Batch fetch execution drag for efficiency (ONCE)
    drag_map = {}
    if execution_service and user_id:
        try:
            # Step B2: Build symbol list early, then call batch stats ONCE
            drag_map = execution_service.get_batch_execution_drag_stats(
                user_id=user_id,
                symbols=symbols,
                lookback_days=45,
                min_samples=3
            )
        except Exception as e:
            print(f"[Scanner] Failed to fetch execution stats: {e}")


    # 3. Parallel Processing
    batch_size = 20 # Increased from 5 to 20 to improve I/O throughput (Bolt Optimization)

    # 3a. Batch Fetch Quotes (Optimization)
    # Fetch all quotes in one go to avoid N requests inside the loop
    # truth_layer.snapshot_many handles batching automatically
    logger.info(f"[Scanner] Batch fetching quotes for {len(symbols)} symbols...")
    quotes_map = truth_layer.snapshot_many(symbols)

    def process_symbol(symbol: str, drag_map: Dict[str, Any], quotes_map: Dict[str, Any], earnings_map: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single symbol and return a candidate dict or None."""
        try:
            # A. Enrich Data
            # Use batched quote from map
            # Normalize symbol key for lookup
            key = truth_layer.normalize_symbol(symbol) if hasattr(truth_layer, "normalize_symbol") else symbol
            snapshot_item = quotes_map.get(key) or quotes_map.get(symbol)

            quote = {}
            if snapshot_item:
                # Convert MDTL snapshot format to scanner quote format
                q = snapshot_item.get("quote", {})
                quote = {
                    "bid": q.get("bid"),
                    "ask": q.get("ask"),
                    "bid_price": q.get("bid"),
                    "ask_price": q.get("ask"),
                    "price": q.get("last") or q.get("mid")
                }

            # Extract primitives from truth layer attempt
            bid = quote.get("bid")
            ask = quote.get("ask")
            current_price = quote.get("price")

            # Calculate mid if needed
            if current_price is None and bid is not None and ask is not None and bid > 0 and ask > 0:
                current_price = (float(bid) + float(ask)) / 2.0

            # Fallback to PolygonService if TruthLayer failed to provide a valid price
            if current_price is None:
                quote = market_data.get_recent_quote(symbol)
                bid = quote.get("bid_price") if "bid_price" in quote else quote.get("bid")
                ask = quote.get("ask_price") if "ask_price" in quote else quote.get("ask")
                current_price = quote.get("price")

                if current_price is None and bid is not None and ask is not None and bid > 0 and ask > 0:
                    current_price = (float(bid) + float(ask)) / 2.0

            if not current_price: return None

            # B. Check Liquidity (Deferred)
            # We calculate threshold here but apply it later using Option Spread Pct
            threshold = 0.10 # Default
            if global_snapshot.state == RegimeState.SUPPRESSED:
                    threshold = 0.20
            elif global_snapshot.state == RegimeState.SHOCK:
                    threshold = 0.15

            # Note: We NO LONGER reject here based on underlying spread.

            if not (bid is not None and ask is not None and bid > 0 and ask > 0):
                # We can reject if NO quote at all, but let's be lenient if we have current_price
                pass

            # D. Technical Analysis (Trend) - MOVED UP to reuse for Regime
            # Optimization: Use truth_layer which caches, and reuse bars for regime engine
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90) # Enough buffer for 60 trading days

            # Fetch using Truth Layer (caches!)
            bars = truth_layer.daily_bars(symbol, start_date, end_date)

            # History handling: tolerate list of objects or dict with 'prices'
            closes = []
            if isinstance(bars, dict):
                closes = bars.get("prices") or []
            elif isinstance(bars, list):
                closes = [b.get("close") for b in bars if b.get("close") is not None]

            # Fallback to PolygonService if TruthLayer failed or returned insufficient data
            if not closes or len(closes) < 50:
                try:
                    hist_data = market_data.get_historical_prices(symbol, days=90)
                    if hist_data and "prices" in hist_data:
                        closes = hist_data["prices"]
                        # Convert to list of dicts for RegimeEngine compatibility if needed
                        # bars = [{"close": p} for p in closes]
                        # Note: We rely on 'closes' list for SMA calc below.
                        # RegimeEngine below uses 'existing_bars=bars'. If 'bars' is from TruthLayer (empty),
                        # RegimeEngine might re-fetch or fail.
                        # Ideally we update 'bars' to match TruthLayer format for RegimeEngine reuse.
                        bars = [{"close": p} for p in closes]
                except Exception:
                    pass

            # Ensure we have enough data (need at least 50 for SMA50)
            if not closes or len(closes) < 50:
                return None

            # C. Compute Symbol Regime (Authoritative)
            # Pass existing bars to avoid redundant network call
            symbol_snapshot = regime_engine.compute_symbol_snapshot(symbol, global_snapshot, existing_bars=bars)
            effective_regime_state = regime_engine.get_effective_regime(symbol_snapshot, global_snapshot)

            iv_rank = symbol_snapshot.iv_rank or 50.0

            sma20 = np.mean(closes[-20:])
            sma50 = np.mean(closes[-50:])

            trend = "NEUTRAL"
            if closes[-1] > sma20 > sma50:
                trend = "BULLISH"
            elif closes[-1] < sma20 < sma50:
                trend = "BEARISH"

            # E. Strategy Selection
            suggestion = strategy_selector.determine_strategy(
                ticker=symbol,
                sentiment=trend,
                current_price=current_price,
                iv_rank=iv_rank,
                effective_regime=effective_regime_state.value
            )

            if suggestion["strategy"] == "HOLD":
                return None

            # F. Construct Contract & Calculate EV
            # Prefer TruthLayer (cached)
            chain = []
            chain_objects = None

            try:
                # OPTIMIZATION: Use min/max expiry to reduce data fetch size
                now_date = datetime.now().date()
                min_dte = SCANNER_MIN_DTE
                max_dte = SCANNER_MAX_DTE
                min_expiry = (now_date + timedelta(days=min_dte)).isoformat()
                max_expiry = (now_date + timedelta(days=max_dte)).isoformat()

                chain_objects = truth_layer.option_chain(symbol, min_expiry=min_expiry, max_expiry=max_expiry)
            except Exception:
                chain_objects = None

            if chain_objects:
                now_date = datetime.now().date()
                for c in chain_objects:
                    # Adapt to scanner format
                    try:
                        exp_str = c.get("expiry")
                        if not exp_str: continue

                        # Handle date parsing safely
                        try:
                            exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").date()
                        except ValueError:
                            continue

                        days_to_expiry = (exp_dt - now_date).days

                        if not (SCANNER_MIN_DTE <= days_to_expiry <= SCANNER_MAX_DTE):
                            continue

                        # Flatten structure
                        greeks = c.get("greeks") or {}
                        quote = c.get("quote") or {}

                        # Price logic: Mid -> Last -> 0
                        price = quote.get("mid")
                        if price is None:
                            price = quote.get("last")

                        chain.append({
                            "ticker": c.get("contract"),
                            "strike": c.get("strike"),
                            "expiration": exp_str,
                            "type": c.get("right"), # 'call'/'put'
                            "delta": greeks.get("delta"),
                            "gamma": greeks.get("gamma"),
                            "vega": greeks.get("vega"),
                            "theta": greeks.get("theta"),
                            "price": price,
                            "close": quote.get("last"), # fallback
                            "bid": quote.get("bid"),
                            "ask": quote.get("ask")
                        })
                    except Exception as e:
                        continue

            # Fallback if empty
            if not chain:
                chain = market_data.get_option_chain(symbol, min_dte=SCANNER_MIN_DTE, max_dte=SCANNER_MAX_DTE)

            if not chain:
                return None

            # Enforce shared expiry
            # Optimization: Select bucket and return contracts directly to avoid re-filtering
            expiry_selected, chain_subset = _select_best_expiry_chain(chain, target_dte=35)
            if not expiry_selected or not chain_subset:
                return None

            # Optimization: Sort and index chain ONCE per symbol
            # Single-pass split into calls and puts
            calls_list = []
            puts_list = []
            for c in chain_subset:
                t = c.get('type')
                if t == 'call':
                    calls_list.append(c)
                elif t == 'put':
                    puts_list.append(c)

            calls_sorted = sorted(calls_list, key=lambda x: x['strike'])
            puts_sorted = sorted(puts_list, key=lambda x: x['strike'])

            # Normalize Strategy Key early
            raw_strategy = suggestion["strategy"]
            strategy_key = raw_strategy.lower().replace(" ", "_")

            if "iron_condor" in strategy_key or "condor" in strategy_key:
                # Specialized logic for Iron Condor
                legs, total_cost = _select_iron_condor_legs(calls_sorted, puts_sorted, current_price)
                if not legs:
                     return None

                # Invariant Validation
                if not _validate_iron_condor_invariants(legs):
                    return None

                # Sanity Checks
                credit_share = abs(total_cost) if total_cost < 0 else 0.0
                if credit_share <= 0:
                    return None

                # Width Check
                calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
                puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

                width_call = abs(calls[1]["strike"] - calls[0]["strike"])
                width_put = abs(puts[1]["strike"] - puts[0]["strike"])
                width_max = max(width_call, width_put)

                if credit_share >= width_max:
                    # Credit cannot exceed width (no risk? impossible/arb)
                    return None

                if width_call <= 0 or width_put <= 0:
                    return None
            else:
                legs, total_cost = _select_legs_from_chain(calls_sorted, puts_sorted, suggestion["legs"], current_price)

            # NOTE: We recalculate legs below for risk primitives or just reuse?
            # The original code reset `legs = []` here which discards the work above!
            # Wait, looking at original code:
            # legs, total_cost = ...
            # legs = []
            # ...
            # strategy_key in ("iron_condor" ...): ... logic ...
            # else: default loop
            #
            # The original code seems to double-calculate or discard?
            # Let's check lines 400-600.
            # It seems `legs, total_cost = ...` is done, THEN `legs = []`, THEN a large block repeats logic?
            # Ah, the original code had a large block `if strategy_key ... else ...` that RE-DID selection?
            # NO, the original code I read shows:
            #   legs, total_cost = _select_legs_from_chain(...)
            #   legs = []
            #   ...
            # This looks like dead code or a mistake in the file I read.
            # Actually, looking at the file read output:
            # Line 345: if "iron_condor"...
            # Line 375: else: legs, total_cost = _select_legs_from_chain...
            # Line 377: legs = []
            # Line 378: total_cost = 0.0
            # Line 386: if strategy_key in ("iron_condor"...):
            # Line 493: else: # Default Logic (Original loop) ... iterates chain again!
            #
            # WOW. The original code computes legs, throws them away, and computes them again inline!
            # This is a HUGE performance bug.
            # I will fix this by removing the redundant re-calculation.

            # I will USE the legs computed above and REMOVE the redundant blocks below.
            # Removed redundant re-calculation block. We now use 'legs' and 'total_cost' from above.

            pricing_mode = "exact"
            data_quality = "realtime"
            total_ev = 0.0

            # Compute EV for the selected legs
            if len(legs) == 4 and ("condor" in strategy_key or "iron_condor" in strategy_key):
                 # Iron Condor EV
                 credit_share = abs(total_cost)

                 # Identify legs for EV params
                 calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
                 puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

                 if len(calls) == 2 and len(puts) == 2:
                     # calls[0] is Short Call (Lower K), calls[1] is Long Call (Higher K)
                     short_call = calls[0]
                     long_call = calls[1]

                     # puts[0] is Long Put (Lower K), puts[1] is Short Put (Higher K)
                     long_put = puts[0]
                     short_put = puts[1]

                     width_put = abs(short_put["strike"] - long_put["strike"])
                     width_call = abs(long_call["strike"] - short_call["strike"])

                     ev_obj = calculate_condor_ev(
                        credit=credit_share,
                        width_put=width_put,
                        width_call=width_call,
                        delta_short_put=short_put.get("delta", 0),
                        delta_short_call=short_call.get("delta", 0)
                     )
                     total_ev = ev_obj.expected_value
                 else:
                     total_ev = 0.0

            elif len(legs) == 2:
                long_leg = next((l for l in legs if l['side'] == 'buy'), None)
                short_leg = next((l for l in legs if l['side'] == 'sell'), None)
                if long_leg and short_leg:
                    width = abs(long_leg['strike'] - short_leg['strike'])
                    st_type = "debit_spread" if total_cost > 0 else "credit_spread"

                    if st_type == "credit_spread":
                        delta_for_ev = abs(float(short_leg.get("delta") or 0.0))
                    else:
                        delta_for_ev = abs(float(long_leg.get("delta") or 0.0))

                    ev_obj = calculate_ev(
                        premium=abs(total_cost),
                        strike=long_leg['strike'],
                        current_price=current_price,
                        delta=delta_for_ev,
                        strategy=st_type,
                        width=width
                    )
                    total_ev = ev_obj.expected_value
                else:
                    total_ev = 0
            elif len(legs) == 1:
                leg = legs[0]
                st_type = _map_single_leg_strategy(leg)
                if not st_type:
                    return None

                ev_obj = calculate_ev(
                    premium=leg['premium'],
                    strike=leg['strike'],
                    current_price=current_price,
                    delta=leg['delta'],
                    strategy=st_type
                )
                total_ev = ev_obj.expected_value

            # G. Compute Net EV & Risk Primitives
            max_loss_contract = 0.0
            max_profit_contract = 0.0
            collateral_contract = 0.0
            max_loss_per_contract = 0.0
            collateral_per_contract = 0.0

            # Net Delta (shares equiv) and Vega (contract total)
            # Vega in legs is usually per share. Multiplying by 100 gives contract exposure.
            net_delta_contract = sum((l['delta'] if l['side']=='buy' else -l['delta']) for l in legs) * 100
            net_vega_contract = sum((l['vega'] if l['side']=='buy' else -l['vega']) for l in legs) * 100

            pricing_mode = "exact"
            data_quality = "realtime"

            # Check for degraded data (missing premiums)
            if any((l.get('premium') or 0) <= 0 for l in legs):
                 data_quality = "degraded"
                 pricing_mode = "approximate"

            # Risk Primitives (New Helper handles 4 legs now)
            # EV Calculation
            if len(legs) == 4 and ("condor" in strategy_key or "iron_condor" in strategy_key):
                 # Iron Condor EV
                 credit_share = abs(total_cost)

                 # Identify legs for EV params
                 calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
                 puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

                 if len(calls) == 2 and len(puts) == 2:
                     # Short Call is lower strike (for call spread side logic in Condor? No wait.)
                     # Iron Condor:
                     # Sell Put (Higher K), Buy Put (Lower K)
                     # Sell Call (Lower K), Buy Call (Higher K)
                     # Wait, standard Iron Condor:
                     # Strikes: Long Put < Short Put < Short Call < Long Call

                     # calls[0] is Short Call (Lower K), calls[1] is Long Call (Higher K)
                     short_call = calls[0]
                     long_call = calls[1]

                     # puts[0] is Long Put (Lower K), puts[1] is Short Put (Higher K)
                     long_put = puts[0]
                     short_put = puts[1]

                     width_put = abs(short_put["strike"] - long_put["strike"])
                     width_call = abs(long_call["strike"] - short_call["strike"])

                     ev_obj = calculate_condor_ev(
                        credit=credit_share,
                        width_put=width_put,
                        width_call=width_call,
                        delta_short_put=short_put["delta"], # Should be neg
                        delta_short_call=short_call["delta"] # Should be pos
                     )
                     total_ev = ev_obj.expected_value
                 else:
                     total_ev = 0.0

            elif len(legs) == 2:
                long_leg = next((l for l in legs if l['side'] == 'buy'), None)
                short_leg = next((l for l in legs if l['side'] == 'sell'), None)
                if long_leg and short_leg:
                    width = abs(long_leg['strike'] - short_leg['strike'])
                    st_type = "debit_spread" if total_cost > 0 else "credit_spread"

                    if st_type == "credit_spread":
                        delta_for_ev = abs(float(short_leg.get("delta") or 0.0))
                    else:
                        delta_for_ev = abs(float(long_leg.get("delta") or 0.0))

                    ev_obj = calculate_ev(
                        premium=abs(total_cost),
                        strike=long_leg['strike'],
                        current_price=current_price,
                        delta=delta_for_ev,
                        strategy=st_type,
                        width=width
                    )
                    total_ev = ev_obj.expected_value
                else:
                    total_ev = 0
            elif len(legs) == 1:
                leg = legs[0]
                st_type = _map_single_leg_strategy(leg)
                if not st_type:
                    return None

                ev_obj = calculate_ev(
                    premium=leg['premium'],
                    strike=leg['strike'],
                    current_price=current_price,
                    delta=leg['delta'],
                    strategy=st_type
                )
                total_ev = ev_obj.expected_value

            # Risk Primitives (New Helper)
            primitives = _compute_risk_primitives_usd(legs, total_cost, current_price)
            max_loss_contract = primitives["max_loss_per_contract"]
            max_profit_contract = primitives["max_profit_per_contract"]
            collateral_contract = primitives["collateral_required_per_contract"]

            # NEW: Compute explicit combo width via Truth Layer
            # Fallback based on underlying spread or default
            fallback_width_share = abs(total_cost) * 0.05 # Default 5%
            if bid is not None and ask is not None and current_price and current_price > 0:
                 fallback_width_share = abs(total_cost) * ((ask - bid) / current_price)

            combo_width_share = _combo_width_share_from_legs(truth_layer, legs, fallback_width_share)

            # Compute option-spread-based pct (relative to entry)
            entry_cost_share = abs(float(total_cost or 0.0))
            option_spread_pct = (combo_width_share / entry_cost_share) if entry_cost_share > 1e-9 else 0.0

            # NEW: Liquidity Gating (Option Spread Based)
            if option_spread_pct > threshold:
                 # REJECT: Illiquid Options
                 return None

            # H. Unified Scoring
            trade_dict = {
                "ev": total_ev,
                "suggested_entry": abs(total_cost),
                "bid_ask_spread": combo_width_share,  # Uses explicit width
                "strategy": raw_strategy,
                "strategy_key": strategy_key,
                "legs": legs,
                "vega": sum(l['vega'] if l['side']=='buy' else -l['vega'] for l in legs),
                "gamma": sum(l['gamma'] if l['side']=='buy' else -l['gamma'] for l in legs),
                "iv_rank": iv_rank,
                "type": "debit" if total_cost > 0 else "credit",
                # Pass primitives for scoring if needed
                "max_loss": max_loss_contract
            }

            # Determine Execution Cost
            cost_details = _determine_execution_cost(
                drag_map=drag_map,
                symbol=symbol,
                combo_width_share=combo_width_share,
                num_legs=len(legs)
            )
            expected_execution_cost = cost_details["expected_execution_cost"]

            unified_score = calculate_unified_score(
                trade=trade_dict,
                regime_snapshot=global_snapshot.to_dict(),
                market_data={"bid_ask_spread_pct": option_spread_pct}, # Uses option_spread_pct
                execution_drag_estimate=expected_execution_cost,
                num_legs=len(legs),
                entry_cost=abs(total_cost)
            )

            # Retrieve final execution cost (contract dollars) from UnifiedScore
            final_execution_cost = unified_score.execution_cost_dollars

            # Requirement: Hard-reject if execution cost > EV
            # Use expected_execution_cost as per instruction
            if expected_execution_cost >= total_ev:
                return None

            # --- Earnings Awareness Logic ---
            earnings_val = earnings_map.get(symbol)
            days_to_earnings = None
            earnings_risk = False
            earnings_penalty_val = 0.0

            if earnings_val:
                try:
                    # Support datetime object or YYYY-MM-DD string
                    earnings_dt = None
                    if isinstance(earnings_val, datetime):
                        earnings_dt = earnings_val
                    elif isinstance(earnings_val, str):
                        earnings_dt = datetime.fromisoformat(earnings_val)

                    if earnings_dt:
                        # Use now() as scanner is live.
                        now_dt = datetime.now()
                        days_to_earnings = (earnings_dt.date() - now_dt.date()).days

                        # Normalize strategy key for safety checks (already lowercased above but ensuring consistency)
                        safe_strategy_key = strategy_key.lower()

                        # 1. Hard Reject: Short Premium within 2 days
                        if days_to_earnings <= 2:
                            is_short_premium = ("credit" in safe_strategy_key) or ("condor" in safe_strategy_key) or ("short" in safe_strategy_key)
                            if is_short_premium:
                                return None

                        # 2. Score Penalty: Within 7 days
                        if days_to_earnings <= 7:
                            earnings_risk = True
                            earnings_penalty_val = earnings_week_penalty(safe_strategy_key)

                            # Apply penalty
                            unified_score.score = max(0.0, unified_score.score - earnings_penalty_val)
                            # Add badge/warning to unified score object if possible, or handle locally
                            unified_score.badges.append("EARNINGS_RISK")

                except Exception as e:
                    print(f"[Scanner] Earnings date parse error for {symbol}: {e}")

            candidate_dict = {
                "symbol": symbol,
                "ticker": symbol,
                "type": suggestion["strategy"],
                "strategy": suggestion["strategy"],
                "strategy_key": strategy_key,
                "suggested_entry": abs(total_cost),
                "ev": total_ev,
                "score": round(unified_score.score, 1),
                "unified_score_details": unified_score.components.model_dump(),
                "iv_rank": iv_rank,
                "trend": trend,
                "legs": legs,
                "badges": unified_score.badges,
                "execution_drag_estimate": expected_execution_cost,
                "execution_drag_samples": cost_details["execution_cost_samples_used"],
                "execution_drag_source": cost_details["execution_drag_source"],
                "execution_cost_source_used": cost_details["execution_cost_samples_used"],
                "execution_cost_samples_used": cost_details["execution_cost_samples_used"],
                # Risk Primitives
                "max_loss_per_contract": max_loss_contract,
                "max_profit_per_contract": max_profit_contract,
                "collateral_required_per_contract": collateral_contract,
                "collateral_per_contract": collateral_contract,
                "net_delta_per_contract": net_delta_contract,
                "net_vega_per_contract": net_vega_contract,
                "data_quality": data_quality,
                "pricing_mode": pricing_mode,
                # Earnings Metadata
                "earnings_date": str(earnings_val) if earnings_val else None,
                "days_to_earnings": days_to_earnings,
                "earnings_risk": earnings_risk,
                "earnings_penalty": earnings_penalty_val
            }

            # Calculate Probability of Profit
            # Pass dictionary representation of global snapshot for compatibility
            gs_dict = global_snapshot.to_dict() if global_snapshot else None

            pop = None
            if ev_obj is not None and hasattr(ev_obj, "win_probability"):
                pop = float(ev_obj.win_probability)
            elif ev_obj is not None and isinstance(ev_obj, dict) and "win_probability" in ev_obj:
                pop = float(ev_obj["win_probability"])

            if pop is not None:
                pop = max(0.0, min(1.0, pop))
                candidate_dict["probability_of_profit"] = pop
                candidate_dict["probability_of_profit_source"] = "ev"
            else:
                candidate_dict["probability_of_profit"] = _estimate_probability_of_profit(candidate_dict, gs_dict)
                candidate_dict["probability_of_profit_source"] = "score_fallback"

            return candidate_dict

        except Exception as e:
            print(f"[Scanner] Error processing {symbol}: {e}")
            return None

    # Corrected Indentation: ThreadPoolExecutor is now OUTSIDE process_symbol
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_to_symbol = {
            executor.submit(process_symbol, sym, drag_map, quotes_map, earnings_map): sym
            for sym in symbols
        }

        for future in concurrent.futures.as_completed(future_to_symbol):
            sym = future_to_symbol[future]
            try:
                result = future.result()
                if result:
                    candidates.append(result)
            except Exception as exc:
                print(f"[Scanner] Exception in thread for {sym}: {exc}")

    # Sort by Unified Score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    return candidates
