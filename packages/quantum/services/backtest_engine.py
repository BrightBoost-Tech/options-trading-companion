import uuid
import random
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig, BacktestRequestV3
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.regime_scoring import ScoringEngine, ConvictionTransform
from packages.quantum.analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
    run_historical_scoring
)
from packages.quantum.analytics.factors import calculate_trend, calculate_volatility, calculate_rsi
from packages.quantum.nested.backbone import infer_global_context, GlobalContext
from packages.quantum.execution.transaction_cost_model import TransactionCostModel

class BacktestRunResult(BaseModel):
    backtest_id: str
    trades: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]
    metrics: Dict[str, Any]

class BacktestEngine:
    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()
        self.scoring_engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )
        self.conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)
        self.lookback_window = 60  # Days needed for indicators

    def run_single(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        config: StrategyConfig,
        cost_model: CostModelConfig,
        seed: int,
        initial_equity: float
    ) -> BacktestRunResult:
        """
        Runs a single backtest pass stepping through daily bars.
        """
        rng = random.Random(seed)
        backtest_id = str(uuid.uuid4())

        # 1. Fetch Data
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Invalid date format. Use YYYY-MM-DD")

        # Fetch data with buffer
        fetch_start = start_dt - timedelta(days=self.lookback_window * 2) # Buffer
        days_needed = (end_dt - fetch_start).days + 10

        hist_data = self.polygon.get_historical_prices(
            symbol,
            days=days_needed,
            to_date=end_dt
        )

        dates = hist_data.get('dates', [])
        prices = hist_data.get('prices', [])

        if not dates or not prices:
             return BacktestRunResult(
                backtest_id=backtest_id,
                trades=[],
                events=[],
                equity_curve=[],
                metrics={}
            )

        # Map dates to indices
        date_map = {d: i for i, d in enumerate(dates)}

        # Determine start index
        start_idx = -1
        for i, d in enumerate(dates):
            if datetime.strptime(d, "%Y-%m-%d") >= start_dt:
                start_idx = i
                break

        if start_idx == -1 or start_idx < self.lookback_window:
             # Try to adjust if we have enough data but start_idx is too early
             if len(dates) > self.lookback_window and start_idx != -1:
                 pass # Use found start_idx
             elif len(dates) > self.lookback_window:
                 start_idx = self.lookback_window # Default to earliest possible
             else:
                return BacktestRunResult(
                    backtest_id=backtest_id,
                    trades=[],
                    events=[],
                    equity_curve=[],
                    metrics={}
                )

        # 2. Simulation State
        cash = initial_equity
        position = None # { "quantity": float, "entry_price": float, "entry_date": str, "id": str }
        trades = []
        events = []
        equity_curve = []

        # 3. Loop
        for i in range(start_idx, len(dates)):
            current_date = dates[i]
            current_price = prices[i]

            # Helper to calculate scoring
            # Slice strictly up to i inclusive
            price_slice = prices[:i+1]

            # --- Scoring Logic (Reused) ---
            trend = calculate_trend(price_slice)
            vol_annual = calculate_volatility(price_slice, window=30)
            rsi_val = calculate_rsi(price_slice, period=14)

            # Global Context
            features = {
                "spy_trend": trend.lower(),
                "vix_level": 20.0,
            }
            if vol_annual > 0.30: features["vix_level"] = 35.0
            elif vol_annual > 0.20: features["vix_level"] = 25.0
            else: features["vix_level"] = 15.0

            global_context: GlobalContext = infer_global_context(features)

            regime_mapped = map_market_regime({
                "state": global_context.global_regime,
                "vol_annual": vol_annual
            })

            # Score
            trend_score = 100.0 if trend == "UP" else (0.0 if trend == "DOWN" else 50.0)
            vol_score = 50.0
            if vol_annual < 0.15: vol_score = 100.0
            elif vol_annual > 0.30: vol_score = 0.0
            value_score = 50.0
            if rsi_val < 30: value_score = 100.0
            elif rsi_val > 70: value_score = 0.0

            factors_input = {
                "trend": trend_score,
                "volatility": vol_score,
                "value": value_score
            }

            scoring_result = run_historical_scoring(
                symbol_data={
                    "symbol": symbol,
                    "factors": factors_input,
                    "liquidity_tier": "top"
                },
                regime=regime_mapped,
                scoring_engine=self.scoring_engine,
                conviction_transform=self.conviction_transform,
                universe_median=None
            )
            conviction = scoring_result['conviction']

            # --- Trade Logic ---

            # Check for Exit if in position
            if position:
                should_exit = False
                exit_reason = ""

                # PnL Check
                pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

                if pnl_pct < -config.stop_loss_pct:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif pnl_pct > config.take_profit_pct:
                    should_exit = True
                    exit_reason = "take_profit"
                elif conviction < 0.5: # Conviction lost
                    should_exit = True
                    exit_reason = "conviction_lost"
                elif (datetime.strptime(current_date, "%Y-%m-%d") - datetime.strptime(position["entry_date"], "%Y-%m-%d")).days > config.max_holding_days:
                    should_exit = True
                    exit_reason = "time_exit"
                elif i == len(dates) - 1: # End of data
                    should_exit = True
                    exit_reason = "forced_exit"

                if should_exit:
                    # Execute Exit
                    fill_price = self._simulate_fill(current_price, "sell", cost_model, rng)
                    commission = cost_model.commission_per_contract * position["quantity"] # Simple per share/contract model

                    gross_proceeds = fill_price * position["quantity"]
                    net_proceeds = gross_proceeds - commission

                    cash += net_proceeds

                    trade_record = {
                        "trade_id": position["trade_id"],
                        "symbol": symbol,
                        "direction": "long", # Only supporting long for now as per HistoricalCycleService logic
                        "entry_date": position["entry_date"],
                        "entry_price": position["entry_price"],
                        "exit_date": current_date,
                        "exit_price": fill_price,
                        "quantity": position["quantity"],
                        "pnl": net_proceeds - position["cost_basis"],
                        "pnl_pct": (fill_price - position["entry_price"]) / position["entry_price"],
                        "exit_reason": exit_reason,
                        "status": "closed",
                        "commission_paid": position["commission"] + commission,
                        "slippage_paid": (position["ideal_entry"] - position["entry_price"]) * position["quantity"] + (fill_price - current_price) * position["quantity"] # Approx
                    }
                    trades.append(trade_record)

                    events.append({
                        "trade_id": position["trade_id"],
                        "event_type": "EXIT_FILLED",
                        "date": current_date,
                        "price": fill_price,
                        "quantity": position["quantity"],
                        "details": {"reason": exit_reason, "commission": commission}
                    })

                    position = None

            # Check for Entry if not in position
            if not position:
                regime_ok = True
                if config.regime_whitelist and regime_mapped not in config.regime_whitelist:
                    regime_ok = False

                if regime_ok and conviction >= config.conviction_floor:
                    # Execute Entry
                    trade_id = str(uuid.uuid4())

                    # Sizing
                    risk_amt = cash * config.max_risk_pct_portfolio
                    # Simplified: buying power = cash. Use max_risk_pct_portfolio as position size for now
                    # Or adhere strictly:
                    # If max_risk_pct_per_trade is risk (stop loss dist), calculate qty.
                    # Here assuming simplified position sizing:
                    position_value = cash * config.max_risk_pct_portfolio
                    quantity = position_value / current_price
                    if quantity < 1: quantity = 0 # Can't buy partial

                    if quantity > 0:
                        ideal_price = current_price
                        fill_price = self._simulate_fill(current_price, "buy", cost_model, rng)
                        commission = cost_model.commission_per_contract * quantity
                        cost_basis = (fill_price * quantity) + commission

                        if cash >= cost_basis:
                            cash -= cost_basis
                            position = {
                                "trade_id": trade_id,
                                "entry_date": current_date,
                                "entry_price": fill_price,
                                "ideal_entry": ideal_price,
                                "quantity": quantity,
                                "cost_basis": cost_basis,
                                "commission": commission
                            }

                            events.append({
                                "trade_id": trade_id,
                                "event_type": "ENTRY_FILLED",
                                "date": current_date,
                                "price": fill_price,
                                "quantity": quantity,
                                "details": {"conviction": conviction, "regime": regime_mapped, "commission": commission}
                            })

            # Track Equity
            current_equity = cash
            if position:
                current_value = position["quantity"] * current_price
                current_equity += current_value

            equity_curve.append({
                "date": current_date,
                "equity": current_equity,
                "cash": cash
            })

        # Calculate Metrics
        metrics = self._calculate_metrics(trades, equity_curve, initial_equity)

        return BacktestRunResult(
            backtest_id=backtest_id,
            trades=trades,
            events=events,
            equity_curve=equity_curve,
            metrics=metrics
        )

    def _simulate_fill(self, price: float, side: str, cost_model: CostModelConfig, rng: random.Random) -> float:
        """
        Simulates execution price with slippage using shared TransactionCostModel.
        """
        # Construct Mock Order
        order = {
             "order_type": "market",
             "side": side,
             "requested_qty": 100, # Arbitrary qty for simulation
             "quantity": 100
        }

        # Construct Mock Quote
        # Assuming price is close/market.
        quote = {
             "bid_price": price,
             "ask_price": price,
             "status": "ok"
        }

        # Generate int seed from rng
        seed_val = rng.randint(0, 1000000)

        res = TransactionCostModel.simulate_fill(order, quote, cost_model, seed=seed_val)
        return res["avg_fill_price"]

    def _calculate_metrics(self, trades: List[Dict], equity_curve: List[Dict], initial_equity: float) -> Dict[str, Any]:
        if not trades:
            return {
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "turnover": 0.0,
                "slippage_paid": 0.0,
                "fill_rate": 1.0, # Mock
                "trades_count": 0
            }

        total_pnl = sum(t["pnl"] for t in trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(wins) / len(trades) if trades else 0.0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Max Drawdown from equity curve
        peaks = [initial_equity]
        drawdowns = []
        max_eq = initial_equity
        for point in equity_curve:
            eq = point["equity"]
            max_eq = max(max_eq, eq)
            dd = (max_eq - eq) / max_eq if max_eq > 0 else 0
            drawdowns.append(dd)

        max_drawdown = max(drawdowns) if drawdowns else 0.0

        # Sharpe (simplified, daily returns)
        # Need daily returns
        if len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                prev = equity_curve[i-1]["equity"]
                curr = equity_curve[i]["equity"]
                ret = (curr - prev) / prev if prev > 0 else 0
                returns.append(ret)

            mean_ret = np.mean(returns) if returns else 0
            std_ret = np.std(returns) if returns else 1
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        slippage_paid = sum(t.get("slippage_paid", 0) for t in trades)

        return {
            "sharpe": float(sharpe),
            "max_drawdown": float(max_drawdown),
            "profit_factor": float(profit_factor),
            "win_rate": float(win_rate),
            "total_pnl": float(total_pnl),
            "turnover": 0.0, # Placeholder
            "slippage_paid": float(slippage_paid),
            "fill_rate": 1.0, # Placeholder
            "trades_count": len(trades)
        }
