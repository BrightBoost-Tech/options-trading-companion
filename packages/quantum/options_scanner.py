import os
import math
import requests
import numpy as np
import operator
import threading
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional, Tuple
from supabase import Client
import logging
import concurrent.futures
from collections import defaultdict
from functools import lru_cache
from bisect import bisect_left

from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.analytics.strategy_policy import StrategyPolicy
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
from packages.quantum.services.earnings_calendar_service import EarningsCalendarService
from packages.quantum.agents.runner import AgentRunner, build_agent_pipeline

# Surface V4 integration (optional, gated by env)
def _is_surface_v4_enabled() -> bool:
    """Check if Surface V4 hook is enabled."""
    return os.getenv("SURFACE_V4_ENABLE", "").lower() in ("1", "true", "yes")

def _get_surface_v4_policy() -> str:
    """Get Surface V4 policy: 'off', 'observe', or 'skip'."""
    return os.getenv("SURFACE_V4_POLICY", "observe").lower()

def _get_surface_v4_strike_range() -> float:
    """Get Surface V4 strike range as fraction of spot (default 0.20 = ±20%)."""
    return float(os.getenv("SURFACE_V4_STRIKE_RANGE", "0.20"))

# Configuration
SCANNER_LIMIT_DEV = int(os.getenv("SCANNER_LIMIT_DEV", "40")) # Limit universe in dev
SCANNER_MIN_DTE = 25
SCANNER_MAX_DTE = 45

logger = logging.getLogger(__name__)


class RejectionStats:
    """Thread-safe rejection statistics tracker for scanner diagnostics."""

    # Default cap for rejection samples (can be overridden via env var)
    DEFAULT_SAMPLES_CAP = 3

    def __init__(self):
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self.symbols_processed = 0
        self.chains_loaded = 0
        self.chains_empty = 0
        self._samples: List[Dict[str, Any]] = []
        self._samples_cap: int = int(os.getenv("REJECTION_SAMPLES_CAP", str(self.DEFAULT_SAMPLES_CAP)))

    def record(self, reason: str) -> None:
        """Record a rejection reason (thread-safe)."""
        with self._lock:
            self._counts[reason] += 1

    def record_with_sample(self, reason: str, sample: Dict[str, Any]) -> None:
        """
        Record a rejection reason with a diagnostic sample (thread-safe).

        Args:
            reason: The rejection reason key (e.g., 'condor_no_credit')
            sample: A dict containing diagnostic info (must be JSON-serializable)
        """
        with self._lock:
            self._counts[reason] += 1
            if len(self._samples) < self._samples_cap:
                # Ensure sample includes the reason
                safe_sample = self._make_json_safe(sample)
                safe_sample["reason"] = reason
                self._samples.append(safe_sample)

    @staticmethod
    def _make_json_safe(obj: Any) -> Any:
        """Recursively convert objects to JSON-serializable types."""
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (str, int, float)):
            return obj
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, (list, tuple)):
            return [RejectionStats._make_json_safe(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): RejectionStats._make_json_safe(v) for k, v in obj.items()}
        return str(obj)

    def increment_processed(self) -> None:
        """Increment symbols processed counter."""
        with self._lock:
            self.symbols_processed += 1

    def increment_chains_loaded(self) -> None:
        """Increment chains loaded counter."""
        with self._lock:
            self.chains_loaded += 1

    def increment_chains_empty(self) -> None:
        """Increment chains empty counter."""
        with self._lock:
            self.chains_empty += 1

    def to_dict(self) -> Dict[str, Any]:
        """Return rejection stats as a dictionary."""
        with self._lock:
            return {
                "rejection_counts": dict(self._counts),
                "symbols_processed": self.symbols_processed,
                "chains_loaded": self.chains_loaded,
                "chains_empty": self.chains_empty,
                "total_rejections": sum(self._counts.values()),
                "rejection_samples": list(self._samples),
                "rejection_samples_cap": self._samples_cap,
            }

    def top_reasons(self, n: int = 5) -> List[Tuple[str, int]]:
        """Return top N rejection reasons sorted by count descending."""
        with self._lock:
            sorted_items = sorted(self._counts.items(), key=lambda x: x[1], reverse=True)
            return sorted_items[:n]


