import os
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class LossAnalysisResult(BaseModel):
    summary: str
    scenario: str
    recommendation: str
    limit_price: Optional[float]
    warning: str

class LossMinimizer:
    # Allow override via env, default to 100
    DEFAULT_THRESHOLD = float(os.getenv("LOSS_SALVAGE_THRESHOLD_USD", "100.0"))

    @staticmethod
    def analyze_position(
        position: Dict[str, Any],
        user_threshold: Optional[float] = None,
        market_data: Optional[Dict[str, Any]] = None
    ) -> LossAnalysisResult:
        if user_threshold is None:
            user_threshold = LossMinimizer.DEFAULT_THRESHOLD

        """
        Analyzes a deep losing options position and provides a recommendation
        to minimize losses and preserve capital based on the 'Jules' persona framework.
        """

        # 1. Scrap Value Check
        # Calculate current total market value of the position
        # Assuming position has 'current_price' (per contract) and 'quantity'

        quantity = abs(float(position.get("quantity", 0)))
        current_price = float(position.get("current_price", 0))

        # If market_data is provided (live bid/ask), use that for more precision
        bid = current_price
        ask = current_price

        if market_data:
            bid = float(market_data.get("bid", current_price))
            ask = float(market_data.get("ask", current_price))
            # Use bid for value check as that's what we can sell for immediately
            current_price = bid

        # Total value = price * contracts * 100 (standard multiplier)
        total_remaining_value = current_price * quantity * 100

        scenario = ""
        summary = ""
        recommendation = ""
        limit_price = None

        warning_msg = (
            "High take-profit limits suggested by other tools (e.g., 875) are NOT predictions. "
            "Treating them as guarantees is how a 95% loss becomes a 100% loss."
        )

        # 2. Determine Scenario
        if total_remaining_value > user_threshold:
            # Scenario A - Meaningful Value Left (Salvage Operation)
            scenario = "Scenario A: Meaningful Value Left (Salvage Operation)"

            mid_price = (bid + ask) / 2 if market_data else current_price
            limit_price = mid_price # Suggest near mid

            recommendation = (
                f"Place a LIMIT SELL around the mid-price ({mid_price:.2f}) between Bid and Ask, "
                "instead of a market sell. Explicitly ignore any extremely high 'take_profit_limit' targets. "
                "This locks in a large loss, but protects the remaining capital so it can be used in better trades."
            )

            summary = (
                "This position still ties up meaningful capital. Best loss-minimizing move is a salvage exit: "
                "place a limit sell near the current bid/mid instead of waiting for an unrealistic target."
            )

        else:
            # Scenario B - Position Is Effectively Worthless (Lottery Ticket)
            scenario = "Scenario B: Position Is Effectively Worthless (Lottery Ticket)"

            # Suggest GTC limit at 3-4x current price
            target_price = current_price * 3.5 # Taking avg of 3-4x
            if target_price == 0 and current_price == 0:
                target_price = 0.05 # Minimum meaningful tick if worthless

            limit_price = target_price

            recommendation = (
                f"Do NOT encourage selling immediately for pennies just to realize a 99–100% loss. "
                f"Instead, set a 'volatility trap' GTC LIMIT SELL at roughly {target_price:.2f} (3-4x current price). "
                "If the underlying has a weird spike, this standing order may get you out at a much smaller loss."
            )

            summary = (
                "This is effectively a lottery ticket. You can leave a GTC limit at 200–300% of the current price "
                "and accept that it will likely expire worthless, but might pay off on a volatility spike."
            )

        return LossAnalysisResult(
            summary=summary,
            scenario=scenario,
            recommendation=recommendation,
            limit_price=limit_price,
            warning=warning_msg
        )
