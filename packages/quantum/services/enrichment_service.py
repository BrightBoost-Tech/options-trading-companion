# packages/quantum/services/enrichment_service.py
from market_data import PolygonService
import numpy as np

def enrich_holdings_with_analytics(holdings: list) -> list:
    """
    Enriches a list of holdings with analytics data from Polygon.
    """
    try:
        service = PolygonService()
    except Exception:
        service = None

    for holding in holdings:
        symbol = holding.get('symbol')
        if not symbol or not service:
            holding['delta'] = 0.5
            holding['theta'] = -0.05
            holding['iv_rank'] = 50.0  # Default IV Rank
            continue

        try:
            # Get real IV Rank
            iv_rank = service.get_iv_rank(symbol)
            holding['iv_rank'] = iv_rank

            # Use static defaults for other analytics until real calculations are available
            holding['delta'] = 0.5
            holding['theta'] = -0.05

        except Exception as e:
            print(f"Could not enrich {symbol}: {e}")
            # Fallback to defaults on a per-holding basis
            holding['delta'] = 0.5
            holding['theta'] = -0.05
            holding['iv_rank'] = 50.0

    return holdings
