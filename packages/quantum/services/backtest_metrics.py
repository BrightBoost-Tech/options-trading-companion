from typing import Dict, List, Any
import numpy as np

def calculate_backtest_metrics(trades: List[Dict[str, Any]], equity_curve: List[Dict[str, Any]], initial_equity: float) -> Dict[str, Any]:
    """
    Computes standard backtest metrics from trade list and equity curve.
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
            "fill_rate": 0.0,
            "avg_trade_ev": 0.0,
            "ev_calibration_error": 0.0
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

    # 2. Equity-based Metrics (Sharpe, DD)
    # Reconstruct daily returns
    if len(equity_curve) > 1:
        returns = []
        peaks = [initial_equity]
        drawdowns = []
        max_eq = initial_equity

        for i, point in enumerate(equity_curve):
            eq = point["equity"]

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
    else:
        sharpe = 0.0
        max_drawdown = 0.0

    # 3. EV Metrics (Placeholder logic)
    # If trades had 'predicted_prob' and 'predicted_ev', we could compute Brier score.
    # Currently assuming null.
    ev_calibration_error = 0.0 # Placeholder
    avg_trade_ev = 0.0 # Placeholder

    return {
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "profit_factor": float(profit_factor),
        "win_rate": float(win_rate),
        "total_pnl": float(total_pnl),
        "turnover": 0.0, # Placeholder
        "slippage_paid": float(slippage_paid),
        "fill_rate": 1.0, # Placeholder
        "avg_trade_ev": float(avg_trade_ev),
        "ev_calibration_error": float(ev_calibration_error)
    }
