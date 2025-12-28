import os
import math
from typing import Dict, Any, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class SizingAgent(BaseQuantAgent):
    """
    SizingAgent determines position sizing based on account capital,
    risk milestones, and confluence of other agent signals.
    """

    @property
    def id(self) -> str:
        return "sizing"

    def _get_milestone_limits(self, capital: float) -> tuple[float, float]:
        """
        Returns (min_risk_usd, max_risk_usd) based on capital milestones.
        Configurable via environment variables.
        """
        # Load config or defaults
        # <1k: 10–35
        m1_min = float(os.getenv("SIZING_MILESTONE_1000_MIN", "10"))
        m1_max = float(os.getenv("SIZING_MILESTONE_1000_MAX", "35"))
        # 1k–5k: 20–75
        m2_min = float(os.getenv("SIZING_MILESTONE_5000_MIN", "20"))
        m2_max = float(os.getenv("SIZING_MILESTONE_5000_MAX", "75"))
        # 5k–10k: 35–150
        m3_min = float(os.getenv("SIZING_MILESTONE_10000_MIN", "35"))
        m3_max = float(os.getenv("SIZING_MILESTONE_10000_MAX", "150"))
        # >10k: 50–250
        m4_min = float(os.getenv("SIZING_MILESTONE_BIG_MIN", "50"))
        m4_max = float(os.getenv("SIZING_MILESTONE_BIG_MAX", "250"))

        if capital < 1000:
            return m1_min, m1_max
        elif capital < 5000:
            return m2_min, m2_max
        elif capital < 10000:
            return m3_min, m3_max
        else:
            return m4_min, m4_max

    def _extract_score(self, signals: Dict[str, Any], keys: list[str]) -> Optional[float]:
        """Helper to extract score from signal dict or object for first matching key."""
        for key in keys:
            signal = signals.get(key)
            if not signal:
                continue

            # If it's an AgentSignal object
            if hasattr(signal, "score"):
                return float(signal.score)
            # If it's a dict
            if isinstance(signal, dict):
                return float(signal.get("score", 50.0))
        return None

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Determines sizing constraints.

        Context requires:
        - deployable_capital (float)
        - max_loss_per_contract (float)

        Optional context:
        - base_score (float): The scanner score (0-100). Default 50.
        - agent_signals (Dict[str, AgentSignal] or Dict): Other agent outputs.
        - collateral_required_per_contract (float)
        """
        capital = float(context.get("deployable_capital", 0.0))
        max_loss = float(context.get("max_loss_per_contract", 0.0))
        collateral = float(context.get("collateral_required_per_contract", 0.0)) or max_loss
        base_score = float(context.get("base_score", 50.0))

        # 1. Determine Risk Range
        min_risk, max_risk = self._get_milestone_limits(capital)

        # 2. Confluence Logic
        agent_signals = context.get("agent_signals", {})

        # Parse signals
        # Prioritize keys: 'regime', 'vol', 'liquidity', 'event'/'event_risk'
        regime_score = self._extract_score(agent_signals, ["regime", "regime_agent"])
        vol_score = self._extract_score(agent_signals, ["vol", "volatility", "vol_agent"])
        liquidity_score = self._extract_score(agent_signals, ["liquidity", "liquidity_agent"])
        event_score = self._extract_score(agent_signals, ["event", "event_risk", "event_agent"])

        # Base factor from scanner score
        base_scale_factor = max(0.0, min(1.0, base_score / 100.0))

        # Apply Confluence Modifiers
        confluence_multiplier = 1.0
        reasons = []

        # Scale UP: Regime + Vol alignment
        # Assuming high score in regime/vol means "favorable/safe" or "strong signal"
        if regime_score is not None and vol_score is not None:
            if regime_score > 70 and vol_score > 70:
                confluence_multiplier *= 1.25
                reasons.append("Boost: High Regime & Vol alignment")

        # Scale DOWN: Liquidity risk (low score = bad liquidity)
        if liquidity_score is not None and liquidity_score < 50:
            penalty = (liquidity_score / 50.0) # e.g. score 25 -> 0.5x
            confluence_multiplier *= penalty
            reasons.append(f"Penalty: Poor Liquidity (Score {liquidity_score:.0f})")

        # Scale DOWN: Event risk (low score = high risk/earnings soon)
        if event_score is not None and event_score < 50:
            penalty = (event_score / 50.0)
            confluence_multiplier *= penalty
            reasons.append(f"Penalty: Event Risk (Score {event_score:.0f})")

        # Calculate final scale factor
        final_scale_factor = base_scale_factor * confluence_multiplier
        final_scale_factor = max(0.0, min(1.0, final_scale_factor)) # Clamp to 0-1 range within bucket

        # 3. Calculate Target Risk
        # Map factor to range [min_risk, max_risk]
        target_risk = min_risk + (max_risk - min_risk) * final_scale_factor

        # 4. Safety Checks & Contract Conversion
        safe_risk_cap = capital * 0.95 # Absolute safety buffer
        target_risk = min(target_risk, safe_risk_cap)

        if max_loss <= 0:
            rec_contracts = 1
            reasons.append("Missing per-contract risk, default to 1")
        else:
            rec_contracts = math.floor(target_risk / max_loss)
            reasons.append(f"Sized ${target_risk:.2f} (Factor {final_scale_factor:.2f})")

        # 5. Check Collateral/Buying Power
        if collateral > 0:
            max_contracts_bp = math.floor(capital / collateral)
            if rec_contracts > max_contracts_bp:
                rec_contracts = max_contracts_bp
                reasons.append("Capped by Buying Power")

        rec_contracts = int(max(0, rec_contracts))

        # Hard max cap
        HARD_MAX = 100
        if rec_contracts > HARD_MAX:
            rec_contracts = HARD_MAX
            reasons.append("Capped by global max")

        return AgentSignal(
            agent_id=self.id,
            score=base_score, # We return base score but sizing metadata reflects the logic
            veto=False, # Sizing agent rarely vetos, just returns 0 contracts if needed
            reasons=reasons,
            metadata={
                "constraints": {
                    "sizing.target_risk_usd": round(target_risk, 2),
                    "sizing.max_risk_usd": round(max_risk, 2),
                    "sizing.min_risk_usd": round(min_risk, 2),
                    "sizing.recommended_contracts": rec_contracts,
                    "sizing.max_contracts": HARD_MAX,
                    "sizing.risk_scale_factor": round(final_scale_factor, 2)
                }
            }
        )
