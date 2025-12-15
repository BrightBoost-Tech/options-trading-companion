from typing import List, Dict

def compute_drawdown(equity_curve: List[float]) -> Dict[str, float]:
    """
    Computes the maximum drawdown from an equity curve.

    Args:
        equity_curve: A list of float values representing account equity over time.

    Returns:
        A dictionary containing:
        - 'peak': The peak equity value before the max drawdown.
        - 'trough': The lowest equity value during the max drawdown.
        - 'max_drawdown_pct': The maximum percentage drop from a peak (as a positive float, e.g., 0.10 for 10%).
    """
    if not equity_curve:
        return {
            "peak": 0.0,
            "trough": 0.0,
            "max_drawdown_pct": 0.0
        }

    running_peak = equity_curve[0]
    max_dd_pct = 0.0
    peak_at_max_dd = equity_curve[0]
    trough_at_max_dd = equity_curve[0]

    # We need to find the global maximum drawdown.
    # While iterating, we track the running peak.

    current_peak = equity_curve[0]

    for value in equity_curve:
        if value > current_peak:
            current_peak = value

        dd = (current_peak - value) / current_peak if current_peak > 0 else 0.0

        if dd > max_dd_pct:
            max_dd_pct = dd
            peak_at_max_dd = current_peak
            trough_at_max_dd = value

    return {
        "peak": peak_at_max_dd,
        "trough": trough_at_max_dd,
        "max_drawdown_pct": max_dd_pct
    }

def compute_consecutive_losses(pnl_series: List[float]) -> int:
    """
    Computes the number of consecutive losses at the end of the PnL series.

    Args:
        pnl_series: A list of PnL values (ordered chronologically).

    Returns:
        The count of consecutive losses (negative PnL) at the tail of the list.
    """
    count = 0
    # Iterate backwards
    for pnl in reversed(pnl_series):
        if pnl < 0:
            count += 1
        else:
            break
    return count

def compute_risk_multiplier(drawdown_pct: float, consecutive_losses: int, regime: str = "normal") -> float:
    """
    Calculates a risk multiplier based on drawdown, loss streaks, and market regime.

    Policy:
       base=1.0
       if regime=="panic": *=0.4
       elif regime=="high_vol": *=0.7
       if consecutive_losses>=3: *=0.6
       if drawdown_pct>=0.10: *=0.7
       if drawdown_pct>=0.20: *=0.4
       clamp [0.1, 1.2]

    Args:
        drawdown_pct: Current drawdown percentage as a float (e.g., 0.15 for 15%).
        consecutive_losses: Number of consecutive losing trades.
        regime: Market regime string (e.g., "panic", "high_vol", "normal").

    Returns:
        A float multiplier for position sizing.
    """
    multiplier = 1.0

    # Regime adjustments
    # Note: Using case-insensitive comparison for robustness, though not strictly specified.
    regime_lower = regime.lower()
    if regime_lower == "panic":
        multiplier *= 0.4
    elif regime_lower == "high_vol":
        multiplier *= 0.7

    # Loss streak penalty
    if consecutive_losses >= 3:
        multiplier *= 0.6

    # Drawdown penalties
    # Note: The prompt implies these stack if both are true (since >= 0.20 implies >= 0.10).
    # "if drawdown_pct>=0.10: *=0.7"
    # "if drawdown_pct>=0.20: *=0.4"
    # If drawdown is 0.25, both conditions are true.
    # 1.0 * 0.7 * 0.4 = 0.28.

    if drawdown_pct >= 0.10:
        multiplier *= 0.7

    if drawdown_pct >= 0.20:
        multiplier *= 0.4

    # Clamp [0.1, 1.2]
    if multiplier < 0.1:
        multiplier = 0.1
    elif multiplier > 1.2:
        multiplier = 1.2

    return multiplier
