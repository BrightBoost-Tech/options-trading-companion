import uuid
import random
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig, BacktestRequestV3
from packages.quantum.market_data import PolygonService, extract_underlying_symbol

# v5 dual-import shim for unified metrics
try:
    from packages.quantum.services.backtest_metrics import calculate_backtest_metrics
except ImportError:
    from services.backtest_metrics import calculate_backtest_metrics
from packages.quantum.analytics.regime_scoring import ScoringEngine, ConvictionTransform
from packages.quantum.services.options_utils import get_contract_multiplier
from packages.quantum.analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
    run_historical_scoring,
    calculate_regime_vectorized
)
from packages.quantum.analytics.factors import (
    calculate_trend,
    calculate_volatility,
    calculate_rsi,
    calculate_indicators_vectorized
)
from packages.quantum.nested.backbone import infer_global_context, GlobalContext
from packages.quantum.execution.transaction_cost_model import TransactionCostModel as V3TCM
from packages.quantum.services.transaction_cost_model import TransactionCostModel as LegacyTCM

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
        initial_equity: float,
        rolling_options: Dict[str, Any] = None,
        option_resolver=None
    ) -> BacktestRunResult:
        """
        Runs a single backtest pass stepping through daily bars.

        PR7: If rolling_options is provided, uses rolling contract mode where:
        - Symbol is treated as the underlying
        - Each trade entry resolves a fresh option contract as-of entry date
        - Option OHLC is fetched per-contract for trade execution

        Args:
            symbol: Stock ticker or option symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            config: Strategy configuration
            cost_model: Transaction cost configuration
            seed: Random seed
            initial_equity: Starting capital
            rolling_options: Optional dict with {right, target_dte, moneyness} for rolling mode
            option_resolver: OptionContractResolver instance (required for rolling mode)
        """
        rng = random.Random(seed)
        backtest_id = str(uuid.uuid4())

        # Initialize TCM
        tcm = LegacyTCM(cost_model)

        # PR7: Rolling options mode detection
        rolling_mode = rolling_options is not None and option_resolver is not None
        if rolling_mode:
            # In rolling mode, symbol is the underlying, multiplier is always 100
            underlying_for_rolling = symbol
            multiplier = 100.0
        else:
            underlying_for_rolling = None
            # Determine contract multiplier (100 for options, 1 for stocks)
            multiplier = get_contract_multiplier(symbol)

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

        # PR5: For options, fetch underlying prices for scoring
        # Option prices are dominated by theta decay, so scoring should use underlying trend
        underlying_symbol = None
        underlying_dates = []
        underlying_prices = []
        underlying_date_map = {}

        if multiplier == 100:  # Option contract
            underlying_symbol = extract_underlying_symbol(symbol)
            underlying_hist = self.polygon.get_historical_prices(
                underlying_symbol,
                days=days_needed,
                to_date=end_dt
            )
            if underlying_hist:
                underlying_dates = underlying_hist.get('dates', [])
                underlying_prices = underlying_hist.get('prices', [])
                underlying_date_map = {d: i for i, d in enumerate(underlying_dates)}

        # Determine start index
        start_idx = -1
        for i, d in enumerate(dates):
            if datetime.strptime(d, "%Y-%m-%d") >= start_dt:
                start_idx = i
                break

        if start_idx == -1 or start_idx < self.lookback_window:
             if len(dates) > self.lookback_window and start_idx != -1:
                 pass
             elif len(dates) > self.lookback_window:
                 start_idx = self.lookback_window
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
        position = None
        trades = []
        events = []
        equity_curve = []

        # 3. Pre-calculate Indicators & Scoring (Vectorized Optimization)

        # A. Calculate for default 'prices' (used for stocks or fallback)
        indicators_vec = calculate_indicators_vectorized(prices)
        regime_vec = calculate_regime_vectorized(
            indicators_vec["trend"],
            indicators_vec["volatility"],
            indicators_vec["rsi"]
        )
        vec_regime_arr = regime_vec["regime"]
        vec_conviction_arr = regime_vec["conviction"]

        # B. Calculate for 'underlying_prices' (preferred for options)
        und_regime_arr = None
        und_conviction_arr = None

        if underlying_prices and len(underlying_prices) > 0:
            und_indicators = calculate_indicators_vectorized(underlying_prices)
            und_regime = calculate_regime_vectorized(
                und_indicators["trend"],
                und_indicators["volatility"],
                und_indicators["rsi"]
            )
            und_regime_arr = und_regime["regime"]
            und_conviction_arr = und_regime["conviction"]

        # 3. Loop
        for i in range(start_idx, len(dates)):
            current_date = dates[i]
            current_price = prices[i]

            # Logic: Prefer underlying if available and aligned, else fallback to prices
            regime_mapped = "normal"
            conviction = 0.5
            used_underlying = False

            if und_regime_arr is not None and current_date in underlying_date_map:
                u_idx = underlying_date_map[current_date]
                if u_idx < len(und_regime_arr):
                    regime_mapped = und_regime_arr[u_idx]
                    conviction = float(und_conviction_arr[u_idx])
                    used_underlying = True

            if not used_underlying:
                # Fallback to default prices
                if i < len(vec_regime_arr):
                    regime_mapped = vec_regime_arr[i]
                    conviction = float(vec_conviction_arr[i])

            # --- Trade Logic ---

            # Check for Exit if in position
            if position:
                should_exit = False
                exit_reason = ""

                # PR7: In rolling mode, use contract's OHLC for position valuation
                position_current_price = current_price
                if rolling_mode and position.get("contract_ohlc") and position.get("contract_date_map"):
                    if current_date in position["contract_date_map"]:
                        position_current_price = position["contract_ohlc"][position["contract_date_map"][current_date]]
                    else:
                        # Contract has no data for this date (may have expired)
                        # Force exit if contract data unavailable
                        should_exit = True
                        exit_reason = "contract_expired"
                        # Use last known price
                        if position["contract_ohlc"]:
                            position_current_price = position["contract_ohlc"][-1]

                # PnL Check
                pnl_pct = (position_current_price - position["entry_price"]) / position["entry_price"]

                if not should_exit:  # Skip if already flagged for exit
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
                    fill = tcm.simulate_fill(position_current_price, position["quantity"], "sell", rng, multiplier)

                    # Proceeds include multiplier (100 shares per option contract)
                    gross_proceeds = fill.fill_price * fill.filled_quantity * multiplier
                    net_proceeds = gross_proceeds - fill.commission_paid

                    cash += net_proceeds

                    # PR7: Use contract symbol in trade record for rolling mode
                    trade_symbol = position.get("contract_symbol") or symbol

                    trade_record = {
                        "trade_id": position["trade_id"],
                        "symbol": trade_symbol,
                        "direction": "long",
                        "entry_date": position["entry_date"],
                        "entry_price": position["entry_price"],
                        "exit_date": current_date,
                        "exit_price": fill.fill_price,
                        "quantity": position["quantity"],
                        "multiplier": multiplier,
                        "pnl": net_proceeds - position["cost_basis"],
                        "pnl_pct": (fill.fill_price - position["entry_price"]) / position["entry_price"],
                        "exit_reason": exit_reason,
                        "status": "closed",
                        "commission_paid": position["commission"] + fill.commission_paid,
                        "slippage_paid": position["slippage"] + fill.slippage_paid
                    }
                    trades.append(trade_record)

                    events.append({
                        "trade_id": position["trade_id"],
                        "event_type": "EXIT_FILLED",
                        "date": current_date,
                        "price": fill.fill_price,
                        "quantity": position["quantity"],
                        "details": {
                            "reason": exit_reason,
                            "commission": fill.commission_paid,
                            "contract_symbol": trade_symbol if rolling_mode else None,
                            # v4: Fill tracking for metrics
                            "requested_qty": position["quantity"],
                            "filled_qty": fill.filled_quantity,
                            "multiplier": position.get("multiplier", 1.0)
                        }
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

                    # PR7: Rolling mode - resolve contract as-of entry date
                    entry_price = current_price
                    entry_symbol = symbol
                    contract_ohlc = None
                    contract_date_map = None

                    if rolling_mode:
                        # Resolve contract for this entry date
                        entry_date_obj = datetime.strptime(current_date, "%Y-%m-%d").date()
                        resolved_contract = option_resolver.resolve_contract_asof(
                            underlying=underlying_for_rolling,
                            right=rolling_options.get("right", "call"),
                            target_dte=rolling_options.get("target_dte", 30),
                            moneyness=rolling_options.get("moneyness", "atm"),
                            as_of_date=entry_date_obj
                        )

                        if resolved_contract:
                            entry_symbol = resolved_contract
                            # Fetch contract's OHLC for the trade window
                            # Use end_dt as max, but contract may expire earlier
                            contract_hist = self.polygon.get_option_historical_prices(
                                resolved_contract,
                                start_date=entry_date_obj,
                                end_date=end_dt.date() if hasattr(end_dt, 'date') else end_dt
                            )
                            if contract_hist and contract_hist.get("prices"):
                                contract_ohlc = contract_hist["prices"]
                                contract_dates = contract_hist.get("dates", [])
                                contract_date_map = {d: idx for idx, d in enumerate(contract_dates)}
                                # Use contract's entry-date price
                                if current_date in contract_date_map:
                                    entry_price = contract_ohlc[contract_date_map[current_date]]
                                elif contract_ohlc:
                                    entry_price = contract_ohlc[0]  # Use first available
                        else:
                            # No contract found - skip entry in rolling mode
                            continue

                    # Sizing (contract-aware: options use multiplier=100)
                    position_value = cash * config.max_risk_pct_portfolio
                    notional_per_unit = entry_price * multiplier
                    quantity = int(position_value / notional_per_unit) if notional_per_unit > 0 else 0

                    if quantity > 0:
                        ideal_price = entry_price
                        fill = tcm.simulate_fill(entry_price, quantity, "buy", rng, multiplier)
                        # Cost basis includes multiplier (100 shares per option contract)
                        cost_basis = (fill.fill_price * fill.filled_quantity * multiplier) + fill.commission_paid

                        if cash >= cost_basis:
                            cash -= cost_basis
                            position = {
                                "trade_id": trade_id,
                                "entry_date": current_date,
                                "entry_price": fill.fill_price,
                                "ideal_entry": ideal_price,
                                "quantity": fill.filled_quantity,
                                "cost_basis": cost_basis,
                                "commission": fill.commission_paid,
                                "slippage": fill.slippage_paid,
                                "multiplier": multiplier,
                                # PR7: Track contract info for rolling mode
                                "contract_symbol": entry_symbol if rolling_mode else None,
                                "contract_ohlc": contract_ohlc,
                                "contract_date_map": contract_date_map
                            }

                            events.append({
                                "trade_id": trade_id,
                                "event_type": "ENTRY_FILLED",
                                "date": current_date,
                                "price": fill.fill_price,
                                "quantity": fill.filled_quantity,
                                "details": {
                                    "conviction": conviction,
                                    "regime": regime_mapped,
                                    "commission": fill.commission_paid,
                                    "contract_symbol": entry_symbol if rolling_mode else None,
                                    # v4: Fill tracking for metrics
                                    "requested_qty": quantity,
                                    "filled_qty": fill.filled_quantity,
                                    "multiplier": multiplier
                                }
                            })

            # Track Equity (includes multiplier for options)
            current_equity = cash
            if position:
                # PR7: In rolling mode, use contract price for position valuation
                valuation_price = current_price
                if rolling_mode and position.get("contract_ohlc") and position.get("contract_date_map"):
                    if current_date in position["contract_date_map"]:
                        valuation_price = position["contract_ohlc"][position["contract_date_map"][current_date]]
                    elif position["contract_ohlc"]:
                        valuation_price = position["contract_ohlc"][-1]  # Last known price

                current_value = position["quantity"] * valuation_price * multiplier
                current_equity += current_value

            equity_curve.append({
                "date": current_date,
                "equity": current_equity,
                "cash": cash
            })

        # Calculate Metrics (v5: pass events for unified v4 metrics)
        metrics = self._calculate_metrics(trades, equity_curve, initial_equity, events=events)

        # PR5: Add debug metrics for options to track scoring vs trading symbols
        if multiplier == 100 and underlying_symbol:
            metrics["scoring_symbol"] = underlying_symbol
            metrics["traded_symbol"] = symbol
            metrics["underlying_bars"] = len(underlying_prices)
            metrics["option_bars"] = len(prices)

        # PR7: Add rolling mode metrics
        if rolling_mode:
            metrics["rolling_mode"] = True
            metrics["underlying"] = underlying_for_rolling
            # Count unique contracts traded
            unique_contracts = set(t.get("symbol") for t in trades if t.get("symbol"))
            metrics["unique_contracts_traded"] = len(unique_contracts)

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

        res = V3TCM.simulate_fill(order, quote, cost_model, seed=seed_val)
        return res["avg_fill_price"]

    def _calculate_metrics(
        self,
        trades: List[Dict],
        equity_curve: List[Dict],
        initial_equity: float,
        events: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Calculate backtest metrics using unified v4 metrics calculator.

        v5: Delegates to calculate_backtest_metrics for consistent turnover,
        fill_rate, and cost_drag_bps calculations across single-run and
        walk-forward modes.

        Args:
            trades: List of trade records
            equity_curve: List of equity snapshots
            initial_equity: Starting capital
            events: Optional list of trade events for fill_rate calculation

        Returns:
            Dict with all v4 metrics
        """
        return calculate_backtest_metrics(
            trades,
            equity_curve,
            initial_equity,
            events=events
        )
