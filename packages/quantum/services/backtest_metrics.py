from typing import Dict, List, Any, Optional
import numpy as np


def calculate_backtest_metrics(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    initial_equity: float,
    events: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Computes standard backtest metrics from trade list and equity curve.

    v4 upgrade: Real turnover, fill_rate, cost_drag_bps calculations.

    Args:
        trades: List of closed trade dicts
        equity_curve: List of {date, equity} points
        initial_equity: Starting capital
        events: Optional list of events (for fill_rate calculation)

    Returns:
        Dict with sharpe, max_drawdown, profit_factor, win_rate, total_pnl,
        turnover, slippage_paid, fill_rate, cost_drag_bps, etc.
    """
    if not trades:
        return {
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "turnover": 0.0,
            "slippage_paid": 0.0,
            "commission_paid": 0.0,
            "cost_drag_bps": 0.0,
            "fill_rate": 1.0,
            "avg_trade_ev": 0.0,
            "ev_calibration_error": 0.0,
            "trades_count": 0
        }

    # 1. Trade-based Metrics
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]

    win_rate = len(wins) / len(trades)

    gross_profit = sum(t.get("pnl", 0) for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    avg_pnl = total_pnl / len(trades)

    slippage_paid = sum(t.get("slippage_paid", 0) for t in trades)
    commission_paid = sum(t.get("commission_paid", 0) for t in trades)

    # v4: Calculate traded notional for turnover
    # Entry + Exit notional per trade
    trade_notional_sum = 0.0
    for t in trades:
        multiplier = t.get("multiplier", 1.0)
        quantity = t.get("quantity", 0)
        entry_price = t.get("entry_price", 0)
        exit_price = t.get("exit_price", 0)
        # Notional = price * quantity * multiplier (for both legs)
        entry_notional = abs(entry_price * quantity * multiplier)
        exit_notional = abs(exit_price * quantity * multiplier)
        trade_notional_sum += entry_notional + exit_notional

    # 2. Equity-based Metrics (Sharpe, DD)
    # Reconstruct daily returns
    if len(equity_curve) > 1:
        returns = []
        equities = []
        drawdowns = []
        max_eq = initial_equity

        for i, point in enumerate(equity_curve):
            eq = point["equity"]
            equities.append(eq)

            # DD
            max_eq = max(max_eq, eq)
            dd = (max_eq - eq) / max_eq if max_eq > 0 else 0
            drawdowns.append(dd)

            # Returns
            if i > 0:
                prev = equity_curve[i-1]["equity"]
                ret = (eq - prev) / prev if prev > 0 else 0
                returns.append(ret)

        max_drawdown = max(drawdowns) if drawdowns else 0.0

        mean_ret = np.mean(returns) if returns else 0
        std_ret = np.std(returns) if returns else 1
        sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0

        # v4: Average equity for turnover/cost calculations
        avg_equity = np.mean(equities) if equities else initial_equity
    else:
        sharpe = 0.0
        max_drawdown = 0.0
        avg_equity = initial_equity

    # v4: Turnover = traded notional / avg equity
    turnover = trade_notional_sum / avg_equity if avg_equity > 0 else 0.0

    # v4: Cost drag in basis points
    total_costs = slippage_paid + commission_paid
    cost_drag_bps = (total_costs / avg_equity) * 10000 if avg_equity > 0 else 0.0

    # v4: Fill rate from events (if provided)
    fill_rate = 1.0  # Default fallback
    if events:
        total_requested = 0.0
        total_filled = 0.0
        for e in events:
            if e.get("event_type") in ["ENTRY_FILLED", "EXIT_FILLED"]:
                details = e.get("details", {})
                req_qty = details.get("requested_qty", 0)
                filled_qty = details.get("filled_qty", 0)
                if req_qty > 0:
                    total_requested += req_qty
                    total_filled += filled_qty
        if total_requested > 0:
            fill_rate = total_filled / total_requested

    # 3. EV Metrics (Placeholder logic)
    # If trades had 'predicted_prob' and 'predicted_ev', we could compute Brier score.
    # Currently assuming null.
    ev_calibration_error = 0.0  # Placeholder
    avg_trade_ev = 0.0  # Placeholder

    return {
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "profit_factor": float(profit_factor),
        "win_rate": float(win_rate),
        "total_pnl": float(total_pnl),
        "turnover": float(turnover),
        "slippage_paid": float(slippage_paid),
        "commission_paid": float(commission_paid),
        "cost_drag_bps": float(cost_drag_bps),
        "fill_rate": float(fill_rate),
        "avg_trade_ev": float(avg_trade_ev),
        "ev_calibration_error": float(ev_calibration_error),
        "trades_count": len(trades)
    }
