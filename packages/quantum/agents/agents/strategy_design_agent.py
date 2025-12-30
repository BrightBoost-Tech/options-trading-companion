from typing import Dict, Any, List, Optional
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal
from packages.quantum.analytics.strategy_policy import StrategyPolicy

class StrategyDesignAgent(BaseQuantAgent):
    """
    Agent responsible for selecting or overriding the trading strategy based on
    market regime and IV rank.
    """

    @property
    def id(self) -> str:
        return "strategy_design"

    def _normalize_strategy(self, strategy_name: str) -> str:
        """
        Normalizes human-readable strategy names to internal snake_case keys.
        """
        s = str(strategy_name).upper().strip()

        # Explicit mappings
        mapping = {
            "IRON CONDOR": "iron_condor",
            "LONG CALL": "long_call",
            "LONG PUT": "long_put",
            "CREDIT PUT SPREAD": "credit_put_spread",
            "CREDIT CALL SPREAD": "credit_call_spread",
            "DEBIT CALL SPREAD": "debit_call_spread",
            "DEBIT PUT SPREAD": "debit_put_spread",
            "CASH": "cash",
            "HOLD": "cash"
        }

        if s in mapping:
            return mapping[s]

        # Fallback normalization
        return s.lower().replace(" ", "_")

    def _get_fallback_strategy(self, strategy: str, policy: StrategyPolicy) -> Optional[str]:
        """
        Returns a valid fallback strategy if the primary one is banned.
        """
        # Bullish: Credit Put Spread <-> Debit Call Spread
        if strategy == "credit_put_spread":
            return "debit_call_spread" if policy.is_allowed("debit_call_spread") else None
        if strategy == "debit_call_spread":
            return "credit_put_spread" if policy.is_allowed("credit_put_spread") else None

        # Bearish: Credit Call Spread <-> Debit Put Spread
        if strategy == "credit_call_spread":
            return "debit_put_spread" if policy.is_allowed("debit_put_spread") else None
        if strategy == "debit_put_spread":
            return "credit_call_spread" if policy.is_allowed("credit_call_spread") else None

        # Neutral: Iron Condor -> No direct equivalent that is usually safer/different enough?
        # If Iron Condor is banned, we probably just want CASH or HOLD unless we are okay with Butterflies (not impl).

        return None

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Context inputs:
        - legacy_strategy: str (e.g. "IRON CONDOR", "LONG CALL")
        - effective_regime: str (e.g. "SHOCK", "BULLISH", "CHOP")
        - iv_rank: float (0-100)
        - banned_strategies: List[str] (optional)
        """
        raw_legacy = context.get("legacy_strategy", "")
        legacy_strategy = self._normalize_strategy(raw_legacy)

        effective_regime = str(context.get("effective_regime", "NEUTRAL")).upper()
        iv_rank = float(context.get("iv_rank", 50.0))

        # Initialize Policy
        # raw_banned can be None, StrategyPolicy handles None
        policy = StrategyPolicy(context.get("banned_strategies"))

        # Default: stick to legacy
        recommended = legacy_strategy
        override = False
        reasons = []
        score = 80.0

        # --- Override Logic (Deterministic v1) ---

        # 1. SHOCK Regime Check
        if "SHOCK" in effective_regime:
            # Override to CASH (Safety)
            # CASH is always allowed (not checkable by policy generally, but safe)
            recommended = "cash"
            override = True
            reasons.append(f"Regime is SHOCK: Overriding {legacy_strategy} to cash")
            score = 100.0 # High confidence in safety override

        # 2. CHOP Regime Check
        elif "CHOP" in effective_regime and recommended != "cash":
            is_long_premium = "debit" in legacy_strategy or "long" in legacy_strategy or "buy" in legacy_strategy
            if is_long_premium:
                # Attempt to switch to Credit Spread/Condor (neutral/sold)
                # Prefer Iron Condor for Chop
                candidate = "iron_condor"

                if policy.is_allowed(candidate):
                     recommended = candidate
                     override = True
                     reasons.append(f"Regime is CHOP: Overriding Long Premium to {candidate}")
                else:
                     # If Iron Condor banned, maybe Cash?
                     recommended = "cash"
                     override = True
                     reasons.append(f"Regime is CHOP & {candidate} Banned: Overriding to cash")

        # 3. High IV Rank Check
        # "If iv_rank high (>=60) and legacy is long premium -> override to defined-risk credit variant (reduce vega bleed)"
        if iv_rank >= 60.0 and recommended != "cash":
            # Only override if we haven't already settled on something safe
            # And if current rec is long premium
            is_long_premium = "debit" in recommended or "long" in recommended or "buy" in recommended

            if is_long_premium:
                 new_strat = None
                 if "call" in recommended:
                     new_strat = "credit_put_spread" # Bullish
                 elif "put" in recommended:
                     new_strat = "credit_call_spread" # Bearish

                 if new_strat:
                     if policy.is_allowed(new_strat):
                         recommended = new_strat
                         override = True
                         reasons.append(f"High IV ({iv_rank}): Overriding Long Premium to {new_strat}")
                     else:
                         # Credit banned? Maybe stay with debit or go to cash?
                         # If we are High IV, Long Premium is bad.
                         # If Credit is banned, we can't sell premium.
                         # Maybe fallback to CASH is safer than bleeding theta/vega?
                         # Or just stick to original if user really wants it (but user banned credit).
                         # Let's try to stick to original unless it's strictly banned or really bad.
                         # If the user strictly banned credit, we can't do it.
                         # We'll check the validity of the current 'recommended' at the end.
                         pass

        # 4. Final Policy Enforcement
        # Ensure the final recommendation is allowed.
        # If 'cash' or 'hold', we assume it's always allowed (safe fallback).
        if recommended not in ("cash", "hold") and not policy.is_allowed(recommended):
            # Try to find a fallback
            fallback = self._get_fallback_strategy(recommended, policy)
            if fallback:
                original_rec = recommended
                recommended = fallback
                override = True
                reasons.append(f"Strategy {original_rec} is Banned. Fallback to {fallback}.")
            else:
                original_rec = recommended
                recommended = "cash"
                override = True
                reasons.append(f"Strategy {original_rec} is Banned & No Fallback. Defaulting to cash.")

        # Constraints payload
        constraints = {
            "strategy.recommended": recommended,
            "strategy.override_selector": override,
            "strategy.banned": list(policy.banned_strategies), # Serialize set to list
            "strategy.require_defined_risk": True # Always default to defined risk for agents
        }

        return AgentSignal(
            agent_id=self.id,
            score=score,
            veto=False,
            reasons=reasons,
            metadata={"constraints": constraints}
        )
