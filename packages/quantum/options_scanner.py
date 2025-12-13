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


    # 3. Parallel Processing
    batch_size = 5 # Used for thread pool size, though we'll submit all batches or iterate

    def process_symbol(symbol: str, batch_drag_stats: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Process a single symbol and return a candidate dict or None."""
        try:
            # A. Enrich Data
            quote = market_data.get_recent_quote(symbol)
            if not quote: return None

            current_price = quote.get("price")
            if not current_price: return None

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
            if not bars or len(bars) < 50:
                return None

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

            # Fetch Execution Drag History
            historical_drag = batch_drag_stats.get(symbol, 0.0)

            unified_score = calculate_unified_score(
                trade=trade_dict,
                regime_snapshot=global_snapshot.to_dict(),
                market_data={"bid_ask_spread_pct": spread_pct},
                execution_drag_estimate=historical_drag
            )

            # Requirement: Hard-reject if execution cost > EV
            estimated_cost_raw = (trade_dict['bid_ask_spread'] * 0.5) + (len(legs)*0.0065)
            # Use max of historical too
            estimated_cost_raw = max(estimated_cost_raw, historical_drag)

            if estimated_cost_raw > total_ev:
                # REJECT: Negative Expectancy after Cost
                return None

            return {
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
                "badges": unified_score.badges
            }

        except Exception as e:
            print(f"[Scanner] Error processing {symbol}: {e}")
            return None


    # Process in batches to balance parallelism with resource usage
    # We still use batches to fetch drag stats efficiently if needed
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]

        # Batch fetch execution drag for efficiency
        batch_drag_stats = {}
        if execution_service:
            try:
                batch_drag_stats = execution_service.get_batch_execution_drag_stats(batch, user_id=user_id)
            except Exception:
                pass

        # Parallelize the batch
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            future_to_symbol = {
                executor.submit(process_symbol, sym, batch_drag_stats): sym
                for sym in batch
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
