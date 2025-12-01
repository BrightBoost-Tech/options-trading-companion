"""
Weekly Options Scout - Find high-probability credit spread opportunities
"""
import numpy as np
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, date
from market_data import PolygonService
from analytics.strategy_selector import StrategySelector
from services.trade_builder import enrich_trade_suggestions
from services.universe_service import UniverseService
from supabase import Client


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
    # Initialize UniverseService if supabase is available
    if supabase_client:
        try:
            universe_service = UniverseService(supabase_client)
        except Exception:
            pass

    # If symbols are provided, it uses them (e.g. for custom scans).
    # Otherwise, it defaults to the Universe Service (Funnel) or broad market scan list.
    opportunities = []

    if not symbols:
        # Use Universe Funnel
        if universe_service:
            print("Scanning via Universe Funnel...")
            candidates = universe_service.get_scan_candidates(limit=40)
            # candidates is now a list of dicts: {'symbol': '...', 'earnings_date': ...}
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
            opportunities = market_scan_universe
    else:
        # Create opportunity skeletons for provided symbols
        # Removed the [:15] limit, use higher cap if necessary but generally respect input
        limit_symbols = symbols[:100] if len(symbols) > 100 else symbols
        for sym in limit_symbols:
            opportunities.append({
                'symbol': sym,
                'width': 5, # Default width
                'credit_target': 1.00 # Default credit target
            })

    # Prepare list for processing
    processed_opportunities = []

    # Try to update with real prices if available
    # service is already imported but we need to instantiate it if not done earlier
    # NOTE: UniverseService might have instantiated one, but options_scanner typically
    # manages its own market connection or reuses one.
    # To be safe and consistent with legacy code structure:
    service = None
    try:
        service = PolygonService()
    except Exception:
        pass

    for opp_config in opportunities:
        symbol = opp_config['symbol']

        # GUARDRAIL 1: Quick Liquidity & Earnings Check
        # We can implement earnings check if we had data, for now skipped or rely on score.
        # Liquidity check happens in enrich_trade_suggestions via apply_slippage_guardrail.
        # But we can pre-filter here if bid/ask spread is massive to save API calls?
        # Actually enrich_trade_suggestions fetches quotes.
        # Let's trust enrich_trade_suggestions for heavy lifting to keep flow cleaner.

        # Default fallback values
        opp = {
            'symbol': symbol,
            'type': 'Debit Call Spread', # Default to Debit Call Spread as requested (Directional Debit)
            'short_strike': 105,
            'long_strike': 100,
            'expiry': (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
            'dte': 30,
            'credit': opp_config.get('credit_target', 1.0), # Keeping this key for compatibility, though it's debit
            'width': opp_config.get('width', 5),
            'iv_rank': None,
            'delta': 0.30,
            'underlying_price': 100.00,
            'max_gain': (opp_config.get('width', 5) - 1.0) * 100, # Approx gain for debit spread
            'max_loss': 1.0 * 100, # Approx cost
            'trend': 'UP', # Mock trend
            'reward_risk': 2.0 # Good R/R for debit
        }

        if service:
            try:
                # Get latest daily bar (approximate current price)
                hist = service.get_historical_prices(symbol, days=5)
                if hist and hist.get('prices'):
                    current_price = hist['prices'][-1]
                    opp['underlying_price'] = current_price

                    # Trend Check
                    trend = service.get_trend(symbol)
                    opp['trend'] = trend

                    # 1. Decide Strategy based on Trend (Directional Debit)
                    if trend == "DOWN":
                        opp['type'] = 'Debit Put Spread'
                        # Target OTM Puts
                        target_long = current_price * 0.95
                        target_short = current_price * 0.90 # wider width?
                    else:
                        opp['type'] = 'Debit Call Spread'
                        # Target OTM Calls
                        target_long = current_price * 1.02
                        target_short = current_price * 1.07

                    # Rounding logic
                    if current_price > 200:
                        step = 5
                    elif current_price > 50:
                        step = 1
                    else:
                        step = 0.5

                    long_strike = round(target_long / step) * step
                    short_strike = round(target_short / step) * step

                    # Ensure width is at least step size
                    if abs(short_strike - long_strike) < step:
                        if trend == "DOWN": short_strike = long_strike - step
                        else: short_strike = long_strike + step

                    # Update Opportunity
                    opp['long_strike'] = long_strike
                    opp['short_strike'] = short_strike
                    opp['width'] = abs(short_strike - long_strike)

                    opp['iv_rank'] = service.get_iv_rank(symbol)

                    # Earnings Guardrail
                    # If we have an earnings_date from the universe, check it.
                    e_date_str = opp_config.get('earnings_date')
                    if e_date_str:
                        try:
                            e_date = datetime.fromisoformat(e_date_str).date()
                            days_to_earnings = (e_date - date.today()).days
                            if 0 <= days_to_earnings <= 7:
                                print(f"Skipping {symbol} due to earnings in {days_to_earnings} days.")
                                continue # Skip this opportunity
                        except Exception:
                            pass

            except Exception as e:
                # print(f"Could not fetch price for {symbol}: {e}")
                # Keep defaults
                pass

        processed_opportunities.append(opp)

    # --- New Decision Funnel ---
    market_data = {}
    if service:
        # Optimize: Fetch quotes in batch if possible?
        # PolygonService doesn't support batch quotes yet cleanly.
        for opp in processed_opportunities:
            symbol = opp['symbol']
            quote = service.get_recent_quote(symbol)

            # GUARDRAIL 2: Bid/Ask Spread Filter (Pre-scoring)
            bid = quote.get("bid", 0.0)
            ask = quote.get("ask", 0.0)
            if bid > 0:
                spread_pct = (ask - bid) / bid
                if spread_pct > 0.10: # >10% spread is too illiquid
                    continue

            market_data[symbol] = {
                "price": opp['underlying_price'],
                "iv_rank": service.get_iv_rank(symbol),
                "trend": service.get_trend(symbol),
                "sector": service.get_ticker_details(symbol).get('sic_description'),
                "bid": bid,
                "ask": ask
            }

    # Filter processed_opportunities to only include those that passed the liquidity guardrail
    filtered_opportunities = [
        opp for opp in processed_opportunities
        if opp['symbol'] in market_data
    ] if service else processed_opportunities

    enriched_opportunities = enrich_trade_suggestions(
        filtered_opportunities,
        100000, # Mock portfolio value for sizing
        market_data,
        [] # No existing positions for scanner
    )

    print(
        f"[Scanner] filtered_opportunities={len(filtered_opportunities)}, "
        f"enriched={len(enriched_opportunities)}, "
        f"market_data={len(market_data)}"
    )

    # SCORING UPGRADE (Step 4 of Plan)
    # Apply enhanced scoring logic tailored for directional debit/credit
    final_candidates = []
    for cand in enriched_opportunities:
        score = cand.get('score', 0)
        sym = cand['symbol']
        mdata = market_data.get(sym, {})

        # Trend Alignment Bonus
        trend = mdata.get('trend', 'NEUTRAL')
        direction = cand.get('direction', 'neutral') # enrich might not set direction well for spreads?
        # Assuming strategy type implies direction or we check trend match

        # IV Rank Logic
        # Debit -> Favor Low IV. Credit -> Favor High IV.
        iv_rank = mdata.get('iv_rank')
        strategy = cand.get('type', '')

        if iv_rank is not None:
            if 'Credit' in strategy and iv_rank > 50:
                score += 10
            elif 'Debit' in strategy and iv_rank < 50:
                score += 10

        cand['score'] = min(100, score)
        final_candidates.append(cand)

    # Sort by score (highest first)
    final_candidates.sort(key=lambda x: x.get('score', 0), reverse=True)

    if not final_candidates:
        print("[Scanner] WARNING: final_candidates is empty after scoring. "
              f"processed={len(processed_opportunities)}, "
              f"filtered={len(filtered_opportunities)}, "
              f"enriched={len(enriched_opportunities)}")

    return final_candidates


if __name__ == '__main__':
    print("Weekly Options Scout")
    print("=" * 60)
    print()
    
    opportunities = scan_for_opportunities()
    
    print(f"Found {len(opportunities)} opportunities\n")
    print("Top 3 Trades This Week:")
    print("-" * 60)
    
    for i, opp in enumerate(opportunities[:3], 1):
        print(f"\n#{i} - {opp['symbol']} {opp['type']}")
        print(f"   Score: {opp.get('score', 'N/A')}/100")
        print(f"   Strikes: {opp['short_strike']}/{opp['long_strike']}")
        print(f"   Credit: ${opp['credit']:.2f} (Max Gain: ${opp['max_gain']:.0f})")
        print(f"   Risk/Reward: {opp['risk_reward']}")
        print(f"   Expiry: {opp['expiry']} ({opp['dte']} DTE)")
        print(f"   Why:")
        for reason in opp['reasons'][:3]:
            print(f"      • {reason}")
