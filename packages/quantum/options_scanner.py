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
    regime_engine = RegimeEngineV3(
        supabase_client=supabase_client,
        market_data=MarketDataTruthLayer(),
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

    def process_symbol(symbol: str, drag_map: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single symbol and return a candidate dict or None."""
        try:
            # A. Enrich Data
            quote = market_data.get_recent_quote(symbol)
            if not quote: return None

            # Quote handling: tolerate both real Polygon (bid/ask) and mock (bid_price/ask_price)
            bid = quote.get("bid_price") if "bid_price" in quote else quote.get("bid")
            ask = quote.get("ask_price") if "ask_price" in quote else quote.get("ask")
            current_price = quote.get("price")

            # Fallback for current_price
            if current_price is None and bid is not None and ask is not None and bid > 0 and ask > 0:
                current_price = (bid + ask) / 2.0

            if not current_price: return None

            # B. Check Liquidity (Hard Rejection)
            spread_pct = 0.0

            if bid is not None and ask is not None and bid > 0 and ask > 0:
                spread_pct = (ask - bid) / current_price
                # Dynamic Liquidity Threshold based on Regime
                threshold = 0.10 # Default
                if global_snapshot.state == RegimeState.SUPPRESSED:
                        threshold = 0.20
                elif global_snapshot.state == RegimeState.SHOCK:
                        threshold = 0.15

                if spread_pct > threshold:
                    # REJECT: Liquidity
                    return None
            else:
                # REJECT: No Quote
                return None

            # C. Compute Symbol Regime (Authoritative)
            symbol_snapshot = regime_engine.compute_symbol_snapshot(symbol, global_snapshot)
            effective_regime_state = regime_engine.get_effective_regime(symbol_snapshot, global_snapshot)

            iv_rank = symbol_snapshot.iv_rank or 50.0

            # D. Technical Analysis (Trend)
            bars = market_data.get_historical_prices(symbol, days=60)

            # History handling: tolerate list of objects or dict with 'prices'
            closes = []
            if isinstance(bars, dict):
                closes = bars.get("prices") or []
            elif isinstance(bars, list):
                closes = [b.get("close") for b in bars if b.get("close") is not None]

            if not closes or len(closes) < 50:
                return None

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
                st_type = f"{leg['side']}_{leg['type']}"
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

            # H. Unified Scoring
            trade_dict = {
                "ev": total_ev,
                "suggested_entry": abs(total_cost),
                "bid_ask_spread": abs(total_cost) * spread_pct,
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

            # Fetch Execution Drag History
            stats = drag_map.get(symbol)
            # Default proxy values
            expected_execution_cost = None
            drag_source = "proxy"
            drag_samples = 0

            if stats and isinstance(stats, dict):
                expected_execution_cost = float(stats.get("avg_drag", 0.0))
                drag_source = "history"
                drag_samples = int(stats.get("n", stats.get("N", 0)) or 0)
            elif execution_service:
                expected_execution_cost = execution_service.estimate_execution_cost(
                  symbol,
                  spread_pct=spread_pct,
                  user_id=None,                 # Force proxy (do not re-query history per symbol)
                  entry_cost=abs(total_cost),
                  num_legs=len(legs),
                )
            else:
                  # This fallback is only used if no execution service and no history map.
                  # It is passed to calculate_unified_score, which handles null/0 better.
                  expected_execution_cost = 0.0

            unified_score = calculate_unified_score(
                trade=trade_dict,
                regime_snapshot=global_snapshot.to_dict(),
                market_data={"bid_ask_spread_pct": spread_pct},
                execution_drag_estimate=expected_execution_cost,
                num_legs=len(legs),
                entry_cost=abs(total_cost)
            )

            # Retrieve final execution cost (contract dollars) from UnifiedScore
            final_execution_cost = unified_score.execution_cost_dollars

            # Requirement: Hard-reject if execution cost > EV
            if final_execution_cost >= total_ev:
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
                "execution_drag_estimate": final_execution_cost,
                "execution_drag_samples": drag_samples,
                "execution_drag_source": drag_source,
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
            executor.submit(process_symbol, sym, drag_map): sym
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
