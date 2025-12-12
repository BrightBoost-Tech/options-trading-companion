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
                # Use UniverseService to fetch cached candidates
                # This should handle syncing if stale
                # For now, just getting the list.
                universe = universe_service.get_universe() # returns list of dicts
                symbols = [u['symbol'] for u in universe]
            except Exception as e:
                print(f"[Scanner] UniverseService failed: {e}. Using fallback.")
                symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
        else:
             symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMD"]

    # Filter symbols: Skip ETFs if we want stock only? Or include?
    # Spec implies stocks mainly, but ETFs okay.

    # Dev mode limit
    if os.getenv("APP_ENV") != "production":
        symbols = symbols[:SCANNER_LIMIT_DEV]

    print(f"[Scanner] Processing {len(symbols)} symbols...")

    # 2. Sequential Processing (Synchronous to avoid event loop issues)
    # We moved away from asyncio.gather to avoid "Event loop is closed" errors in non-async contexts.

    batch_size = 5 # Small batching for Polygon rate limits if needed internally

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]

        for symbol in batch:
            try:
                # A. Enrich Data (Price, IV, Earnings, etc.)
                # We can use market_data.get_recent_quote or similar.
                # Need IV Rank.
                # If we don't have IV repository handy, we fetch from Polygon snapshot
                # OR use a helper.
                # Let's use UniverseService data if available, else fetch.

                # Fetch recent quote (Trade/Quote)
                quote = market_data.get_recent_quote(symbol)
                if not quote: continue

                current_price = quote.get("price")
                if not current_price: continue

                # Check Liquidity (Bid/Ask spread)
                # Guardrail: If spread > 10% of price, skip.
                bid = quote.get("bid_price", 0)
                ask = quote.get("ask_price", 0)
                if bid > 0 and ask > 0:
                    spread_pct = (ask - bid) / current_price
                    if spread_pct > 0.10:
                        # print(f"Skipping {symbol}: Wide spread {spread_pct:.1%}")
                        continue

                # Check Earnings Guardrail
                # Using Polygon reference data if available, or UniverseService cache
                # Assume UniverseService populates 'earnings_date'
                # If not, skipping for MVP.

                # B. Get IV Data
                # IV Rank is critical.
                iv_rank = 50.0 # Default
                effective_regime = None

                if supabase_client:
                    # Try fetch from DB via IVRepository or UniverseService
                    # This is slow per symbol.
                    try:
                        repo = IVRepository(supabase_client)
                        iv_ctx = repo.get_iv_context(symbol)
                        iv_rank = iv_ctx.get("iv_rank", 50.0)
                        # Normalize None
                        if iv_rank is None: iv_rank = 50.0

                        # V3 Integration: Map IV Rank to Regime State roughly if engine not fully integrated here
                        # Ideally pass effective_regime from upstream if batch processed,
                        # but here we are scanning individual symbols.
                        # Simple mapping for now until we inject RegimeEngineV3 here

                        # Just use helper logic or check IV Context 'regime' if updated
                        # V3 Engine computes Symbol Snapshot. We don't have engine here easily unless we instantiate it.
                        # For now, approximate mapping for Strategy Routing
                        if iv_rank < 20: effective_regime = RegimeState.SUPPRESSED
                        elif iv_rank > 80: effective_regime = RegimeState.ELEVATED
                        elif iv_rank > 95: effective_regime = RegimeState.SHOCK
                        else: effective_regime = RegimeState.NORMAL

                    except Exception:
                        pass

                # C. Technical Analysis (Trend)
                # Need historical data
                # Fetch last 50 days
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
                # Use StrategySelector with V3 Regime
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
                # This requires finding a specific contract.
                # StrategySelector returns generic instructions ("LONG_CALL", "delta_target": 0.60)
                # We need to find the real contract.

                # 1. Fetch Option Chain
                # Ideally expiration ~30-45 days out.
                chain = market_data.get_option_chain(symbol, min_dte=25, max_dte=45)
                if not chain: continue

                legs = []
                total_cost = 0.0
                total_ev = 0.0

                for leg_def in suggestion["legs"]:
                     # Find matching contract
                     target_delta = leg_def["delta_target"]
                     side = leg_def["side"] # buy/sell
                     op_type = leg_def["type"] # call/put

                     # Filter chain
                     # Need Greeks. Polygon chain endpoint might not include greeks?
                     # PolygonService.get_option_chain usually fetches basic info.
                     # We might need snapshot to get Greeks.
                     # For V2, we might filter by strike vs price as proxy if greeks missing.
                     # But assume we have greeks (or approximate).

                     # Approximation for MVP:
                     # Delta ~ Moneyness.
                     # Call 0.50 delta ~ ATM. 0.60 delta ~ ITM.
                     # Put 0.50 delta ~ ATM. 0.30 delta ~ OTM.

                     # Sort by strike
                     if op_type == "call":
                         # Lower strike = Higher Delta
                         # ITM Call (High Delta) < Price
                         filtered = [c for c in chain if c['type'] == 'call']
                     else:
                         filtered = [c for c in chain if c['type'] == 'put']

                     if not filtered: continue

                     # Find contract closest to target delta
                     # If we don't have delta, we estimate strike.
                     # Estimate: Delta 0.5 is ATM.
                     # Delta 0.25 is ~ 1 std dev OTM?
                     # Rough heuristic:
                     # 0.50 delta -> Strike = Price
                     # 0.30 delta -> Strike = Price * (1 + 0.05 * (1 if call else -1))?? Very rough.
                     # Let's rely on 'delta' field if available.

                     has_delta = any('delta' in c and c['delta'] is not None for c in filtered)

                     if has_delta:
                         # Find closest delta (abs diff)
                         # Note: Put deltas are negative. Target is usually passed as positive magnitude.
                         target_d = abs(target_delta)
                         best_contract = min(filtered, key=lambda x: abs(abs(x.get('delta',0) or 0) - target_d))
                     else:
                         # Fallback: Moneyness
                         # 0.50 -> ATM
                         # 0.25 -> 5% OTM?
                         # 0.75 -> 5% ITM?
                         # Very crude.
                         moneyness = 1.0
                         if op_type == 'call':
                             if target_delta > 0.5: moneyness = 0.95 # ITM
                             elif target_delta < 0.5: moneyness = 1.05 # OTM
                         else: # put
                             if target_delta > 0.5: moneyness = 1.05 # ITM (Strike > Price)
                             elif target_delta < 0.5: moneyness = 0.95 # OTM (Strike < Price)

                         target_k = current_price * moneyness
                         best_contract = min(filtered, key=lambda x: abs(x['strike'] - target_k))

                     # Get Price (Mark or Mid)
                     # Option chain usually has price/premium
                     premium = best_contract.get('price') or best_contract.get('close') or 0.0

                     # EV Calculation per leg
                     # Using simple EV calculator
                     leg_ev_res = calculate_ev(
                         premium=premium,
                         strike=best_contract['strike'],
                         current_price=current_price,
                         delta=best_contract.get('delta') or target_delta, # use assumed if missing
                         strategy=f"{side}_{op_type}", # "buy_call"
                         contracts=1
                     )

                     # Combine
                     # If buy, cost is premium. If sell, credit.
                     # EV is usually computed for net strategy.
                     # For spreads, we sum EV of legs? No, simpler to compute spread EV.
                     # But calculate_ev supports complex strategies if passed params.
                     # Here we do leg-sum approximation or just single leg EV for "single".

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
                # Simplified Score: Trend Strength + IV Alignment + Liquidity
                # Trend score (sma20/sma50 dist)
                trend_score = (sma20 / sma50 - 1.0) * 100 # % diff

                # EV (very rough sum of legs? No, calculate_ev handles simple spreads if passed)
                # Let's calculate EV of the *trade* structure.
                # Assuming first leg is primary.
                # If vertical spread:
                if len(legs) == 2:
                    # Vertical
                    # Long leg, Short leg
                    long_leg = next((l for l in legs if l['side'] == 'buy'), None)
                    short_leg = next((l for l in legs if l['side'] == 'sell'), None)
                    if long_leg and short_leg:
                        width = abs(long_leg['strike'] - short_leg['strike'])
                        net_debit = total_cost
                        # If net_debit < 0 (credit), max profit is credit.

                        # Use calculate_ev for spread?
                        # It supports 'credit_spread' or 'debit_spread'
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
                        total_ev = 0 # Complex/broken
                elif len(legs) == 1:
                    # Single
                    leg = legs[0]
                    st_type = f"{leg['side']}_{leg['type']}" # long_call
                    ev_obj = calculate_ev(
                        premium=leg['premium'],
                        strike=leg['strike'],
                        current_price=current_price,
                        delta=leg['delta'],
                        strategy=st_type
                    )
                    total_ev = ev_obj.expected_value

                # Score Formula
                # Base 50
                # + Trend Score * 5
                # + EV/Cost * 10?
                score = 50.0 + (trend_score * 5.0)
                if total_cost > 0:
                    roi_ev = total_ev / total_cost
                    score += roi_ev * 20.0

                # IV Rank bonus
                # If buying (Debit) and IV Low (<30) -> Good (+10)
                # If selling (Credit) and IV High (>50) -> Good (+10)
                is_debit = total_cost > 0
                if is_debit and iv_rank < 30: score += 10
                if not is_debit and iv_rank > 50: score += 10

                candidates.append({
                    "symbol": symbol,
                    "ticker": symbol,
                    "type": suggestion["strategy"],
                    "strategy": suggestion["strategy"],
                    "suggested_entry": abs(total_cost), # Net price
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
