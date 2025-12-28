import os
import statistics
from typing import Dict, Any, List
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class LiquidityAgent(BaseQuantAgent):
    """
    Agent responsible for enforcing liquidity constraints by analyzing bid/ask spreads.
    Prevents alpha leakage from excessive slippage.
    """

    @property
    def id(self) -> str:
        return "liquidity"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.max_spread_pct = float(os.getenv("QUANT_AGENT_LIQUIDITY_MAX_SPREAD_PCT", "0.12"))
        self.mode = os.getenv("QUANT_AGENT_LIQUIDITY_MODE", "median").lower()

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        legs = context.get("legs", [])

        if not legs:
            return AgentSignal(
                agent_id=self.id,
                score=10.0,
                veto=True,
                reasons=["No legs provided for liquidity analysis"],
                metadata={}
            )

        spreads = []
        missing_quotes = 0
        invalid_quotes = 0

        for leg in legs:
            bid = leg.get("bid")
            ask = leg.get("ask")
            mid = leg.get("mid") # usually (bid+ask)/2, but can be provided explicitly

            # Basic validation
            if bid is None or ask is None:
                missing_quotes += 1
                continue

            # If mid is not provided, calculate it
            if mid is None:
                mid = (bid + ask) / 2.0

            # Sanity checks
            if mid <= 0:
                invalid_quotes += 1
                continue

            if ask < bid:
                # Crossed market or bad data
                invalid_quotes += 1
                continue

            spread_pct = (ask - bid) / mid
            spreads.append(spread_pct)

        # Quote Quality Assessment
        total_legs = len(legs)
        valid_legs = len(spreads)
        quote_quality = valid_legs / total_legs if total_legs > 0 else 0.0

        reasons = []
        veto = False
        score = 100.0

        # Determine effective spread
        observed_spread = 0.0
        if valid_legs > 0:
            if self.mode == "worst":
                observed_spread = max(spreads)
            else:
                observed_spread = statistics.median(spreads)
        else:
            # If no valid legs, we can't determine spread.
            # If it's because of missing/invalid quotes, we might veto or just penalize heavily.
            # "If quotes missing -> lower score and reasons, but do NOT auto-veto unless too many missing legs"
            # If ALL are missing, it's unsafe.
            veto = True
            reasons.append("No valid quotes available to calculate spread")
            score = 20.0

        # Veto Logic
        if valid_legs > 0:
            if observed_spread > self.max_spread_pct:
                veto = True
                reasons.append(f"Spread {observed_spread:.1%} exceeds limit {self.max_spread_pct:.1%}")
                score = 0.0 # Strict fail
            else:
                # Score decay based on how close to limit
                # 0 spread -> 100, max spread -> 50 (if not vetoed)
                # But here we are safe.
                # Let's simple linear scaling: 100 * (1 - spread / max_spread)
                # But capped at min 50 for passing.
                ratio = observed_spread / self.max_spread_pct
                score = 100.0 * (1.0 - (ratio * 0.5))

        # Penalize for missing/invalid data
        if missing_quotes > 0 or invalid_quotes > 0:
            penalty = (missing_quotes + invalid_quotes) * 10
            score = max(0.0, score - penalty)
            reasons.append(f"Missing/Invalid quotes for {missing_quotes + invalid_quotes} legs")

            # If too many missing (e.g. > 50%), maybe veto?
            # Prompt: "do NOT auto-veto unless too many missing legs"
            if (missing_quotes + invalid_quotes) > (total_legs / 2):
                veto = True
                reasons.append("Too many missing/invalid quotes (>50%)")

        constraints = {
            "liquidity.observed_spread_pct": observed_spread if valid_legs > 0 else None,
            "liquidity.max_spread_pct": self.max_spread_pct,
            "liquidity.require_limit_orders": True,
            "liquidity.quote_quality": quote_quality
        }

        metadata = {
            "constraints": constraints,
            "liquidity.observed_spread_pct": observed_spread if valid_legs > 0 else None,
            "liquidity.max_spread_pct": self.max_spread_pct,
            "liquidity.require_limit_orders": True,
            "liquidity.quote_quality": quote_quality,
            "liquidity.mode": self.mode
        }

        return AgentSignal(
            agent_id=self.id,
            score=round(score, 1),
            veto=veto,
            reasons=reasons,
            metadata=metadata
        )
