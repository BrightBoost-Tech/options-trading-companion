from typing import List, Dict, Any, Optional
import datetime
# from .trade_builder import SafetySelectionLayer # Removed because it does not exist in trade_builder.py
from ..models import SpreadPosition
# Removed WorkflowOrchestrator import to avoid circular dependency
# from .workflow_orchestrator import WorkflowOrchestrator

# Using services to fetch context is safer than direct imports
from ..analytics.conviction_service import ConvictionService
from ..analytics.iv_regime_service import IVRegimeService

class RiskBudgetEngine:
    """
    Computes risk utilization against defined budgets for strategies, underlyings, and global risk (VaR).
    """
    def __init__(self, default_strategy_cap=0.30, default_underlying_cap=0.20, max_var_pct=0.25):
        self.default_strategy_cap = default_strategy_cap
        self.default_underlying_cap = default_underlying_cap
        self.max_var_pct = max_var_pct

    def compute(self, current_positions: List[SpreadPosition], total_equity: float, risk_profile: str = "balanced") -> Dict[str, Any]:
        """
        Calculates current usage and remaining budgets.

        Returns:
            Dict containing:
            - usage: {strategy: val, underlying: val, var: val, greeks: {underlying: {delta: val, vega: val}}}
            - remaining: {strategy: val, underlying: val, var: val}
            - limits: {strategy: val, underlying: val, var: val}
        """
        usage = {
            "strategy": {},
            "underlying": {},
            "var": 0.0,
            "greeks": {} # underlying -> {delta: x, vega: y}
        }

        # Calculate usage
        for pos in current_positions:
            val = pos.current_value
            # Strategy Usage
            stype = pos.spread_type or "unknown"
            usage["strategy"][stype] = usage["strategy"].get(stype, 0.0) + val

            # Underlying Usage
            und = pos.underlying or "unknown"
            usage["underlying"][und] = usage["underlying"].get(und, 0.0) + val

            # VaR Usage (Approximated by net_cost/max loss for debit, or margin for credit)
            # Using net_cost if positive (debit), else approx margin.
            # Simplified: Use current_value as a proxy for exposure if net_cost not reliable
            risk_amt = max(pos.net_cost, pos.current_value) if pos.net_cost > 0 else (pos.current_value * 1.5) # Rough heuristic
            usage["var"] += risk_amt

            # Greeks Usage
            if und not in usage["greeks"]:
                usage["greeks"][und] = {"delta": 0.0, "vega": 0.0}
            usage["greeks"][und]["delta"] += abs(pos.delta)
            usage["greeks"][und]["vega"] += abs(pos.vega)

        # Calculate Limits
        # Adjust caps based on risk_profile if needed
        strat_cap_pct = self.default_strategy_cap
        und_cap_pct = self.default_underlying_cap
        var_cap_pct = self.max_var_pct

        if risk_profile == "aggressive":
            strat_cap_pct *= 1.5
            und_cap_pct *= 1.5
            var_cap_pct = 0.35 # Higher max risk
        elif risk_profile == "conservative":
            strat_cap_pct *= 0.7
            und_cap_pct *= 0.7
            var_cap_pct = 0.15

        limits = {
            "strategy": {k: total_equity * strat_cap_pct for k in usage["strategy"].keys()}, # limits for existing keys
            "underlying": {k: total_equity * und_cap_pct for k in usage["underlying"].keys()},
            "var": total_equity * var_cap_pct,
            "defaults": {
                "strategy": total_equity * strat_cap_pct,
                "underlying": total_equity * und_cap_pct
            }
        }

        # Calculate Remaining
        remaining = {
            "strategy": {},
            "underlying": {},
            "var": limits["var"] - usage["var"],
            "greeks": {} # TODO: Implement greek limits if needed
        }

        for k, v in usage["strategy"].items():
            limit = limits["strategy"].get(k, limits["defaults"]["strategy"])
            remaining["strategy"][k] = limit - v

        for k, v in usage["underlying"].items():
            limit = limits["underlying"].get(k, limits["defaults"]["underlying"])
            remaining["underlying"][k] = limit - v

        return {
            "usage": usage,
            "limits": limits,
            "remaining": remaining
        }

