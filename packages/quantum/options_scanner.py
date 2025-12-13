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
from packages.quantum.analytics.regime_engine_v3 import RegimeState

# Configuration
SCANNER_LIMIT_DEV = int(os.getenv("SCANNER_LIMIT_DEV", "40")) # Limit universe in dev

logger = logging.getLogger(__name__)

def classify_iv_regime(iv_rank: float) -> str:
    """Classifies IV Rank into Low/Normal/High/Extreme."""
    if iv_rank < 20:
        return "suppressed"
    elif iv_rank < 50:
        return "normal"
    elif iv_rank < 80:
        return "elevated"
    else:
        return "high"

def scan_for_opportunities(
    symbols: List[str] = None,
    supabase_client: Client = None
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

    # 1. Determine Universe
    if not symbols:
        if universe_service:
            try:
                universe = universe_service.get_universe() # returns list of dicts
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

    # 2. Sequential Processing
    batch_size = 5

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]

        for symbol in batch:
            try:
                # A. Enrich Data (Price, IV, Earnings, etc.)
                quote = market_data.get_recent_quote(symbol)
                if not quote: continue

                current_price = quote.get("price")
                if not current_price: continue

                # Check Liquidity (Bid/Ask spread)
                bid = quote.get("bid_price", 0)
                ask = quote.get("ask_price", 0)
                if bid > 0 and ask > 0:
                    spread_pct = (ask - bid) / current_price
                    if spread_pct > 0.10:
                        continue

                # B. Get IV Data
                iv_rank = 50.0 # Default
                effective_regime = None

                if supabase_client:
                    try:
                        repo = IVRepository(supabase_client)
                        iv_ctx = repo.get_iv_context(symbol)
                        iv_rank = iv_ctx.get("iv_rank", 50.0)
                        if iv_rank is None: iv_rank = 50.0

                        if iv_rank < 20: effective_regime = RegimeState.SUPPRESSED.value
                        elif iv_rank > 80: effective_regime = RegimeState.ELEVATED.value
                        elif iv_rank > 95: effective_regime = RegimeState.SHOCK.value
                        else: effective_regime = RegimeState.NORMAL.value

                    except Exception:
                        pass

                # C. Technical Analysis (Trend)
                bars = market_data.get_historical_prices(symbol, days=60)
                if not bars or len(bars) < 50:
                    continue

                closes = [b['close'] for b in bars]
                sma20 = np.mean(closes[-20:])
                sma50 = np.mean(closes[-50:])

                # Simple Trend Logic
                trend = "NEUTRAL"
                if closes[-1] > sma20 > sma50:
                    trend = "BULLISH"
                elif closes[-1] < sma20 < sma50:
                    trend = "BEARISH"

                # D. Strategy Selection
                suggestion = strategy_selector.determine_strategy(
                    ticker=symbol,
                    sentiment=trend,
                    current_price=current_price,
                    iv_rank=iv_rank,
                    effective_regime=effective_regime
                )

                if suggestion["strategy"] == "HOLD":
                    continue

                # E. Construct Contract & Calculate EV
                chain = market_data.get_option_chain(symbol, min_dte=25, max_dte=45)
                if not chain: continue

                legs = []
                total_cost = 0.0
                total_ev = 0.0

                for leg_def in suggestion["legs"]:
                     target_delta = leg_def["delta_target"]
                     side = leg_def["side"] # buy/sell
                     op_type = leg_def["type"] # call/put

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
                         # Fallback: Moneyness
                         moneyness = 1.0
                         if op_type == 'call':
                             if target_delta > 0.5: moneyness = 0.95 # ITM
                             elif target_delta < 0.5: moneyness = 1.05 # OTM
                         else: # put
                             if target_delta > 0.5: moneyness = 1.05 # ITM
                             elif target_delta < 0.5: moneyness = 0.95 # OTM

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
                         "delta": best_contract.get('delta') or target_delta
                     })

                     if side == "buy":
                         total_cost += premium
                     else:
                         total_cost -= premium # Credit

                # Compute Net EV and Score
                trend_score = (sma20 / sma50 - 1.0) * 100 # % diff

                if len(legs) == 2:
                    long_leg = next((l for l in legs if l['side'] == 'buy'), None)
                    short_leg = next((l for l in legs if l['side'] == 'sell'), None)
                    if long_leg and short_leg:
                        width = abs(long_leg['strike'] - short_leg['strike'])
                        st_type = "debit_spread" if total_cost > 0 else "credit_spread"

                        ev_obj = calculate_ev(
                            premium=abs(total_cost),
                            strike=long_leg['strike'], # Anchor
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

                score = 50.0 + (trend_score * 5.0)
                if total_cost > 0:
                    roi_ev = total_ev / total_cost if total_cost > 0 else 0
                    score += roi_ev * 20.0

                is_debit = total_cost > 0
                if is_debit and iv_rank < 30: score += 10
                if not is_debit and iv_rank > 50: score += 10

                candidates.append({
                    "symbol": symbol,
                    "ticker": symbol,
                    "type": suggestion["strategy"],
                    "strategy": suggestion["strategy"],
                    "suggested_entry": abs(total_cost),
                    "ev": total_ev,
                    "score": round(score, 1),
                    "iv_rank": iv_rank,
                    "trend": trend,
                    "legs": legs
                })

            except Exception as e:
                print(f"[Scanner] Error processing {symbol}: {e}")
                continue

    return candidates
