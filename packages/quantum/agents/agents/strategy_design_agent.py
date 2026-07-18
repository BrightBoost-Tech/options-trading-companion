import logging
from typing import Dict, Any
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal
from packages.quantum.observability.feature_flags import is_iv_rank_none_routing_enabled

logger = logging.getLogger(__name__)

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

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Context inputs:
        - legacy_strategy: str (e.g. "IRON CONDOR", "LONG CALL")
        - effective_regime: str (e.g. "SHOCK", "BULLISH", "CHOP")
        - iv_rank: float (0-100)
        """
        raw_legacy = context.get("legacy_strategy", "")
        legacy_strategy = self._normalize_strategy(raw_legacy)

        effective_regime = str(context.get("effective_regime", "NEUTRAL")).upper()
        # #115 PR-B-2: when IV_RANK_NONE_ROUTING_ENABLED, skip the iv-aware
        # override branch instead of fabricating 50.0 (the silent default
        # that always evaluated `50 >= 60` as False, masking missing input
        # by routing into the no-override path). Flag OFF preserves the
        # legacy fallback to 50.0 verbatim.
        raw_iv_rank = context.get("iv_rank")
        if is_iv_rank_none_routing_enabled() and raw_iv_rank is None:
            iv_rank = None
            logger.info(
                "strategy_design_agent: iv_rank missing — skipping high-IV override branch"
            )
        else:
            iv_rank = float(raw_iv_rank if raw_iv_rank is not None else 50.0)

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
                # Switch to Credit Spread/Condor (neutral/sold).
                # Prefer Iron Condor for Chop.
                candidate = "iron_condor"
                recommended = candidate
                override = True
                reasons.append(f"Regime is CHOP: Overriding Long Premium to {candidate}")

        # 3. High IV Rank Check
        # "If iv_rank high (>=60) and legacy is long premium -> override to defined-risk credit variant (reduce vega bleed)"
        # PR-B-2: when iv_rank is None (flag ON + missing input), this
        # branch is skipped entirely — no override decision is made on
        # absent data.
        if iv_rank is not None and iv_rank >= 60.0 and recommended != "cash":
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
                     recommended = new_strat
                     override = True
                     reasons.append(f"High IV ({iv_rank}): Overriding Long Premium to {new_strat}")

        # Constraints payload
        constraints = {
            "strategy.recommended": recommended,
            "strategy.override_selector": override,
            "strategy.require_defined_risk": True # Always default to defined risk for agents
        }

        return AgentSignal(
            agent_id=self.id,
            score=score,
            veto=False,
            reasons=reasons,
            metadata={"constraints": constraints}
        )
