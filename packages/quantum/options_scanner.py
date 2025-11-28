"""
Weekly Options Scout - Find high-probability credit spread opportunities
"""
import numpy as np
from typing import List, Dict
from datetime import datetime, timedelta
from market_data import PolygonService
from analytics.strategy_selector import StrategySelector
from services.trade_builder import enrich_trade_suggestions


def scan_for_opportunities(symbols: List[str] = None) -> List[Dict]:
    """
    Scan for weekly option opportunities.
    This function scans a predefined market-wide universe of tickers for opportunities.
    It does NOT use the user's holdings, which is the job of the Optimizer.
    """

    # If symbols are provided, it uses them (e.g. for custom scans).
    # Otherwise, it defaults to a broad market scan list.
    if not symbols:
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
        opportunities = []
        for sym in symbols[:15]: # Limit to 15 symbols to avoid timeout
            opportunities.append({
                'symbol': sym,
                'width': 5, # Default width
                'credit_target': 1.00 # Default credit target
            })

    # Prepare list for processing
    processed_opportunities = []

    # Try to update with real prices if available
    service = None
    try:
        service = PolygonService()
    except Exception:
        pass

    for opp_config in opportunities:
        symbol = opp_config['symbol']

        # Default fallback values
        opp = {
            'symbol': symbol,
            'type': 'Credit Put Spread',
            'short_strike': 100,
            'long_strike': 95,
            'expiry': (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
            'dte': 30,
            'credit': opp_config.get('credit_target', 1.0),
            'width': opp_config.get('width', 5),
            'iv_rank': None,
            'delta': -0.30,
            'underlying_price': 105.00,
            'max_gain': opp_config.get('credit_target', 1.0) * 100,
            'max_loss': (opp_config.get('width', 5) - opp_config.get('credit_target', 1.0)) * 100,
            'trend': 'UP', # Mock trend
            'reward_risk': 0.33 # Mock reward/risk
        }

        if service:
            try:
                # Get latest daily bar (approximate current price)
                hist = service.get_historical_prices(symbol, days=5)
                if hist and hist.get('prices'):
                    current_price = hist['prices'][-1]
                    opp['underlying_price'] = current_price

                    # Construct realistic trade parameters based on price
                    # Target 3-5% OTM for Put Spread
                    target_short = current_price * 0.96

                    # Rounding logic
                    if current_price > 200:
                        step = 5
                    elif current_price > 50:
                        step = 1
                    else:
                        step = 0.5

                    short_strike = round(target_short / step) * step
                    width = opp['width']
                    long_strike = short_strike - width

                    # Update Opportunity
                    opp['short_strike'] = short_strike
                    opp['long_strike'] = long_strike

                    opp['iv_rank'] = service.get_iv_rank(symbol)

            except Exception as e:
                # print(f"Could not fetch price for {symbol}: {e}")
                # Keep defaults
                pass

        processed_opportunities.append(opp)

    # --- New Decision Funnel ---
    market_data = {}
    if service:
        for opp in processed_opportunities:
            symbol = opp['symbol']
            market_data[symbol] = {
                "price": opp['underlying_price'],
                "iv_rank": service.get_iv_rank(symbol),
                "trend": service.get_trend(symbol),
                "sector": service.get_ticker_details(symbol).get('sic_description')
            }

    enriched_opportunities = enrich_trade_suggestions(
        processed_opportunities,
        100000, # Mock portfolio value for sizing
        market_data,
        [] # No existing positions for scanner
    )

    # Sort by score (highest first)
    enriched_opportunities.sort(key=lambda x: x.get('score', 0), reverse=True)
    
    return enriched_opportunities


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
