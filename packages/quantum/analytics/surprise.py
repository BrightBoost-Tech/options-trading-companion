def compute_surprise(sigma_pred: float, sigma_realized: float, pnl_realized: float, w1: float = 1.0, w2: float = 1.0) -> float:
    """
    Computes the surprise score based on volatility mismatch and negative P&L.

    Surprise = w1 * abs(sigma_pred - sigma_realized) + w2 * ReLU(-PnL)
    """
    vol_surprise = abs(sigma_pred - sigma_realized)

    # ReLU(-PnL): If PnL is negative (loss), the term is positive. If PnL is positive (profit), term is 0.
    loss_surprise = max(0.0, -pnl_realized)

    return w1 * vol_surprise + w2 * loss_surprise
