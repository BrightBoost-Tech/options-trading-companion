from typing import List, Dict, Any, Optional
from supabase import Client
from datetime import datetime, timezone
import math

from packages.quantum.models import SpreadPosition, Holding
from packages.quantum.services.sizing_engine import calculate_sizing
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, RegimeState
from packages.quantum.analytics.scoring import calculate_unified_score
from packages.quantum.services.execution_service import ExecutionService

class RebalanceEngine:
    """
    Generates actionable trade instructions to rebalance a portfolio
    based on optimizer target weights.
    """

    def __init__(self, supabase: Client = None):
        self.supabase = supabase
        self.regime_engine = RegimeEngineV3(supabase) if supabase else None
        self.execution_service = ExecutionService(supabase) if supabase else None

    def generate_trades(
        self,
        current_spreads: List[SpreadPosition],
        raw_positions: List[Dict], # including stocks
        cash_balance: float,
        target_weights: List[Dict], # [{type: spread|stock, symbol: str, target_weight: float}, ...]
        profile: str = "balanced",
        conviction_map: Dict[str, float] = None,
        regime_context: Dict[str, Any] = None,
        user_id: str = None
    ) -> List[Dict]:
        """
        Core logic: compare current vs target and emit trades.
        """
        trades = []
        if conviction_map is None:
            conviction_map = {}

        # 1. Map Targets
        # Targets structure: {"type": "spread", "symbol": "...", "target_allocation": 0.15}
        target_map = {t["symbol"]: t["target_allocation"] for t in target_weights}

        # Calculate Total Portfolio Value for sizing
        stocks = [p for p in raw_positions if p.get("symbol", "").upper() not in ["USD", "CUR:USD", "CASH"] and len(p.get("symbol", "")) <= 6]

        total_equity = sum(s.current_value for s in current_spreads)
        total_equity += sum(float(s.get("current_value") or (s.get("quantity") * s.get("current_price"))) for s in stocks)
        total_portfolio_value = total_equity + cash_balance

        deployable_capital = cash_balance

        # Get Regime Snapshot for Scoring
        regime_snap = {"state": "normal"}
        if self.regime_engine:
             try:
                 gs = self.regime_engine.compute_global_snapshot(datetime.now())
                 regime_snap = gs.to_dict()
             except:
                 pass

        # Use passed regime_context if available (it might be fresher or from V3 logic in API)
        # But 'regime_snap' is used for `calculate_unified_score`.
        # For RebalanceScore, we might use regime_context['current_regime'] (e.g. "normal", "shock").

        # 2. Process Spreads (Existing vs Target)
        for target in target_weights:
            symbol = target["symbol"]
            target_w = target["target_allocation"]

            # Find matching holding
            existing_spread = next((s for s in current_spreads if s.ticker == symbol), None)
            existing_stock = next((s for s in stocks if s["symbol"] == symbol), None)

            current_val = 0.0
            current_w = 0.0

            if existing_spread:
                current_val = existing_spread.current_value
                item_type = "spread"
                price_unit = abs(existing_spread.current_value / (existing_spread.quantity or 1)) # approx price per unit
            elif existing_stock:
                current_val = float(existing_stock.get("current_value") or 0)
                item_type = "stock"
                price_unit = float(existing_stock.get("current_price") or 0)
            else:
                continue

            if total_portfolio_value > 0:
                current_w = current_val / total_portfolio_value

            diff_w = target_w - current_w

            # Threshold to trade (e.g. 2% deviation)
            if abs(diff_w) < 0.02:
                continue

            # ACTION
            desired_val_change = diff_w * total_portfolio_value

            if desired_val_change > 0:
                side = "buy" # or "increase"
                action = "increase"
            else:
                side = "sell" # or "decrease"
                action = "decrease"

            # Sizing
            if price_unit <= 0: continue

            qty_delta = abs(desired_val_change) / price_unit
            qty_delta = math.floor(qty_delta)

            if qty_delta == 0: continue

            # Risk Check (for buys)
            reason = "Rebalance to target"
            if side == "buy":
                cost = qty_delta * price_unit

                # Max 25% deployable capital per NEW spread (or addition)
                max_allocation = deployable_capital * 0.25
                if cost > max_allocation:
                     qty_delta = math.floor(max_allocation / price_unit)
                     reason = "Rebalance (capped by 25% rule)"
                     cost = qty_delta * price_unit

                if cost > deployable_capital:
                    qty_delta = math.floor(deployable_capital / price_unit)
                    reason = "Rebalance (capped by cash)"

                if qty_delta == 0: continue

            # --- Rebalance Score Calculation ---
            # Inputs:
            # 1. Conviction (0-1)
            # 2. Execution Cost Penalty
            # 3. Risk/Regime Penalty

            # 1. Conviction
            # Use underlying for lookup if possible, else symbol
            lookup_key = existing_spread.underlying if existing_spread else symbol
            conviction = conviction_map.get(lookup_key, conviction_map.get(symbol, 0.5))

            # Base Score: Conviction * 100 (0-100 scale)
            base_score = conviction * 100.0

            # 2. Execution Cost Penalty
            # Use ExecutionService logic
            exec_cost_per_unit = 0.05 # default fallback
            if self.execution_service:
                # We try to use historical data if user_id is provided
                exec_cost_per_unit = self.execution_service.estimate_execution_cost(
                    symbol=symbol,
                    user_id=user_id,
                    entry_cost=price_unit,
                    num_legs=1 # Simplified, exact legs might be hard here
                )

            # ROI impact of execution cost: Cost / Price
            cost_roi = 0.0
            if price_unit > 0:
                cost_roi = exec_cost_per_unit / price_unit

            # Scaling: 1% cost = 5 points penalty (Factor 500, similar to scoring.py)
            exec_penalty_points = cost_roi * 500.0

            # 3. Regime Penalty
            # Use simplified logic based on scoring.py patterns
            regime_penalty_points = 0.0
            if regime_context:
                current_regime = regime_context.get("current_regime", "normal")
                # regime_context uses "normal", "high_vol", "panic" (mapped from RegimeState)

                # Simple penalties
                if current_regime == "panic": # Shock
                    regime_penalty_points = 15.0 # High penalty in panic
                elif current_regime == "high_vol": # Elevated
                    # If we are buying (adding risk) in high vol, maybe small penalty unless conviction is high
                    if side == "buy":
                        regime_penalty_points = 5.0

            # 4. Risk Penalty
            # Use diff_w as a proxy for 'urgency' but maybe not 'risk'.
            # If we are shorting (selling), risk is actually reducing.
            # Let's keep it simple: RebalanceScore is about quality of holding + regime.
            # User said: "risk_penalty (portfolio greek deltas / concentration / regime penalty)"
            risk_penalty_points = 0.0
            # Concentration check: if target > 20%, maybe add penalty?
            if target_w > 0.20:
                risk_penalty_points += 5.0

            # Final Score Calculation
            # RebalanceScore = Conviction - Cost - Regime - Risk
            rebalance_score = base_score - exec_penalty_points - regime_penalty_points - risk_penalty_points

            # Clamp 0-100
            rebalance_score = max(0.0, min(100.0, rebalance_score))

            # Components for API
            score_components = {
                "conviction_score": base_score,
                "execution_cost_penalty": exec_penalty_points,
                "regime_penalty": regime_penalty_points,
                "risk_penalty": risk_penalty_points,
                "raw_cost_roi": cost_roi
            }

            # Construct Trade
            trade = {
                "side": action,
                "kind": item_type,
                "symbol": symbol,
                "quantity": qty_delta,
                "limit_price": price_unit,
                "reason": f"Target: {target_w:.1%}, Current: {current_w:.1%}. {reason}",
                "target_weight": target_w,
                "current_weight": current_w,
                "risk_metadata": {
                    "diff_value": desired_val_change
                },
                "score": rebalance_score, # Use RebalanceScore for sorting
                "rebalance_score": rebalance_score,
                "score_components": score_components,
                "ev": None # Explicitly None to avoid fake EV
            }
            trades.append(trade)

        # Sort by Score
        trades.sort(key=lambda x: x['score'], reverse=True)

        return trades
