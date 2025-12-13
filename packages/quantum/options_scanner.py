import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
import logging

from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.ev_calculator import calculate_ev
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.regime_integration import map_market_regime
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, GlobalRegimeSnapshot, RegimeState
from packages.quantum.analytics.scoring import calculate_unified_score
from packages.quantum.services.execution_service import ExecutionService

# Configuration
SCANNER_LIMIT_DEV = int(os.getenv("SCANNER_LIMIT_DEV", "40")) # Limit universe in dev

logger = logging.getLogger(__name__)

def scan_for_opportunities(
    symbols: List[str] = None,
    supabase_client: Client = None,
    user_id: str = None
) -> List[Dict[str, Any]]:
    """
    Scans the provided symbols (or universe) for option trade opportunities.
    Returns a list of trade candidates (dictionaries).
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
        market_data=market_data,
        iv_repository=IVRepository(supabase_client) if supabase_client else None,
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


    # 3. Sequential Processing
    # No longer batching for Execution Drag here, as it's done above.
    batch_size = 5

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]

        for symbol in batch:
            try:
                # A. Enrich Data
                quote = market_data.get_recent_quote(symbol)
                if not quote: continue

                current_price = quote.get("price")
                if not current_price: continue

                # B. Check Liquidity (Hard Rejection)
                bid = quote.get("bid_price", 0)
                ask = quote.get("ask_price", 0)
                spread_pct = 0.0

                if bid > 0 and ask > 0:
                    spread_pct = (ask - bid) / current_price
                    # Dynamic Liquidity Threshold based on Regime
                    threshold = 0.10 # Default
                    if global_snapshot.state == RegimeState.SUPPRESSED:
                         threshold = 0.20
                    elif global_snapshot.state == RegimeState.SHOCK:
                         threshold = 0.15

                    if spread_pct > threshold:
                        # REJECT: Liquidity
                        continue
                else:
                    # REJECT: No Quote
                    continue

                # C. Compute Symbol Regime (Authoritative)
                symbol_snapshot = regime_engine.compute_symbol_snapshot(symbol, global_snapshot)
                effective_regime_state = regime_engine.get_effective_regime(symbol_snapshot, global_snapshot)

                iv_rank = symbol_snapshot.iv_rank or 50.0

                # Check for Regime Suppression (Hard Rejection)
                # If regime explicitly bans structures or symbols, we skip here.
                # E.g., if Symbol is in 'Crisis' state (IV Rank > 95) but market is Normal?
                # The strategy selector should handle this, or we do it here.
                # For now, relying on Strategy Selector returning HOLD/NONE.

                # D. Technical Analysis (Trend)
                bars = market_data.get_historical_prices(symbol, days=60)
                if not bars or len(bars) < 50:
                    continue

                closes = [b['close'] for b in bars]
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
                    continue

                # F. Construct Contract & Calculate EV
                chain = market_data.get_option_chain(symbol, min_dte=25, max_dte=45)
                if not chain: continue

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

                # G. Compute Net EV
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

                # H. Unified Scoring
                trade_dict = {
                    "ev": total_ev,
                    "suggested_entry": abs(total_cost),
                    "bid_ask_spread": abs(total_cost) * spread_pct,
                    "strategy": suggestion["strategy"],
                    "legs": legs,
                    "vega": sum(l['vega'] if l['side']=='buy' else -l['vega'] for l in legs),
                    "gamma": sum(l['gamma'] if l['side']=='buy' else -l['gamma'] for l in legs),
                    "iv_rank": iv_rank,
                    "type": "debit" if total_cost > 0 else "credit"
                }

                # Step B3: Inject expected execution cost
                stats = drag_map.get(symbol)

                # Default proxy
                expected_execution_cost = None
                drag_source = "proxy"
                drag_samples = 0

                if stats:
                    expected_execution_cost = stats["avg_drag"]
                    drag_source = "history"
                    drag_samples = stats["n"]
                else:
                    # Use existing proxy mechanism if stats not available
                    # We pass None and let unified_score handle it, OR we compute proxy here.
                    # The prompt says: "if stats: expected = stats... else expected = proxy"
                    # And then pass it to calculate_unified_score.
                    if execution_service:
                        expected_execution_cost = execution_service.estimate_execution_cost(symbol, spread_pct=spread_pct, user_id=None)
                    else:
                        expected_execution_cost = 0.05 # safe fallback

                unified_score = calculate_unified_score(
                    trade=trade_dict,
                    regime_snapshot=global_snapshot.to_dict(),
                    market_data={"bid_ask_spread_pct": spread_pct},
                    execution_drag_estimate=expected_execution_cost
                )

                # Step B4: Hard rejection: execution drag > EV
                if expected_execution_cost >= total_ev:
                    # REJECT: Execution drag exceeds EV
                    # store reject reason e.g. "execution_drag_exceeds_ev"
                    # We continue loop, effectively skipping this candidate
                    continue

                # Step B5: Persist in candidate details
                candidates.append({
                    "symbol": symbol,
                    "ticker": symbol,
                    "type": suggestion["strategy"],
                    "strategy": suggestion["strategy"],
                    "suggested_entry": abs(total_cost),
                    "ev": total_ev,
                    "score": round(unified_score.score, 1),
                    "unified_score_details": unified_score.components.dict(),
                    "iv_rank": iv_rank,
                    "trend": trend,
                    "legs": legs,
                    "badges": unified_score.badges,
                    "execution_drag_estimate": expected_execution_cost,
                    "execution_drag_samples": drag_samples,
                    "execution_drag_source": drag_source
                })

            except Exception as e:
                print(f"[Scanner] Error processing {symbol}: {e}")
                continue

    # Sort by Unified Score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    return candidates
