"""
Weekly Options Scout - Find high-probability credit spread opportunities
"""
import numpy as np
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, date
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.services.trade_builder import enrich_trade_suggestions
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.forward_atm import compute_forward_atm_from_parity
from supabase import Client

# Constants for Regime Classification
IV_RANK_SUPPRESSED_THRESHOLD = 20
IV_RANK_ELEVATED_THRESHOLD = 60

def classify_iv_regime(iv_rank: float | None) -> str | None:
    if iv_rank is None:
        return None
    if iv_rank < IV_RANK_SUPPRESSED_THRESHOLD: return "suppressed"
    if iv_rank < IV_RANK_ELEVATED_THRESHOLD: return "normal"
    return "elevated"

def scan_for_opportunities(
    symbols: List[str] = None,
    supabase_client: Optional[Client] = None
) -> List[Dict]:
    """
    Scan for weekly option opportunities.
    This function scans a predefined market-wide universe of tickers for opportunities.
    It does NOT use the user's holdings, which is the job of the Optimizer.
    """

    universe_service = None
    if supabase_client:
        try:
            universe_service = UniverseService(supabase_client)
        except Exception:
            pass

    opportunities = []

    # DEV LIMIT logic (Step 6)
    limit = 40
    if os.getenv("APP_ENV") == "development":
        # in development we typically set SCANNER_LIMIT_DEV=15 to speed up scans
        limit = int(os.getenv("SCANNER_LIMIT_DEV", 40))

    if not symbols:
        # Use Universe Funnel
        if universe_service:
            print(f"Scanning via Universe Funnel (Limit: {limit})...")
            candidates = universe_service.get_scan_candidates(limit=limit)
            for cand in candidates:
                opportunities.append({
                    'symbol': cand['symbol'],
                    'earnings_date': cand.get('earnings_date'),
                    'width': 5,
                    'credit_target': 1.0
                })
        else:
            # Fallback to static list
            market_scan_universe = [
                {'symbol': 'SPY', 'width': 5, 'credit_target': 1.25},
                {'symbol': 'QQQ', 'width': 5, 'credit_target': 1.50},
                {'symbol': 'IWM', 'width': 5, 'credit_target': 1.10},
                {'symbol': 'DIA', 'width': 5, 'credit_target': 1.00},
                {'symbol': 'TLT', 'width': 2, 'credit_target': 0.50},
                {'symbol': 'GLD', 'width': 2, 'credit_target': 0.40},
                {'symbol': 'XLF', 'width': 1, 'credit_target': 0.25},
                {'symbol': 'AAPL', 'width': 5, 'credit_target': 1.30},
                {'symbol': 'MSFT', 'width': 5, 'credit_target': 1.20},
                {'symbol': 'AMZN', 'width': 5, 'credit_target': 1.80},
                {'symbol': 'GOOGL', 'width': 5, 'credit_target': 1.70},
                {'symbol': 'NVDA', 'width': 10, 'credit_target': 3.00},
                {'symbol': 'TSLA', 'width': 10, 'credit_target': 2.50},
                {'symbol': 'META', 'width': 5, 'credit_target': 1.50},
            ]
            opportunities = market_scan_universe[:limit]
    else:
        limit_symbols = symbols[:limit]
        for sym in limit_symbols:
            opportunities.append({
                'symbol': sym,
                'width': 5,
                'credit_target': 1.00
            })

    # Prepare list for processing
    processed_opportunities = []

    # Initialize Truth Layer
    truth_layer = MarketDataTruthLayer()

    # Batch Fetch Price Data
    # Collect all unique symbols
    scan_symbols = list(set(opp['symbol'] for opp in opportunities))
    snapshots = truth_layer.snapshot_many(scan_symbols)

    for opp_config in opportunities:
        symbol = opp_config['symbol']

        # Use normalized lookup
        norm_sym = truth_layer.normalize_symbol(symbol)
        snapshot = snapshots.get(norm_sym) or {}
        quote = snapshot.get("quote", {})
        day = snapshot.get("day", {})

        # Determine price (prefer last trade, then day close)
        current_price = quote.get("last") or day.get("c") or 100.0
        current_price = 100.0
        cached = get_cached_market_data(symbol)
        hist_data = None

        if cached:
            current_price = cached.get("day", {}).get("c") or cached.get("lastTrade", {}).get("p") or 100.0
        elif service:
             try:
                 # ⚡ Bolt Optimization: Fetch max history (365d) once per symbol instead of 3 separate calls
                 # This reduces API requests by ~66% (3 -> 1) per symbol in the scanner loop.
                 hist_data = service.get_historical_prices(symbol, days=365)
                 if hist_data and hist_data.get('prices'):
                    current_price = hist_data['prices'][-1]
             except:
                 pass

        # Construct Opportunity Object
        opp = {
            'symbol': symbol,
            'type': 'Debit Call Spread',
            'short_strike': 105,
            'long_strike': 100,
            'expiry': (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
            'dte': 30,
            'credit': opp_config.get('credit_target', 1.0),
            'width': opp_config.get('width', 5),
            'iv_rank': None,
            'delta': 0.30,
            'underlying_price': current_price,
            'max_gain': (opp_config.get('width', 5) - 1.0) * 100,
            'max_loss': 1.0 * 100,
            'trend': 'UP',
            'reward_risk': 2.0,
            'suggested_entry': None, # Init None
            'last_price': None
        }

        try:
            # Use Truth Layer for Analytics
            # Note: get_trend and iv_context use caching internally, so sequential calls are okay
            # and won't spam the API if cache hits.
            # But initial run will be N sequential calls for historical data.
            # Truth Layer daily_bars uses cache.

            opp['trend'] = truth_layer.get_trend(symbol)

            iv_ctx = truth_layer.iv_context(symbol)
            opp['iv_rank'] = iv_ctx.get('iv_rank')
            opp['iv_regime'] = iv_ctx.get('iv_regime')

            # --- Forward ATM Logic ---
            anchor_price = current_price
            atm_method = "spot"
            atm_mode = os.getenv("ATM_MODE", "forward") # Default to forward

            if atm_mode == "forward":
                try:
                    expiry_date = opp['expiry']
                    calls_chain = truth_layer.option_chain(symbol, expiration_date=expiry_date, right="call")
                    puts_chain = truth_layer.option_chain(symbol, expiration_date=expiry_date, right="put")

                    fwd_res = compute_forward_atm_from_parity(calls_chain, puts_chain, current_price)
                    if fwd_res.forward_price:
                        anchor_price = fwd_res.forward_price
                        atm_method = fwd_res.method
                        opp['forward_price'] = fwd_res.forward_price
                        opp['atm_strike_forward'] = fwd_res.atm_strike
                        opp['atm_method'] = fwd_res.method
                    else:
                        opp['atm_method'] = "fallback_spot_computation_failed"
                except Exception as e:
                    print(f"[Scanner] Forward ATM failed for {symbol}: {e}")
                    opp['atm_method'] = "fallback_spot_exception"

            if opp['trend'] == "DOWN":
                opp['type'] = 'Debit Put Spread'
                target_long = anchor_price * 0.95
                target_short = anchor_price * 0.90
            else:
                opp['type'] = 'Debit Call Spread'
                target_long = anchor_price * 1.02
                target_short = anchor_price * 1.07

            step = 1 if current_price < 200 else 5
            long_strike = round(target_long / step) * step
            short_strike = round(target_short / step) * step
            if abs(short_strike - long_strike) < step:
                 short_strike = long_strike + (step if opp['trend']!="DOWN" else -step)

            opp['long_strike'] = long_strike
            opp['short_strike'] = short_strike
            opp['width'] = abs(short_strike - long_strike)

            estimated_price = opp['width'] * 0.35
            opp['suggested_entry'] = estimated_price
            opp['last_price'] = estimated_price

        except Exception as e:
            print(f"Error enriching opportunity {symbol}: {e}")
        if service and hist_data:
            try:
                # Use pre-fetched data for trend (needs ~100 days)
                # Ensure we pass the list, calculate_trend handles length checks
                prices = hist_data['prices']
                # Pass recent slice or full history (calculate_trend looks at last 50)
                opp['trend'] = calculate_trend(prices)

                # Use pre-fetched data for IV Rank (needs 365 days)
                opp['iv_rank'] = calculate_iv_rank(hist_data['returns'])

                opp['iv_regime'] = classify_iv_regime(opp['iv_rank'])

                if opp['trend'] == "DOWN":
                    opp['type'] = 'Debit Put Spread'
                    target_long = current_price * 0.95
                    target_short = current_price * 0.90
                else:
                    opp['type'] = 'Debit Call Spread'
                    target_long = current_price * 1.02
                    target_short = current_price * 1.07

                step = 1 if current_price < 200 else 5
                long_strike = round(target_long / step) * step
                short_strike = round(target_short / step) * step
                if abs(short_strike - long_strike) < step:
                     short_strike = long_strike + (step if opp['trend']!="DOWN" else -step)

                opp['long_strike'] = long_strike
                opp['short_strike'] = short_strike
                opp['width'] = abs(short_strike - long_strike)

                estimated_price = opp['width'] * 0.35
                opp['suggested_entry'] = estimated_price
                opp['last_price'] = estimated_price

            except:
                pass

        # Ensure fallback
        if opp.get('suggested_entry') is None:
             opp['suggested_entry'] = opp['width'] * 0.35
             opp['last_price'] = opp['width'] * 0.35

        processed_opportunities.append(opp)

    # --- Enrich & Filter ---
    market_data_enrich = {}

    # We already have snapshots from the batch call above
    for opp in processed_opportunities:
        symbol = opp['symbol']

        # Use existing snapshot data
        norm_sym = truth_layer.normalize_symbol(symbol)
        snapshot = snapshots.get(norm_sym) or {}
        quote = snapshot.get("quote", {})

        bid = quote.get("bid") or 0.0
        ask = quote.get("ask") or 0.0

        if bid > 0:
             spread_pct = (ask - bid) / bid
             if spread_pct > 0.10: continue

        market_data_enrich[symbol] = {
            "price": opp['underlying_price'],
            "iv_rank": opp.get("iv_rank"),
            "iv_regime": opp.get("iv_regime"),
            "trend": opp.get("trend"),
            "sector": "Unknown",
            "bid": bid,
            "ask": ask
        }

    filtered_opportunities = [
        opp for opp in processed_opportunities
        if opp['symbol'] in market_data_enrich
    ]

    enriched_opportunities = enrich_trade_suggestions(
        filtered_opportunities,
        100000,
        market_data_enrich,
        [],
        supabase_client=supabase_client
    )

    print(
        f"[Scanner] filtered_opportunities={len(filtered_opportunities)}, "
        f"enriched={len(enriched_opportunities)}, "
        f"market_data={len(market_data_enrich)}"
    )

    # Final Scoring
    final_candidates = []
    for cand in enriched_opportunities:
        # V3 Scoring is already applied in enrich_trade_suggestions via OpportunityScorer
        # We trust the score and metrics populated there.

        symbol = cand.get("symbol") or cand.get("ticker")
        metrics_debug = cand.get('metrics') or {}

        # Ensure suggested_entry is present
        current_entry = cand.get("suggested_entry")
        if current_entry is None or (isinstance(current_entry, (int, float)) and current_entry <= 0):
             cand["suggested_entry"] = cand.get("last_price", 0.0)
             if cand["suggested_entry"] <= 0:
                 width = cand.get("width", 5)
                 cand["suggested_entry"] = width * 0.35

        print(f"{symbol} score={cand.get('score')} ev={metrics_debug.get('ev_amount')}")

        final_candidates.append(cand)

    # Sort with None safety: treat None as -1
    def get_sort_key(x):
        s = x.get('score')
        try:
            return float(s) if s is not None else -1.0
        except (ValueError, TypeError):
            return -1.0

    final_candidates.sort(key=get_sort_key, reverse=True)

    return final_candidates

if __name__ == '__main__':
    pass
