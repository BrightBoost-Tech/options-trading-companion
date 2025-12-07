"""
Weekly Options Scout - Find high-probability credit spread opportunities
"""
import numpy as np
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, date
from market_data import PolygonService
from analytics.strategy_selector import StrategySelector
from services.trade_builder import enrich_trade_suggestions
from services.universe_service import UniverseService
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

# Cache for market data (simple in-memory cache with basic expiry handling concept)
# In a real system, use Redis or similar.
_MARKET_DATA_CACHE = {}
_CACHE_EXPIRY = 24 * 3600  # 24 hours

def get_cached_market_data(symbol):
    entry = _MARKET_DATA_CACHE.get(symbol)
    if entry:
        timestamp, data = entry
        if (datetime.now() - timestamp).total_seconds() < _CACHE_EXPIRY:
            return data
    return None

def set_cached_market_data(symbol, data):
    _MARKET_DATA_CACHE[symbol] = (datetime.now(), data)


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

    # Initialize PolygonService synchronously
    service = None
    try:
        service = PolygonService()
    except Exception:
        pass

    # Removed broken async batching. Falling back to synchronous calls loop below.
    # The subsequent logic handles fetching data via 'service' if cache is missing.

    for opp_config in opportunities:
        symbol = opp_config['symbol']

        current_price = 100.0
        cached = get_cached_market_data(symbol)

        if cached:
            current_price = cached.get("day", {}).get("c") or cached.get("lastTrade", {}).get("p") or 100.0
        elif service:
             try:
                 hist = service.get_historical_prices(symbol, days=5)
                 if hist and hist.get('prices'):
                    current_price = hist['prices'][-1]
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
            'reward_risk': 2.0
        }

        if service:
            try:
                opp['trend'] = service.get_trend(symbol)
                opp['iv_rank'] = service.get_iv_rank(symbol)
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

            except:
                pass

        processed_opportunities.append(opp)

    # --- Enrich & Filter ---
    market_data_enrich = {}
    if service:
        for opp in processed_opportunities:
            symbol = opp['symbol']

            cached = get_cached_market_data(symbol)
            bid, ask = 0.0, 0.0
            if cached:
                q = cached.get("lastQuote", {})
                bid = q.get("P", 0.0) or q.get("b", 0.0) # Polygon variation safety
                ask = q.get("p", 0.0) or q.get("a", 0.0)

            if bid == 0 and ask == 0:
                quote = service.get_recent_quote(symbol)
                bid = quote.get("bid", 0.0)
                ask = quote.get("ask", 0.0)

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
    ] if service else processed_opportunities

    enriched_opportunities = enrich_trade_suggestions(
        filtered_opportunities,
        100000,
        market_data_enrich,
        []
    )

    print(
        f"[Scanner] filtered_opportunities={len(filtered_opportunities)}, "
        f"enriched={len(enriched_opportunities)}, "
        f"market_data={len(market_data_enrich)}"
    )

    # Final Scoring
    final_candidates = []
    for cand in enriched_opportunities:
        # Always recompute score to avoid stale or legacy constants
        metrics = cand.get("metrics") or {}
        iv_rank = metrics.get("iv_rank")
        if iv_rank is None:
            iv_rank = cand.get("iv_rank")

        pop = metrics.get("probability_of_profit")
        rr = metrics.get("reward_to_risk") or cand.get("reward_risk")

        components = []
        if iv_rank is not None:
            # Prefer high IV for credit, low for debit?
            # Scanner usually Debit logic in defaults (see above), but enriched might switch.
            # Assuming simple "higher IV rank is better" for selling, but here defaults are debit spreads...
            # Actually defaults are Debit. But let's just use raw rank as component 0-1.
            components.append(iv_rank / 100.0)

        if pop is not None:
            components.append(pop)

        if rr is not None:
            components.append(min(rr, 3.0) / 3.0) # Cap R/R at 3 for scoring normalization

        raw_score = 100 * sum(components) / len(components) if components else None

        cand['score'] = raw_score

        symbol = cand.get("symbol") or cand.get("ticker")

        # Logging safety: cand.get('metrics') might be None, so .get({}, {}) is safer or explicit check
        metrics_debug = cand.get('metrics') or {}
        print(f"{symbol} score={cand.get('score')} ev={metrics_debug.get('expected_value')}")

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
    # ... existing main block ...
    pass
