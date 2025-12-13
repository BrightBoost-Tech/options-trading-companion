from typing import Dict, Any, Optional

class PnlAttribution:
    """
    Computes attribution metrics for closed trades.
    Separates Alpha (signal quality) from Execution (friction/costs).
    """

    @staticmethod
    def compute(
        entry_mid: float,
        entry_fill: float,
        exit_mid: float,
        exit_fill: float,
        quantity: float,
        multiplier: float = 100.0,
        fees_total: float = 0.0,
        direction: str = "long" # long (buy->sell) or short (sell->buy)
    ) -> Dict[str, float]:
        """
        Returns dictionary with:
        - pnl_total: Realized PnL
        - pnl_alpha: PnL if filled at mid prices (Theoretical PnL)
        - pnl_execution_drag: Cost of spread + slippage + fees
        """

        qty = abs(quantity)

        # 1. Total Realized PnL
        # Long: (Exit Fill - Entry Fill) * Qty * Mult - Fees
        # Short: (Entry Fill - Exit Fill) * Qty * Mult - Fees
        if direction == "long":
            gross_pnl = (exit_fill - entry_fill) * qty * multiplier
        else:
            gross_pnl = (entry_fill - exit_fill) * qty * multiplier

        total_pnl = gross_pnl - fees_total

        # 2. Alpha PnL (Theoretical / Paper with 0 spread)
        # Long: (Exit Mid - Entry Mid)
        # Short: (Entry Mid - Exit Mid)
        if direction == "long":
            alpha_pnl = (exit_mid - entry_mid) * qty * multiplier
        else:
            alpha_pnl = (entry_mid - exit_mid) * qty * multiplier

        # 3. Execution Drag
        # Difference between Total and Alpha
        # Should be negative usually (cost).
        # Drag = Total - Alpha
        # Example Long:
        # Total = (ExitFill - EntryFill) - Fees
        # Alpha = (ExitMid - EntryMid)
        # Drag = (ExitFill - ExitMid) - (EntryFill - EntryMid) - Fees
        # If ExitFill < ExitMid (sold lower), first term neg.
        # If EntryFill > EntryMid (bought higher), second term pos -> neg total.

        execution_drag = total_pnl - alpha_pnl

        return {
            "pnl_total": round(total_pnl, 2),
            "pnl_alpha": round(alpha_pnl, 2),
            "pnl_execution_drag": round(execution_drag, 2),
            "fees_total": round(fees_total, 2)
        }
