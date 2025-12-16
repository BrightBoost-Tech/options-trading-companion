import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
import logging
import concurrent.futures

from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.ev_calculator import calculate_ev
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.regime_integration import map_market_regime
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, GlobalRegimeSnapshot, RegimeState
from packages.quantum.analytics.scoring import calculate_unified_score
from packages.quantum.services.execution_service import ExecutionService

# Configuration
SCANNER_LIMIT_DEV = int(os.getenv("SCANNER_LIMIT_DEV", "40")) # Limit universe in dev

logger = logging.getLogger(__name__)

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
    user_id: str = None
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

    # 1. Determine Universe
    if not symbols:
        if universe_service:
            try:
                universe = universe_service.get_universe()
                symbols = [u['symbol'] for u in universe]
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
    try:
        global_snapshot = regime_engine.compute_global_snapshot(datetime.now())
        print(f"[Scanner] Global Regime: {global_snapshot.state}")
    except Exception as e:
        print(f"[Scanner] Regime computation failed: {e}. Using default.")
        global_snapshot = regime_engine._default_global_snapshot(datetime.now())

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
    batch_size = 5 # Used for thread pool size

    # 3a. Batch Fetch Quotes (Optimization)
    # Fetch all quotes in one go to avoid N requests inside the loop
    # truth_layer.snapshot_many handles batching automatically
    logger.info(f"[Scanner] Batch fetching quotes for {len(symbols)} symbols...")
    quotes_map = truth_layer.snapshot_many(symbols)

    def process_symbol(symbol: str, drag_map: Dict[str, Any], quotes_map: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
                chain_objects = truth_layer.option_chain(symbol)
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

                        if not (25 <= days_to_expiry <= 45):
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
                chain = market_data.get_option_chain(symbol, min_dte=25, max_dte=45)

            if not chain: return None

            legs = []
            total_cost = 0.0
            total_ev = 0.0

            # ... (Leg selection logic)
            for leg_def in suggestion["legs"]:
                    target_delta = leg_def["delta_target"]
                    side = leg_def["side"]
                    op_type = leg_def["type"]

                    if op_type == "call":
                        filtered = [c for c in chain if c['type'] == 'call']
                    else:
                        filtered = [c for c in chain if c['type'] == 'put']

                    if not filtered: continue

                    # Find closest delta
                    has_delta = any('delta' in c and c['delta'] is not None for c in filtered)

                    if has_delta:
                        target_d = abs(target_delta)
                        best_contract = min(filtered, key=lambda x: abs(abs(x.get('delta',0) or 0) - target_d))
                    else:
                        moneyness = 1.0
                        if op_type == 'call':
                            if target_delta > 0.5: moneyness = 0.95
                            elif target_delta < 0.5: moneyness = 1.05
                        else:
                            if target_delta > 0.5: moneyness = 1.05
                            elif target_delta < 0.5: moneyness = 0.95

                        target_k = current_price * moneyness
                        best_contract = min(filtered, key=lambda x: abs(x['strike'] - target_k))

                    premium = best_contract.get('price') or best_contract.get('close') or 0.0

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
                        "theta": best_contract.get('theta') or 0.0
                    })

                    if side == "buy":
                        total_cost += premium
                    else:
                        total_cost -= premium

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

            # Normalize Strategy Key
            raw_strategy = suggestion["strategy"]
            strategy_key = raw_strategy.lower().replace(" ", "_")
            pricing_mode = "exact"
            data_quality = "realtime"

            # Check for degraded data (missing premiums)
            if any((l.get('premium') or 0) <= 0 for l in legs):
                 data_quality = "degraded"
                 pricing_mode = "approximate"

            # EV Calculation
            if len(legs) == 2:
                long_leg = next((l for l in legs if l['side'] == 'buy'), None)
                short_leg = next((l for l in legs if l['side'] == 'sell'), None)
                if long_leg and short_leg:
                    width = abs(long_leg['strike'] - short_leg['strike'])
                    st_type = "debit_spread" if total_cost > 0 else "credit_spread"

                    ev_obj = calculate_ev(
                        premium=abs(total_cost),
                        strike=long_leg['strike'],
                        current_price=current_price,
                        delta=long_leg['delta'],
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

            candidate_dict = {
                "symbol": symbol,
                "ticker": symbol,
                "type": suggestion["strategy"],
                "strategy": suggestion["strategy"],
                "strategy_key": strategy_key,
                "suggested_entry": abs(total_cost),
                "ev": total_ev,
                "score": round(unified_score.score, 1),
                "unified_score_details": unified_score.components.dict(),
                "iv_rank": iv_rank,
                "trend": trend,
                "legs": legs,
                "badges": unified_score.badges,
                "execution_drag_estimate": expected_execution_cost,
                "execution_drag_samples": cost_details["execution_cost_samples_used"],
                "execution_drag_source": cost_details["execution_drag_source"],
                "execution_cost_source_used": cost_details["execution_cost_source_used"],
                "execution_cost_samples_used": cost_details["execution_cost_samples_used"],
                # Risk Primitives
                "max_loss_per_contract": max_loss_contract,
                "max_profit_per_contract": max_profit_contract,
                "collateral_required_per_contract": collateral_contract,
                "collateral_per_contract": collateral_contract,
                "net_delta_per_contract": net_delta_contract,
                "net_vega_per_contract": net_vega_contract,
                "data_quality": data_quality,
                "pricing_mode": pricing_mode
            }

            # Calculate Probability of Profit
            # Pass dictionary representation of global snapshot for compatibility
            gs_dict = global_snapshot.to_dict() if global_snapshot else None
            candidate_dict["probability_of_profit"] = _estimate_probability_of_profit(candidate_dict, gs_dict)

            return candidate_dict

        except Exception as e:
            print(f"[Scanner] Error processing {symbol}: {e}")
            return None

    # Corrected Indentation: ThreadPoolExecutor is now OUTSIDE process_symbol
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_to_symbol = {
            executor.submit(process_symbol, sym, drag_map, quotes_map): sym
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