def _to_float_or_none(val: Any) -> Optional[float]:
    """Convert value to float or None if invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _build_condor_rejection_sample(
    symbol: str,
    strategy_key: str,
    expiry_selected: Optional[str],
    legs: List[Dict[str, Any]],
    total_cost: Optional[float],
    calls_count: int = 0,
    puts_count: int = 0,
) -> Dict[str, Any]:
    """
    Build a diagnostic sample for condor rejection.

    Args:
        symbol: The underlying symbol
        strategy_key: The strategy key (e.g., 'iron_condor')
        expiry_selected: The selected expiry date (or None)
        legs: List of leg dicts (may be empty for legs_not_found)
        total_cost: The computed total cost (negative for credit, None if legs not found)
        calls_count: Number of calls in chain (for diagnostics)
        puts_count: Number of puts in chain (for diagnostics)

    Returns:
        A JSON-safe sample dict with diagnostic info
    """
    # Extract strikes from legs
    strikes = sorted([float(leg.get("strike", 0)) for leg in legs]) if legs else []

    # Build compact leg info
    leg_samples = []
    legs_with_missing_quotes = []

    for leg in legs:
        bid = _to_float_or_none(leg.get("bid"))
        ask = _to_float_or_none(leg.get("ask"))
        mid = _to_float_or_none(leg.get("mid") or leg.get("premium"))

        leg_sample = {
            "symbol": str(leg.get("symbol") or ""),
            "type": leg.get("type"),
            "side": leg.get("side"),
            "strike": _to_float_or_none(leg.get("strike")),
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "premium": _to_float_or_none(leg.get("premium")),
        }
        leg_samples.append(leg_sample)

        # Track legs with missing quotes
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            legs_with_missing_quotes.append(str(leg.get("symbol") or "unknown"))

    # Compute net credit
    net_credit = None
    if total_cost is not None:
        net_credit = -total_cost if total_cost < 0 else 0.0

    # Ensure expiry is a string
    expiry_str = None
    if expiry_selected is not None:
        expiry_str = str(expiry_selected) if not isinstance(expiry_selected, str) else expiry_selected

    return {
        "symbol": symbol,
        "strategy_key": strategy_key,
        "expiry": expiry_str,
        "strikes": strikes,
        "legs": leg_samples,
        "legs_expected": 4,
        "legs_found": len(legs),
        "total_cost_share": _to_float_or_none(total_cost),
        "net_credit_share": _to_float_or_none(net_credit),
        "legs_with_missing_quotes": legs_with_missing_quotes,
        "chain_calls_count": calls_count,
        "chain_puts_count": puts_count,
    }


def _leg_has_valid_bidask(leg: Dict[str, Any]) -> bool:
    """
    Check if a leg has valid bid/ask quotes for execution.
    Returns True only if bid > 0, ask > 0, and ask >= bid.
    """
    try:
        bid = leg.get("bid")
        ask = leg.get("ask")
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


def _hydrate_legs_quotes_v4(
    truth_layer,
    legs: List[Dict[str, Any]],
    market_data: Optional[PolygonService] = None
) -> Dict[str, Any]:
    """
    Attempt to hydrate missing leg quotes using MarketDataTruthLayer.snapshot_many_v4().

    If v4 snapshots don't provide valid bid/ask, falls back to market_data.get_recent_quote()
    which uses Polygon's /v3/quotes endpoint for individual option tickers.

    Only fetches quotes for the specific leg option tickers (max 4 for condor).
    Updates leg dicts in place with hydrated bid/ask/mid/premium.

    Returns metadata dict with:
        - hydrated: count of legs that were updated
        - missing_after: list of leg symbols still missing valid quotes
        - quality: list of quality info for each leg (capped)
        - fallback: dict with fallback attempt info (if used)
    """
    if not legs:
        return {"hydrated": 0, "missing_after": [], "quality": []}

    # Collect leg symbols
    leg_syms = [leg.get("symbol") for leg in legs if leg.get("symbol")]
    if not leg_syms:
        return {"hydrated": 0, "missing_after": [], "quality": []}

    # Fetch v4 snapshots for leg tickers
    try:
        v4_snaps = truth_layer.snapshot_many_v4(leg_syms) or {}
    except Exception:
        v4_snaps = {}

    hydrated_count = 0
    quality_info = []

    for leg in legs:
        sym = leg.get("symbol")
        if not sym:
            continue

        # Try normalized key first, then raw symbol
        key = truth_layer.normalize_symbol(sym) if hasattr(truth_layer, "normalize_symbol") else sym
        snap = v4_snaps.get(key) or v4_snaps.get(sym)

        if not snap:
            continue

        # Extract quote from v4 snapshot
        q = snap.quote if hasattr(snap, "quote") else None
        if not q:
            continue

        # Track quality info (cap at 6 entries)
        if len(quality_info) < 6 and hasattr(snap, "quality"):
            qual = snap.quality
            quality_info.append({
                "symbol": sym,
                "quality_score": _to_float_or_none(getattr(qual, "quality_score", None)),
                "is_stale": getattr(qual, "is_stale", None),
                "issues": getattr(qual, "issues", [])[:3] if hasattr(qual, "issues") else [],
            })

        updated = False

        # Update bid if missing/invalid
        q_bid = getattr(q, "bid", None)
        if q_bid is not None:
            try:
                q_bid_f = float(q_bid)
                if q_bid_f > 0:
                    leg_bid = leg.get("bid")
                    if leg_bid is None or float(leg_bid) <= 0:
                        leg["bid"] = q_bid_f
                        updated = True
            except (TypeError, ValueError):
                pass

        # Update ask if missing/invalid
        q_ask = getattr(q, "ask", None)
        if q_ask is not None:
            try:
                q_ask_f = float(q_ask)
                if q_ask_f > 0:
                    leg_ask = leg.get("ask")
                    if leg_ask is None or float(leg_ask) <= 0:
                        leg["ask"] = q_ask_f
                        updated = True
            except (TypeError, ValueError):
                pass

        # Compute mid from hydrated or existing bid/ask
        q_mid = getattr(q, "mid", None)
        pref_mid = None
        if q_mid is not None:
            try:
                q_mid_f = float(q_mid)
                if q_mid_f > 0:
                    pref_mid = q_mid_f
            except (TypeError, ValueError):
                pass

        if pref_mid is None and _leg_has_valid_bidask(leg):
            # Compute from bid/ask
            pref_mid = (float(leg["bid"]) + float(leg["ask"])) / 2.0

        if pref_mid is not None and pref_mid > 0:
            leg["mid"] = pref_mid
            leg["premium"] = pref_mid
            updated = True

        if updated:
            hydrated_count += 1

    # Collect symbols still missing valid quotes after v4 snapshot
    missing_after_v4 = [
        leg.get("symbol") for leg in legs
        if not _leg_has_valid_bidask(leg)
    ]

    # Fallback: Use /v3/quotes for legs still missing valid bid/ask
    fallback_meta = None
    if missing_after_v4 and market_data is not None:
        fallback_attempted = 0
        fallback_hydrated = 0
        fallback_still_missing = []

        for leg in legs:
            sym = leg.get("symbol")
            if not sym or _leg_has_valid_bidask(leg):
                continue

            # Only fetch for option symbols (O: prefix)
            if not sym.startswith("O:"):
                fallback_still_missing.append(sym)
                continue

            fallback_attempted += 1
            try:
                q = market_data.get_recent_quote(sym)
                # Support multiple key formats
                bid = q.get("bid") or q.get("bid_price") or 0.0
                ask = q.get("ask") or q.get("ask_price") or 0.0

                if bid > 0 and ask > 0 and ask >= bid:
                    mid = (bid + ask) / 2.0
                    leg["bid"] = bid
                    leg["ask"] = ask
                    leg["mid"] = mid
                    leg["premium"] = mid
                    fallback_hydrated += 1
                    hydrated_count += 1
                else:
                    fallback_still_missing.append(sym)
            except Exception:
                fallback_still_missing.append(sym)

        fallback_meta = {
            "source": "polygon_v3_quotes",
            "attempted": fallback_attempted,
            "hydrated": fallback_hydrated,
            "still_missing": fallback_still_missing,
        }

    # Final list of symbols still missing valid quotes
    missing_after = [
        leg.get("symbol") for leg in legs
        if not _leg_has_valid_bidask(leg)
    ]

    result = {
        "hydrated": hydrated_count,
        "missing_after": missing_after,
        "quality": quality_info,
    }

    if fallback_meta:
        result["fallback"] = fallback_meta

    return result


def _reprice_total_cost_from_legs(legs: List[Dict[str, Any]]) -> Optional[float]:
    """
    Recompute total cost from leg mid/premium values.

    Returns None if any leg is missing a valid premium (> 0).
    For buy legs, adds to cost. For sell legs, subtracts from cost.
    """
    if not legs:
        return None

    total = 0.0
    for leg in legs:
        prem = leg.get("mid") or leg.get("premium")
        if prem is None:
            return None
        try:
            prem_f = float(prem)
            if prem_f <= 0:
                return None
        except (TypeError, ValueError):
            return None

        side = leg.get("side")
        if side == "buy":
            total += prem_f
        else:
            total -= prem_f

    return total


# Bolt Optimization: Cache expiry date parsing
# Using maxsize=4096 to prevent unbounded memory growth while keeping cache hot
@lru_cache(maxsize=4096)
def parse_expiry_date(exp_str: str) -> date:
    try:
        return datetime.fromisoformat(exp_str).date()
    except ValueError:
        return datetime.strptime(exp_str, "%Y-%m-%d").date()

# Bolt Optimization: Module-level accessor functions to avoid closure overhead
# Nested Schema Accessors (TruthLayer)
def _get_delta_nested(c):
    g = c.get("greeks")
    return g.get("delta") if g else None

def _get_gamma_nested(c):
    g = c.get("greeks")
    return g.get("gamma") if g else 0.0

def _get_vega_nested(c):
    g = c.get("greeks")
    return g.get("vega") if g else 0.0

def _get_theta_nested(c):
    g = c.get("greeks")
    return g.get("theta") if g else 0.0

def _get_ticker_nested(c):
    return c.get("contract")

def _get_expiry_nested(c):
    return c.get("expiry")

def _get_bid_nested(c):
    q = c.get("quote")
    return q.get("bid") if q else None

def _get_ask_nested(c):
    q = c.get("quote")
    return q.get("ask") if q else None

def _get_premium_nested(c):
    """
    Get premium from nested quote structure.
    Returns mid if > 0, else last if > 0, else None.
    Zero values are treated as missing/invalid.
    """
    q = c.get("quote")
    if not q:
        return None
    try:
        mid = q.get("mid")
        if mid is not None and float(mid) > 0:
            return float(mid)
        last = q.get("last")
        if last is not None and float(last) > 0:
            return float(last)
    except (TypeError, ValueError):
        pass
    return None

# Flat Schema Accessors (PolygonService)
def _get_delta_flat(c):
    return c.get("delta")

def _get_gamma_flat(c):
    return c.get("gamma")

def _get_vega_flat(c):
    return c.get("vega")

def _get_theta_flat(c):
    return c.get("theta")

def _get_ticker_flat(c):
    return c.get("ticker")

def _get_expiry_flat(c):
    return c.get("expiration")

def _get_bid_flat(c):
    return c.get("bid")

def _get_ask_flat(c):
    return c.get("ask")

def _get_premium_flat(c):
    return c.get("price") or c.get("close")

def _apply_agent_constraints(candidate: Dict[str, Any], portfolio_cash: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """
    Applies agent veto and constraints to the candidate.
    Resolves conflicting constraints using precedence rules.
    Returns the modified candidate (with active_constraints updated) or None if rejected.
    """
    summary = candidate.get("agent_summary")
    if not summary:
        return candidate # No agents ran, pass

    if summary.get("vetoed"):
        return None

    signals = candidate.get("agent_signals", {})

    # Resolve Constraints with Precedence
    # 1. liquidity.max_spread_pct -> MIN (Strictest)
    # 2. event.require_defined_risk -> ANY (True if any agent requires it)
    # 3. liquidity.require_limit_orders -> ANY (True if any agent requires it)

    max_spread_values = []
    require_defined_risk = False
    require_limit_orders = False

    for signal in signals.values():
        meta = signal.get("metadata", {})
        constraints = meta.get("constraints", {})

        if "liquidity.max_spread_pct" in constraints:
            max_spread_values.append(constraints["liquidity.max_spread_pct"])

        if constraints.get("event.require_defined_risk"):
            require_defined_risk = True

        if constraints.get("liquidity.require_limit_orders"):
            require_limit_orders = True

    # Apply Precedence
    effective_max_spread = min(max_spread_values) if max_spread_values else None

    # Update summary with EFFECTIVE constraints for transparency
    # We update the candidate in place
    candidate["agent_summary"]["active_constraints"] = {
        "event.require_defined_risk": require_defined_risk,
        "liquidity.require_limit_orders": require_limit_orders,
    }
    if effective_max_spread is not None:
        candidate["agent_summary"]["active_constraints"]["liquidity.max_spread_pct"] = effective_max_spread

    # --- ENFORCE CONSTRAINTS ---

    # 1. Defined Risk
    if require_defined_risk:
        # Check if strategy is defined risk.
        # Criteria:
        # 1. Reject if max_loss is infinite (e.g., Naked Calls).
        # 2. If Short Put (single leg), ALLOW ONLY IF Cash Secured (CSP).
        #    - Must have portfolio_cash available.
        #    - collateral_required <= portfolio_cash.
        # 3. Allow Spreads and Long Options.

        if candidate.get("max_loss_per_contract") == float("inf"):
            # Naked Short Call or similar infinite risk
            return None

        strategy_key = candidate.get("strategy_key", "")
        is_single_short = "short" in strategy_key and "spread" not in strategy_key and "condor" not in strategy_key

        if is_single_short:
            # Short Put logic (since Short Call is caught by max_loss=inf check above, generally)
            # Just in case Short Call slipped through max_loss check (unlikely), explicitly check strategy
            if "call" in strategy_key:
                return None

            # It is a Short Put. Check for CSP capability.
            # "allow short puts (single-leg) -> allowed only if collateral_required_per_contract * contracts <= available_cash_cap"
            # In scanner, we assume contracts=1 for feasibility check.

            collateral = candidate.get("collateral_required_per_contract")

            if collateral is None:
                # "missing collateral fields -> conservative reject with reason missing_collateral"
                return None

            if portfolio_cash is None:
                # "portfolio cash unknown -> conservative reject for CSP path"
                return None

            # Check if we can afford at least 1 contract
            # contracts > 1 uses total collateral is handled in sizing,
            # here we check if the trade is theoretically possible as a CSP.
            if collateral > portfolio_cash:
                return None

            # If we passed checks, it is a CSP (Defined Risk via Cash Security). Allowed.
            pass

    # 2. Max Spread
    if effective_max_spread is not None:
        current_spread = candidate.get("option_spread_pct", 0.0)
        if current_spread > effective_max_spread:
            return None

    # 3. Limit Orders
    if require_limit_orders:
        candidate["order_type_force_limit"] = True

    return candidate


def _select_best_expiry_chain(chain: List[Dict[str, Any]], target_dte: int = 35, today_date: date = None) -> tuple[Optional[str], List[Dict[str, Any]]]:
    if not chain:
        return None, []

    # Bolt Optimization: Detect expiry key once
    # Use defaultdict for cleaner and faster grouping (approx 10-15% speedup on large lists)
    buckets = defaultdict(list)

    # Detect key from first element if available
    exp_key = "expiration"
    if chain:
        if "expiry" in chain[0]:
            exp_key = "expiry"

    for c in chain:
        # Support canonical format (expiry) fallback
        exp = c.get(exp_key)
        if exp:
            buckets[exp].append(c)

    if not buckets:
        return None, []

    # Helper to get DTE diff
    # Bolt Optimization: Lift now() out of closure. Passed in or calculated once.
    if today_date is None:
        today_date = datetime.now().date()

    # Bolt Optimization: Use cached date parser
    def get_dte_diff(exp_str):
        try:
            exp_dt = parse_expiry_date(exp_str)
            return abs((exp_dt - today_date).days - target_dte)
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

    Bolt Optimization: Supports both Flat (PolygonService) and Nested (TruthLayer) schemas
    to avoid O(N) flattening overhead.
    """
    legs = []
    total_cost = 0.0

    # Schema Detection (Bolt Optimization)
    sample = calls[0] if calls else (puts[0] if puts else None)
    is_nested = sample is not None and "greeks" in sample and isinstance(sample.get("greeks"), dict)

    # Optimized Accessors definition using module-level functions
    if is_nested:
        _delta = _get_delta_nested
        _gamma = _get_gamma_nested
        _vega = _get_vega_nested
        _theta = _get_theta_nested
        _ticker = _get_ticker_nested
        _expiry = _get_expiry_nested
        _bid = _get_bid_nested
        _ask = _get_ask_nested
        _premium = _get_premium_nested
    else:
        _delta = _get_delta_flat
        _gamma = _get_gamma_flat
        _vega = _get_vega_flat
        _theta = _get_theta_flat
        _ticker = _get_ticker_flat
        _expiry = _get_expiry_flat
        _bid = _get_bid_flat
        _ask = _get_ask_flat
        _premium = _get_premium_flat

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

        # Bolt Optimization: Check first element (O(1)) instead of scanning all (O(N))
        # Assumes homogeneity in chain data (if one has greeks, all usually do)
        has_delta = candidates and _delta(candidates[0]) is not None

        if has_delta:
            target_d = abs(target_delta)

            # Bolt Optimization: Use bisect (O(log N)) instead of min scan (O(N))
            # Candidates sorted by strike.
            # Calls: Delta decreases with strike. Negate delta to make ascending.
            # Puts: Abs(Delta) increases with strike. Use as is.

            if op_type == "call":
                # Descending (0.9 -> 0.1) -> Ascending (-0.9 -> -0.1)
                key_func = lambda x: -abs(_delta(x) or 0)
                target_val = -target_d
            else:
                # Ascending (0.1 -> 0.9)
                key_func = lambda x: abs(_delta(x) or 0)
                target_val = target_d

            # Find insertion point
            idx = bisect_left(candidates, target_val, key=key_func)

            # Find closest neighbor (idx-1 or idx)
            best_contract = candidates[0]
            best_diff = float('inf')

            # Check left neighbor
            if idx > 0:
                c = candidates[idx - 1]
                diff = abs(abs(_delta(c) or 0) - target_d)
                if diff < best_diff:
                    best_diff = diff
                    best_contract = c

            # Check right neighbor (insertion point)
            if idx < len(candidates):
                c = candidates[idx]
                diff = abs(abs(_delta(c) or 0) - target_d)
                if diff < best_diff:
                    best_diff = diff
                    best_contract = c
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
            # Strike is always at top level
            best_contract = min(candidates, key=lambda x: abs(x['strike'] - target_k))

        premium = _premium(best_contract) or 0.0

        bid = _bid(best_contract)
        ask = _ask(best_contract)
        mid = None
        if bid is not None and ask is not None:
             mid = (float(bid) + float(ask)) / 2.0

        legs.append({
            "symbol": _ticker(best_contract),
            "strike": best_contract['strike'],
            "expiry": _expiry(best_contract),
            "type": op_type,
            "side": side,
            "premium": premium,
            "delta": _delta(best_contract) or target_delta,
            "gamma": _gamma(best_contract) or 0.0,
            "vega": _vega(best_contract) or 0.0,
            "theta": _theta(best_contract) or 0.0,
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

    Bolt Optimization: Supports both Flat (PolygonService) and Nested (TruthLayer) schemas
    """
    legs = []
    total_cost = 0.0

    if not calls or not puts:
        return [], 0.0

    # Schema Detection (Bolt Optimization)
    sample = calls[0] if calls else (puts[0] if puts else None)
    is_nested = sample is not None and "greeks" in sample and isinstance(sample.get("greeks"), dict)

    # Optimized Accessors definition using module-level functions
    if is_nested:
        _delta = _get_delta_nested
        _gamma = _get_gamma_nested
        _vega = _get_vega_nested
        _theta = _get_theta_nested
        _ticker = _get_ticker_nested
        _expiry = _get_expiry_nested
        _bid = _get_bid_nested
        _ask = _get_ask_nested
        _premium = _get_premium_nested
    else:
        _delta = _get_delta_flat
        _gamma = _get_gamma_flat
        _vega = _get_vega_flat
        _theta = _get_theta_flat
        _ticker = _get_ticker_flat
        _expiry = _get_expiry_flat
        _bid = _get_bid_flat
        _ask = _get_ask_flat
        _premium = _get_premium_flat

    # 2. Select Shorts by Delta
    # Target delta is usually ~0.15 (abs)
    # Short Call: delta ~ 0.15
    short_call = min(calls, key=lambda x: abs(abs(_delta(x) or 0) - target_delta))
    # Short Put: delta ~ -0.15
    short_put = min(puts, key=lambda x: abs(abs(_delta(x) or 0) - target_delta))

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
        (short_put, "sell", "put"),
        (long_put, "buy", "put"),
        (short_call, "sell", "call"),
        (long_call, "buy", "call")
    ]

    for contract, side, type_hint in selected_contracts:
        # Use mid from bid/ask if available, otherwise 'price'/'close'
        bid = _bid(contract)
        ask = _ask(contract)
        mid_calc = None
        if bid is not None and ask is not None and ask >= bid:
            mid_calc = (float(bid) + float(ask)) / 2.0

        premium = mid_calc if mid_calc is not None else (_premium(contract) or 0.0)

        leg = {
            "symbol": _ticker(contract),
            "strike": contract['strike'],
            "expiry": _expiry(contract),
            "type": contract.get('type') or contract.get('right') or type_hint,
            "side": side,
            "premium": premium,
            "delta": _delta(contract) or 0.0,
            "gamma": _gamma(contract) or 0.0,
            "vega": _vega(contract) or 0.0,
            "theta": _theta(contract) or 0.0,
            # Pass through bid/ask for width calculation later
            "bid": bid,
            "ask": ask,
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
    # Bolt Optimization: Use math.exp for scalar (2.6x faster than np.exp)
    p = 1.0 / (1.0 + math.exp(-(score - 50.0) / 12.0))

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
    # Bolt Optimization: Use python max/min for scalar (10x faster than np.clip)
    return max(0.01, min(0.99, float(p)))

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
    global_snapshot: GlobalRegimeSnapshot = None,
    banned_strategies: List[str] = None,
    portfolio_cash: float = None
) -> Tuple[List[Dict[str, Any]], RejectionStats]:
    """
    Scans the provided symbols (or universe) for option trade opportunities.
    Returns a tuple of (candidates, rejection_stats) for diagnostics.

    Output Schema (candidates):
    - symbol, ticker, strategy, ev, score
    - max_loss_per_contract (USD)
    - max_profit_per_contract (USD)
    - collateral_required_per_contract (USD)
    - net_delta_per_contract (shares-equivalent)
    - net_vega_per_contract (USD per 1% vol change per contract)
    - data_quality: "realtime" | "degraded"
    - pricing_mode: "exact" | "approximate"

    Output (rejection_stats):
    - rejection_counts: Dict[str, int] - histogram of rejection reasons
    - symbols_processed: int
    - chains_loaded: int
    - chains_empty: int
    """
    candidates = []
    rejection_stats = RejectionStats()

    # Initialize services
    market_data = PolygonService()
    strategy_selector = StrategySelector()
    policy = StrategyPolicy(banned_strategies)
    universe_service = UniverseService(supabase_client) if supabase_client else None
    execution_service = ExecutionService(supabase_client) if supabase_client else None
    earnings_service = EarningsCalendarService(market_data)

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
                # Prefill from Universe if available
                earnings_map = {u["symbol"]: u.get("earnings_date") for u in universe}
            except Exception as e:
                print(f"[Scanner] UniverseService failed: {e}. Using fallback.")
                symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
        else:
             symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]

    # Bolt Optimization: Normalize and deduplicate symbols upfront
    # This avoids repeated regex calls inside the hot loop and ensures consistency
    if hasattr(truth_layer, "normalize_symbol"):
        symbols = sorted(list(set([truth_layer.normalize_symbol(s) for s in symbols])))

    # Dev mode limit
    if os.getenv("APP_ENV") != "production":
        symbols = symbols[:SCANNER_LIMIT_DEV]

    print(f"[Scanner] Processing {len(symbols)} symbols...")

    # Enrich Earnings Map via Service (Batch)
    try:
        # Find symbols missing earnings in Universe map
        missing_earnings = [s for s in symbols if not earnings_map.get(s)]
        if missing_earnings:
             logger.info(f"[Scanner] Fetching earnings for {len(missing_earnings)} symbols...")
             fetched_map = earnings_service.get_earnings_map(missing_earnings)

             # Merge into main map (convert date objects to string if needed, or keep as obj)
             # Note: Universe map has strings (from DB), Service returns date objects.
             # We unify to date objects or strings? Scanner logic below handles both.
             # But let's keep it consistent if possible.
             for s, d in fetched_map.items():
                 earnings_map[s] = d # Store date object directly, logic handles it.
    except Exception as e:
        logger.warning(f"[Scanner] Earnings batch fetch failed: {e}")

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

    # Batch Fetch IV Context (Bolt Optimization)
    iv_context_map = {}
    if regime_engine.iv_repo:
        try:
            logger.info(f"[Scanner] Batch fetching IV context for {len(symbols)} symbols...")
            iv_context_map = regime_engine.iv_repo.get_iv_context_batch(symbols)
        except Exception as e:
            print(f"[Scanner] Failed to batch fetch IV context: {e}")

    # 3. Parallel Processing
    batch_size = 20 # Increased from 5 to 20 to improve I/O throughput (Bolt Optimization)

    # 3a. Batch Fetch Quotes (Optimization)
    # Fetch all quotes in one go to avoid N requests inside the loop
    # truth_layer.snapshot_many handles batching automatically
    logger.info(f"[Scanner] Batch fetching quotes for {len(symbols)} symbols...")
    quotes_map = truth_layer.snapshot_many(symbols)

    # Bolt Optimization: Hoist invariant calculations out of the inner loop
    now_dt = datetime.now()
    today_date = now_dt.date()
    min_dte = SCANNER_MIN_DTE
    max_dte = SCANNER_MAX_DTE
    min_expiry = (today_date + timedelta(days=min_dte)).isoformat()
    max_expiry = (today_date + timedelta(days=max_dte)).isoformat()

    # Technical Analysis Time Window (Shared)
    # Reusing end_date as now_dt for consistency
    ta_end_date = now_dt
    ta_start_date = ta_end_date - timedelta(days=90)

    def process_symbol(symbol: str, drag_map: Dict[str, Any], quotes_map: Dict[str, Any], earnings_map: Dict[str, Any], iv_context: Dict[str, Any], rej_stats: RejectionStats) -> Optional[Dict[str, Any]]:
        """Process a single symbol and return a candidate dict or None."""
        rej_stats.increment_processed()
        try:
            # A. Enrich Data
            # Use batched quote from map
            # Bolt Optimization: Symbol is already normalized upfront, use directly
            snapshot_item = quotes_map.get(symbol)

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

            if not current_price:
                rej_stats.record("missing_quotes")
                return None

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
            # Bolt Optimization: Use hoisted dates (ta_start_date, ta_end_date)

            # Fetch using Truth Layer (caches!)
            bars = truth_layer.daily_bars(symbol, ta_start_date, ta_end_date)

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
                rej_stats.record("insufficient_history")
                return None

            # C. Compute Symbol Regime (Authoritative)
            # Pass existing bars to avoid redundant network call
            # Use pre-fetched IV context (Bolt Optimization)
            iv_context = iv_context_map.get(symbol) if iv_context_map else None
            symbol_snapshot = regime_engine.compute_symbol_snapshot(symbol, global_snapshot, existing_bars=bars, iv_context=iv_context)
            effective_regime_state = regime_engine.get_effective_regime(symbol_snapshot, global_snapshot)

            iv_rank = symbol_snapshot.iv_rank or 50.0

            # Bolt Optimization: Use sum() / len() for small lists (20x faster than np.mean)
            s20 = closes[-20:]
            s50 = closes[-50:]
            sma20 = sum(s20) / len(s20) if s20 else 0.0
            sma50 = sum(s50) / len(s50) if s50 else 0.0

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
                effective_regime=effective_regime_state.value,
                banned_strategies=banned_strategies
            )

            # --- V3 Strategy Design Agent Override ---
            design_agents = build_agent_pipeline(phase="scanner")
            if design_agents:
                try:
                    # Use AgentRunner for consistency
                    agent_context = {
                        "legacy_strategy": suggestion["strategy"],
                        "effective_regime": effective_regime_state.value,
                        "iv_rank": iv_rank,
                        "banned_strategies": banned_strategies
                    }

                    # Run via Runner
                    _, summary = AgentRunner.run_agents(agent_context, design_agents)

                    # Check for override in active constraints
                    active_constraints = summary.get("active_constraints", {})
                    if active_constraints.get("strategy.override_selector"):
                        rec = active_constraints.get("strategy.recommended")
                        if rec:
                            suggestion["strategy"] = rec
                            # Log override reason
                            top_reasons = summary.get("top_reasons", [])
                            if top_reasons:
                                print(f"[Scanner] Strategy Override for {symbol}: {top_reasons[0]}")
                except Exception as e:
                    print(f"[Scanner] StrategyDesignAgent error for {symbol}: {e}")
            # -----------------------------------------

            if suggestion["strategy"] == "HOLD" or suggestion["strategy"] == "CASH":
                rej_stats.record("strategy_hold")
                return None

            # Double check policy (redundant but safe)
            if not policy.is_allowed(suggestion["strategy"]):
                rej_stats.record("strategy_banned")
                return None

            # F. Construct Contract & Calculate EV
            # Prefer TruthLayer (cached)
            chain = []
            chain_objects = None

            try:
                # OPTIMIZATION: Use hoisted min/max expiry to reduce overhead inside loop
                chain_objects = truth_layer.option_chain(symbol, min_expiry=min_expiry, max_expiry=max_expiry)
            except Exception:
                chain_objects = None

            if chain_objects:
                # Bolt Optimization:
                # Pass chain_objects directly to selector. We defer flattening until we select the best expiry.
                # This reduces dictionary creation/copying from ~5000 (all contracts) to ~200 (one expiry).
                chain = chain_objects
                rej_stats.increment_chains_loaded()

            # Fallback if empty
            if not chain:
                chain = market_data.get_option_chain(symbol, min_dte=SCANNER_MIN_DTE, max_dte=SCANNER_MAX_DTE)
                if chain:
                    rej_stats.increment_chains_loaded()

            if not chain:
                rej_stats.increment_chains_empty()
                rej_stats.record("no_chain")
                return None

            # Enforce shared expiry
            # Optimization: Select bucket and return contracts directly to avoid re-filtering
            # Bolt Optimization: Pass today_date to avoid calling datetime.now().date() in loop
            expiry_selected, chain_subset = _select_best_expiry_chain(chain, target_dte=35, today_date=today_date)
            if not expiry_selected or not chain_subset:
                rej_stats.record("dte_out_of_range")
                return None

            # ========== SURFACE V4 HOOK (Optional) ==========
            # Compute arb-free surface when enabled for consistency contract
            surface_v4_summary = None
            surface_result = None
            if _is_surface_v4_enabled():
                # Use distinct name to avoid shadowing outer 'policy' variable
                surface_policy = _get_surface_v4_policy()
                try:
                    from packages.quantum.services.surface_geometry_v4 import (
                        build_arb_free_surface,
                        record_surface_to_context,
                    )

                    # Build surface on MULTI-EXPIRY chain (not chain_subset) so
                    # calendar arb is meaningful. Filter strikes to reduce noise.
                    sr = _get_surface_v4_strike_range()
                    strike_lo = current_price * (1 - sr)
                    strike_hi = current_price * (1 + sr)
                    surface_chain = [
                        c for c in chain
                        if strike_lo <= float(c.get("strike") or 0) <= strike_hi
                    ]

                    surface_result = build_arb_free_surface(
                        chain=surface_chain,
                        spot=current_price,
                        symbol=symbol,
                        as_of_ts=now_dt,
                    )

                    # Record to DecisionContext
                    record_surface_to_context(symbol, surface_result)

                    # Build compact summary using STRICT field names
                    surface = surface_result.surface
                    butterfly_any_post = (
                        any(sm.butterfly_arb_detected_post for sm in surface.smiles)
                        if surface else None
                    )
                    surface_v4_summary = {
                        "is_valid": surface_result.is_valid,
                        "content_hash": surface_result.content_hash,
                        "calendar_arb_pre": surface.calendar_arb_detected_pre if surface else None,
                        "calendar_arb_post": surface.calendar_arb_detected_post if surface else None,
                        "calendar_arb_count_post": surface.calendar_arb_count_post if surface else None,
                        "calendar_arb_expiries": surface.calendar_arb_expiries if surface else [],
                        "butterfly_any_post": butterfly_any_post,
                        "repair_iterations": surface.repair_iterations if surface else None,
                        "warnings": surface_result.warnings[:3],
                        "errors": surface_result.errors[:3],
                    }

                except Exception as e:
                    logger.warning(f"[Scanner] Surface V4 computation failed for {symbol}: {e}")
                    surface_v4_summary = {"error": str(e)}
                    # If surface_policy is skip, reject on build failure
                    if surface_policy == "skip":
                        rej_stats.record("surface_build_failed")
                        return None

                # Policy enforcement (outside try/except so it always runs)
                if surface_policy == "skip" and surface_result is not None:
                    # Reject if surface is invalid
                    if not surface_result.is_valid:
                        rej_stats.record("surface_invalid")
                        return None
                    # Reject if calendar arb detected post-repair
                    if surface_result.surface and surface_result.surface.calendar_arb_detected_post:
                        rej_stats.record("surface_calendar_arb")
                        return None
                    # Reject if any butterfly arb remains post-repair
                    if surface_result.surface and any(
                        sm.butterfly_arb_detected_post for sm in surface_result.surface.smiles
                    ):
                        rej_stats.record("surface_butterfly_arb")
                        return None
            # ================================================

            # Optimization: Sort and index chain ONCE per symbol
            # Single-pass split into calls and puts

            # Bolt Optimization: Removed flattening loop to avoid O(N) dict overhead.
            # Splitting logic now handles 'type' vs 'right' access natively.

            calls_list = []
            puts_list = []

            # Detect schema key from first element to optimize loop
            type_key = 'type'
            if chain_subset:
                # TruthLayer uses 'right', Polygon uses 'type'
                if 'right' in chain_subset[0]:
                    type_key = 'right'

            for c in chain_subset:
                # Native handling of 'type' (Polygon/Flat) or 'right' (TruthLayer/Nested)
                # Optimization: Use detected key
                ctype = c.get(type_key)
                if ctype == 'call':
                    calls_list.append(c)
                elif ctype == 'put':
                    puts_list.append(c)

            # Bolt Optimization: Use operator.itemgetter for faster sort key access
            calls_sorted = sorted(calls_list, key=operator.itemgetter('strike'))
            puts_sorted = sorted(puts_list, key=operator.itemgetter('strike'))

            # Normalize Strategy Key early
            raw_strategy = suggestion["strategy"]
            strategy_key = raw_strategy.lower().replace(" ", "_")

            # Initialize hydration_meta for both condor and non-condor paths
            hydration_meta = None

            if "iron_condor" in strategy_key or "condor" in strategy_key:
                # Specialized logic for Iron Condor
                legs, total_cost = _select_iron_condor_legs(calls_sorted, puts_sorted, current_price)
                if not legs:
                    # Sample even when legs not found for diagnostics
                    sample = _build_condor_rejection_sample(
                        symbol=symbol,
                        strategy_key=strategy_key,
                        expiry_selected=expiry_selected,
                        legs=[],
                        total_cost=None,
                        calls_count=len(calls_sorted),
                        puts_count=len(puts_sorted),
                    )
                    rej_stats.record_with_sample("condor_legs_not_found", sample)
                    return None

                # Invariant Validation
                if not _validate_iron_condor_invariants(legs):
                    rej_stats.record("condor_invariants_failed")
                    return None

                # Quote Hydration: Check for missing/invalid quotes and attempt to fill
                missing_quotes_before = [
                    leg.get("symbol") for leg in legs
                    if not _leg_has_valid_bidask(leg)
                ]

                if missing_quotes_before:
                    # Attempt targeted quote hydration for the 4 leg tickers
                    # Falls back to /v3/quotes if v4 snapshots don't provide valid quotes
                    hydration_meta = _hydrate_legs_quotes_v4(truth_layer, legs, market_data=market_data)

                    # Reprice total_cost from hydrated legs
                    new_total = _reprice_total_cost_from_legs(legs)
                    if new_total is None:
                        # Could not compute valid pricing even after hydration
                        sample = _build_condor_rejection_sample(
                            symbol=symbol,
                            strategy_key=strategy_key,
                            expiry_selected=expiry_selected,
                            legs=legs,
                            total_cost=None,
                            calls_count=len(calls_sorted),
                            puts_count=len(puts_sorted),
                        )
                        sample["hydration"] = hydration_meta
                        rej_stats.record_with_sample("condor_missing_quotes", sample)
                        return None
                    else:
                        total_cost = new_total

                # Re-check for missing quotes after hydration
                missing_quotes_after = [
                    leg.get("symbol") for leg in legs
                    if not _leg_has_valid_bidask(leg)
                ]

                if missing_quotes_after:
                    # Still have legs with unusable quotes
                    sample = _build_condor_rejection_sample(
                        symbol=symbol,
                        strategy_key=strategy_key,
                        expiry_selected=expiry_selected,
                        legs=legs,
                        total_cost=total_cost,
                        calls_count=len(calls_sorted),
                        puts_count=len(puts_sorted),
                    )
                    sample["missing_after"] = missing_quotes_after
                    if hydration_meta:
                        sample["hydration"] = hydration_meta
                    rej_stats.record_with_sample("condor_missing_quotes", sample)
                    return None

                # Credit Check: Only reached when quotes are usable
                credit_share = abs(total_cost) if total_cost < 0 else 0.0
                if credit_share <= 0:
                    # Sample with legs for debugging credit calculation
                    sample = _build_condor_rejection_sample(
                        symbol=symbol,
                        strategy_key=strategy_key,
                        expiry_selected=expiry_selected,
                        legs=legs,
                        total_cost=total_cost,
                        calls_count=len(calls_sorted),
                        puts_count=len(puts_sorted),
                    )
                    rej_stats.record_with_sample("condor_no_credit", sample)
                    return None

                # Width Check
                calls = sorted([l for l in legs if l["type"] == "call"], key=lambda x: x["strike"])
                puts = sorted([l for l in legs if l["type"] == "put"], key=lambda x: x["strike"])

                width_call = abs(calls[1]["strike"] - calls[0]["strike"])
                width_put = abs(puts[1]["strike"] - puts[0]["strike"])
                width_max = max(width_call, width_put)

                if credit_share >= width_max:
                    # Credit cannot exceed width (no risk? impossible/arb)
                    rej_stats.record("condor_credit_exceeds_width")
                    return None

                if width_call <= 0 or width_put <= 0:
                    rej_stats.record("condor_invalid_width")
                    return None
            else:
                legs, total_cost = _select_legs_from_chain(calls_sorted, puts_sorted, suggestion["legs"], current_price)

            if not legs:
                rej_stats.record("legs_not_found")
                return None

            # Determine data quality based on hydration source
            # If fallback was used and hydrated > 0, mark as degraded/approximate
            pricing_mode = "exact"
            data_quality = "realtime"
            if hydration_meta and hydration_meta.get("fallback"):
                fallback = hydration_meta["fallback"]
                if fallback.get("hydrated", 0) > 0:
                    pricing_mode = "approximate"
                    data_quality = "degraded"

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
                    rej_stats.record("single_leg_strategy_unmapped")
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
                 rej_stats.record("spread_too_wide")
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
                rej_stats.record("execution_cost_exceeds_ev")
                return None

            # Define Missing Greeks for Candidate Dict
            net_delta_contract = sum((l.get('delta') or 0.0) * (1 if l['side'] == 'buy' else -1) for l in legs)
            net_vega_contract = sum((l.get('vega') or 0.0) * (1 if l['side'] == 'buy' else -1) for l in legs)

            # --- Earnings Awareness Logic ---
            earnings_val = earnings_map.get(symbol)

            # Note: No fallback fetch here anymore to avoid N+1.
            # We rely on the batch fetch done at start.

            days_to_earnings = None
            earnings_risk = False
            earnings_penalty_val = 0.0

            if earnings_val:
                try:
                    # Support datetime object or YYYY-MM-DD string
                    earnings_dt = None
                    # Bolt Optimization: Reuse parse_expiry_date cache for earnings strings if compatible
                    if isinstance(earnings_val, str):
                        try:
                            earnings_dt = parse_expiry_date(earnings_val)
                            # Convert back to datetime if needed, or work with date.
                            # Scanner logic below uses .date() from datetime, but parse_expiry_date returns date.
                            # So we wrap in datetime if needed or adjust logic.
                            # Logic: (earnings_dt.date() - today_date).days
                            # If earnings_dt is date, we can use it directly.
                            # But code below expects earnings_dt to have .date() method if it was datetime.
                            # Let's adjust logic.
                        except ValueError:
                            # Fallback if cache fails (e.g. invalid format)
                             earnings_dt = datetime.fromisoformat(earnings_val).date()
                    elif isinstance(earnings_val, datetime):
                        earnings_dt = earnings_val.date()
                    elif isinstance(earnings_val, date):
                         earnings_dt = earnings_val

                    if earnings_dt:
                        # Use now_dt (hoisted) instead of calling datetime.now() again
                        # Ensure earnings_dt is a date object for subtraction
                        if isinstance(earnings_dt, datetime):
                             earnings_dt = earnings_dt.date()

                        days_to_earnings = (earnings_dt - today_date).days

                        # Normalize strategy key for safety checks (already lowercased above but ensuring consistency)
                        safe_strategy_key = strategy_key.lower()

                        # 1. Hard Reject: Short Premium within 2 days
                        if days_to_earnings <= 2:
                            is_short_premium = ("credit" in safe_strategy_key) or ("condor" in safe_strategy_key) or ("short" in safe_strategy_key)
                            if is_short_premium:
                                rej_stats.record("earnings_short_premium")
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
                "earnings_penalty": earnings_penalty_val,
                # Agent Data
                "option_spread_pct": option_spread_pct,
                # Surface V4 (optional, only populated when SURFACE_V4_ENABLE=1)
                "surface_v4": surface_v4_summary,
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

            # --- QUANT AGENTS V3 INTEGRATION ---
            scanner_agents = build_agent_pipeline(phase="scanner")
            if scanner_agents:
                try:
                    # Build Agent Context
                    agent_context = candidate_dict.copy()
                    agent_context.update({
                        "quote": quote,
                        "iv_rank": iv_rank,
                        "effective_regime": effective_regime_state.value,
                        "earnings_map": earnings_map,
                        "timestamp": now_dt.isoformat() # Use hoisted timestamp
                    })

                    # Run Canonical Agents
                    # Note: StrategyDesignAgent runs earlier to guide selection
                    agent_signals, agent_summary = AgentRunner.run_agents(agent_context, scanner_agents)

                    candidate_dict["agent_signals"] = agent_signals
                    candidate_dict["agent_summary"] = agent_summary

                    # Apply Constraints & Veto
                    candidate_dict = _apply_agent_constraints(candidate_dict, portfolio_cash=portfolio_cash)
                    if candidate_dict is None:
                        rej_stats.record("agent_veto")
                        return None

                except Exception as e:
                    print(f"[Scanner] Agent execution error for {symbol}: {e}")

            return candidate_dict

        except Exception as e:
            print(f"[Scanner] Error processing {symbol}: {e}")
            rej_stats.record("processing_error")
            return None

    # Corrected Indentation: ThreadPoolExecutor is now OUTSIDE process_symbol
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_to_symbol = {
            executor.submit(process_symbol, sym, drag_map, quotes_map, earnings_map, iv_context_map, rejection_stats): sym
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
    # Bolt Determinism: Add symbol as tie-breaker for stable ordering across concurrent runs
    candidates.sort(key=lambda x: (x['score'], x['symbol']), reverse=True)

    # Log rejection summary if no candidates
    if not candidates:
        top_reasons = rejection_stats.top_reasons(5)
        if top_reasons:
            logger.info(f"[Scanner] Top rejection reasons: {top_reasons}")

    return candidates, rejection_stats
