from typing import List, Dict, Any, Optional
from packages.quantum.models import UnifiedPosition, Holding
from packages.quantum.services.options_utils import parse_option_symbol

class RiskEngine:
    @staticmethod
    def build_unified_positions(holdings: List[Dict[str, Any]]) -> List[UnifiedPosition]:
        """
        Convert DB positions (enriched holdings dicts) into UnifiedPosition objects.
        """
        unified = []
        for h in holdings:
            # Determine asset type if missing (fallback)
            asset_type = h.get("asset_type", "UNKNOWN")
            symbol = h.get("symbol", "")

            qty = float(h.get("quantity", 0))

            # Enriched fields
            delta_unit = float(h.get("delta", 0))
            gamma_unit = float(h.get("gamma", 0))
            theta_unit = float(h.get("theta", 0))
            vega_unit = float(h.get("vega", 0))

            pos_delta = 0.0
            pos_gamma = 0.0
            pos_theta = 0.0
            pos_vega = 0.0

            # Asset type specific logic
            if asset_type == "EQUITY":
                # Equity delta is exactly the quantity (1 share = 1 delta)
                pos_delta = qty
                # Others zero
            elif asset_type == "OPTION":
                multiplier = 100.0
                pos_delta = delta_unit * multiplier * qty
                pos_gamma = gamma_unit * multiplier * qty
                pos_theta = theta_unit * multiplier * qty
                pos_vega = vega_unit * multiplier * qty
            elif asset_type == "CASH":
                pos_delta = 0.0
            else:
                 # Check if we should fallback to Equity for UNKNOWN (likely VTSI scenario)
                 # Phase 8.1 classifier should have set it to EQUITY if it wasn't OPTION or CASH.
                 # If still unknown, treat as 0 risk or assume 1 delta if it has price?
                 # Safe default: 0 risk.
                 pass

            # Is Locked?
            is_locked = h.get("is_locked", False)
            optimizer_role = h.get("optimizer_role", "TARGET")

            # Special case for VTSI (redundant if classifier worked, but safe)
            if symbol == "VTSI" and not is_locked:
                is_locked = True
                optimizer_role = "IGNORE"

            up = UnifiedPosition(
                symbol=symbol,
                security_id=h.get("security_id"),
                asset_type=asset_type,
                quantity=qty,
                cost_basis=float(h.get("cost_basis", 0) or 0),
                current_price=float(h.get("current_price", 0) or 0),
                sector=h.get("sector"),
                industry=h.get("industry"),
                strategy_tag=h.get("strategy_tag"),
                delta=pos_delta,
                beta_weighted_delta=0.0, # Filled later or in summary
                gamma=pos_gamma,
                theta=pos_theta,
                vega=pos_vega,
                is_locked=is_locked,
                optimizer_role=optimizer_role
            )
            unified.append(up)

        return unified

    @staticmethod
    def compute_risk_summary(unified_positions: List[UnifiedPosition]) -> Dict[str, Any]:
        """
        Aggregates risk metrics.
        """
        total_equity = 0.0
        portfolio_delta = 0.0
        portfolio_gamma = 0.0
        portfolio_theta = 0.0
        portfolio_vega = 0.0

        exposure_by_sector = {}
        exposure_by_strategy = {}

        for p in unified_positions:
            multiplier = 100.0 if p.asset_type == 'OPTION' else 1.0

            # Value Calculation
            # Option value = price * 100 * qty
            # Equity value = price * qty
            # Cash value = price * qty (usually 1 * amount)
            mkt_val = p.current_price * p.quantity * multiplier

            # Only add positive value to total equity? Net Liq includes short value (negative).
            total_equity += mkt_val

            portfolio_delta += p.delta
            portfolio_gamma += p.gamma
            portfolio_theta += p.theta
            portfolio_vega += p.vega

            # Sector (Only use market value magnitude for exposure? Or net?)
            # Usually exposure is long + short value (gross) or net.
            # Let's use Net Value for allocation pie chart.
            # If short, it subtracts? Or we want absolute exposure?
            # Pie charts usually handle positive values.
            # Let's use max(0, mkt_val) for pie or just mkt_val.
            # Standard: Long Value.
            # Spec doesn't specify. Assuming Long-only pie for "Allocation".
            # If we have shorts, we might need a separate visualization.
            # We'll sum signed value for now.

            if p.asset_type not in ["CASH", "CRYPTO"]:
                sec = p.sector or "Unknown"
                exposure_by_sector[sec] = exposure_by_sector.get(sec, 0.0) + mkt_val

                strat = p.strategy_tag or (p.asset_type if p.asset_type != 'UNKNOWN' else "Other")
                exposure_by_strategy[strat] = exposure_by_strategy.get(strat, 0.0) + mkt_val

        # Normalize percentages based on Invested Capital (Total Equity - Cash)?
        # Or Total Net Liq.
        # "pct_of_equity" usually means % of Net Liquidation Value.

        # Avoid division by zero
        if abs(total_equity) < 0.01:
            total_equity = 1.0 # arbitrary to avoid crash

        for k in exposure_by_sector:
            exposure_by_sector[k] = (exposure_by_sector[k] / total_equity) * 100
        for k in exposure_by_strategy:
            exposure_by_strategy[k] = (exposure_by_strategy[k] / total_equity) * 100

        return {
            "summary": {
                "netLiquidation": total_equity,
                "plDay": 0.0, # Placeholder
                "betaSpy": portfolio_delta # Placeholder: Raw Portfolio Delta as stub
            },
            "exposure": {
                "bySector": exposure_by_sector,
                "byStrategy": exposure_by_strategy
            },
            "greeks": {
                "portfolioDelta": portfolio_delta,
                "portfolioTheta": portfolio_theta,
                "portfolioVega": portfolio_vega,
                "portfolioGamma": portfolio_gamma
            }
        }