class RebalanceEngine:
    """
    Compares current holdings (SpreadPosition objects) to optimizer targets,
    generating buy/sell suggestions to bridge the gap.
    """

    def __init__(self, conviction_service: ConvictionService = None, iv_regime_service: IVRegimeService = None):
        self.conviction_service = conviction_service
        self.iv_regime_service = iv_regime_service

    def generate_trades(
        self,
        current_holdings: List[SpreadPosition],
        target_weights: Dict[str, float],
        total_equity: float,
        deployable_capital: float,
        pricing_data: Dict[str, float],
        market_context: Dict[str, Any] = None,  # Contains 'regime', 'vix', etc.
        risk_summary: Dict[str, Any] = None     # Contains budget info
    ) -> List[Dict[str, Any]]:
        """
        Generates buy/sell suggestions based on weight differences, enforcing risk budgets.

        Args:
            current_holdings: List of current SpreadPositions.
            target_weights: {ticker: target_pct} from optimizer.
            total_equity: Current Net Liquidity.
            deployable_capital: Cash available for new trades.
            pricing_data: {ticker: current_price} for valuation.
            market_context: Optional dictionary with market regime info.
            risk_summary: output from RiskBudgetEngine.compute().

        Returns:
            List of trade dictionaries compatible with SuggestionCard.
        """
        trades = []

        # 1. Map current holdings to weights
        current_weights = {}
        holding_map = {} # ticker -> SpreadPosition

        for pos in current_holdings:
            ticker = pos.ticker_key if hasattr(pos, 'ticker_key') else pos.ticker or pos.underlying
            val = pos.current_value
            weight = val / total_equity if total_equity > 0 else 0

            if ticker in current_weights:
                current_weights[ticker] += weight
            else:
                current_weights[ticker] = weight

            holding_map[ticker] = pos

        # 2. Identify all relevant tickers (current + target)
        all_tickers = set(current_weights.keys()).union(target_weights.keys())

        # Helper: Trace ID for lineage
        trace_id = market_context.get('trace_id') if market_context else None

        # Sort tickers to process sells first?
        # Actually, we should collect all potential trades then process.
        # But for now, let's just loop.

        sell_trades = []
        buy_trades = []

        for ticker in all_tickers:
            current_w = current_weights.get(ticker, 0.0)
            target_w = target_weights.get(ticker, 0.0)

            diff_w = target_w - current_w

            # Threshold for action (e.g. 1% drift)
            if abs(diff_w) < 0.01:
                continue

            diff_val = diff_w * total_equity
            price = pricing_data.get(ticker)

            if not price or price <= 0:
                continue

            # SELL Logic
            if diff_val < 0:
                if ticker not in holding_map:
                    continue

                sell_val = abs(diff_val)
                qty_to_sell = sell_val / price
                qty = int(round(qty_to_sell))
                if qty < 1:
                    continue

                sell_trades.append({
                    "ticker": ticker,
                    "action": "SELL",
                    "quantity": qty,
                    "reason": f"Overweight by {abs(diff_w)*100:.1f}%",
                    "price": price,
                    "est_value": qty * price,
                    "type": "rebalance_sell",
                    "trace_id": trace_id
                })

            # BUY Logic
            elif diff_val > 0:
                buy_val = diff_val

                # Check Risk Budgets
                clamp_reason = []

                # 1. Global Capital / VaR
                if risk_summary:
                    remaining_var = risk_summary["remaining"]["var"]
                    if buy_val > remaining_var:
                        buy_val = max(0, remaining_var)
                        clamp_reason.append(f"Clamped by Global VaR Budget")

                # 2. Underlying Budget
                if risk_summary:
                    # Parse underlying from ticker (e.g. "AAPL")
                    # If ticker is option "AAPL 100C", underlying is "AAPL"
                    # Simple assumption: ticker is underlying for weight purposes
                    und = ticker
                    rem_und = risk_summary["remaining"]["underlying"].get(und, risk_summary["limits"]["defaults"]["underlying"])

                    if buy_val > rem_und:
                        buy_val = max(0, rem_und)
                        clamp_reason.append(f"Clamped by Underlying Limit")

                # 3. Strategy Budget (Harder if we don't know strategy of new buy)
                # If we assume we are adding to existing position, we know type.
                # If new, we might assume 'vertical' or similar.
                # Skip for now if unknown.

                # 4. Deployable Capital (Cash)
                # Max 25% of deployable per trade
                safe_cap = deployable_capital * 0.25
                if buy_val > safe_cap:
                    buy_val = safe_cap
                    clamp_reason.append("Clamped by 25% Cash Rule")

                # Final check
                if buy_val <= 0:
                    continue

                qty_to_buy = buy_val / price
                qty = int(round(qty_to_buy))

                if qty < 1:
                    continue

                trade = {
                    "ticker": ticker,
                    "action": "BUY",
                    "quantity": qty,
                    "reason": f"Underweight by {diff_w*100:.1f}%",
                    "price": price,
                    "est_value": qty * price,
                    "type": "rebalance_buy",
                    "trace_id": trace_id
                }
                if clamp_reason:
                    trade["clamp_info"] = "; ".join(clamp_reason)
                    trade["reason"] += " (Clamped)"

                buy_trades.append(trade)

        # Prioritize SELLs (liquidity generation) before BUYs
        trades = sell_trades + buy_trades

        return trades
