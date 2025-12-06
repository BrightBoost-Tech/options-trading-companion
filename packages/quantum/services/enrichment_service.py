# packages/quantum/services/enrichment_service.py
from market_data import PolygonService
import numpy as np
from analytics.sector_mapper import SectorMapper

def enrich_holdings_with_analytics(holdings: list) -> list:
    """
    Enriches a list of holdings with analytics data from Polygon.
    Also maps sectors/industries via SectorMapper (Phase 8.1).
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
            holding['iv_rank'] = None
            continue

        try:
            # Get real IV Rank
            raw_iv_rank = service.get_iv_rank(symbol)

            if raw_iv_rank is None:
                iv_rank = None
            else:
                iv = float(raw_iv_rank)
                # Clamp 0-100 (Service now guarantees 0-100 scale)
                iv_rank = max(0.0, min(100.0, iv))

            holding['iv_rank'] = iv_rank

            # Use static defaults for other analytics until real calculations are available
            holding['delta'] = 0.5
            holding['theta'] = -0.05

        except Exception as e:
            print(f"Could not enrich {symbol}: {e}")
            # Fallback to defaults on a per-holding basis
            holding['delta'] = 0.5
            holding['theta'] = -0.05
            holding['iv_rank'] = None

        # Calculate P&L Severity
        try:
            current_value = holding.get('current_price', 0) * holding.get('quantity', 0)
            cost_basis_total = holding.get('cost_basis', 0) * holding.get('quantity', 0) # Assuming cost_basis is per share
            # Note: Memory says "backend's /portfolio/snapshot endpoint expects cost_basis field ... to be the total cost".
            # Checking existing code or context:
            # If cost_basis is total cost, then we use it directly.
            # Usually 'cost_basis' on a holding object from DB is often total or per share depending on schema.
            # Let's assume standardized "cost_basis" field is Total Cost based on memory
            # "The backend's /portfolio/snapshot endpoint expects the cost_basis field on a position to be the total cost"

            # Let's re-read the holding dict structure if possible.
            # In 'PortfolioHoldingsTable.tsx', it calculates:
            # const costBasis = h.cost_basis || 0;
            # const totalCost = h.quantity * costBasis;
            # This implies `h.cost_basis` is PER SHARE.
            # So `cost_basis_total` should be `holding['cost_basis'] * holding['quantity']` if `cost_basis` is per share.
            # However, if the memory says "cost_basis field ... to be the total cost", there is a conflict.
            # I will trust the Frontend implementation I just read: `const totalCost = h.quantity * costBasis;`.
            # So `holding['cost_basis']` is likely per-share or unit cost.

            # Let's calculate percentage based on unit price to be safe, or total.
            # (Current - Basis) / Basis

            cb = holding.get('cost_basis', 0)
            cp = holding.get('current_price', 0)

            if cb and cb > 0:
                pnl_percent = ((cp - cb) / cb) * 100
                holding['pnl_percent'] = pnl_percent

                if pnl_percent <= -90:
                    holding['pnl_severity'] = "critical"
                elif pnl_percent <= -50:
                    holding['pnl_severity'] = "warning"
                elif pnl_percent >= 100:
                    holding['pnl_severity'] = "success"
                else:
                    holding['pnl_severity'] = "normal"
            else:
                holding['pnl_percent'] = 0
                holding['pnl_severity'] = "normal"

        except Exception:
             holding['pnl_severity'] = "normal"

        # Sector Mapping (Phase 8.1)
        # Only populate if missing or if we want to overwrite
        if not holding.get('sector'):
             sector, industry = SectorMapper.get_sector_industry(symbol)
             if sector:
                 holding['sector'] = sector
             if industry:
                 holding['industry'] = industry

    return holdings
