from typing import Dict, Any, List
from packages.quantum.agents.core import BaseQuantAgent, AgentSignal

class StrategyDesignAgent(BaseQuantAgent):
    """
    Agent responsible for selecting or overriding the trading strategy based on
    market regime and IV rank.
    """

    @property
    def id(self) -> str:
        return "strategy_design"

    def evaluate(self, context: Dict[str, Any]) -> AgentSignal:
        """
        Context inputs:
        - legacy_strategy: str (e.g. "IRON CONDOR", "LONG CALL")
        - effective_regime: str (e.g. "SHOCK", "BULLISH", "CHOP")
        - iv_rank: float (0-100)
        - banned_strategies: List[str] (optional)
        """
        legacy_strategy = str(context.get("legacy_strategy", "")).upper()
        effective_regime = str(context.get("effective_regime", "NEUTRAL")).upper()
        iv_rank = float(context.get("iv_rank", 50.0))
        banned_strategies = context.get("banned_strategies", []) or []

        # Default: stick to legacy
        recommended = legacy_strategy
        override = False
        reasons = []
        score = 80.0

        # --- Override Logic (Deterministic v1) ---

        # 1. SHOCK Regime Check
        if "SHOCK" in effective_regime:
            if "CONDOR" in legacy_strategy or "CREDIT" in legacy_strategy:
                # Override to CASH (Safety)
                recommended = "CASH"
                override = True
                reasons.append(f"Regime is SHOCK: Overriding {legacy_strategy} to CASH/HOLD")
                score = 100.0 # High confidence in safety override

        # 2. CHOP Regime Check
        # "If effective_regime includes 'CHOP' and legacy is long premium -> override to defined-risk credit (or CASH)"
        elif "CHOP" in effective_regime:
            is_long_premium = "DEBIT" in legacy_strategy or "LONG" in legacy_strategy or "BUY" in legacy_strategy
            if is_long_premium:
                # Override to defined-risk credit or CASH
                # Let's verify we aren't banning credit spreads
                if "CREDIT SPREAD" not in banned_strategies:
                     # Attempt to switch to Credit Spread (neutral/sold)
                     # But which direction? CHOP implies mean reversion.
                     # If legacy was Long Call -> Short Put Spread (Bullish)?
                     # If legacy was Long Put -> Short Call Spread (Bearish)?
                     # Prompt says "defined-risk credit variant".
                     # Actually, if we are chopping, directional bets are risky.
                     # Maybe Iron Condor?
                     recommended = "IRON CONDOR"
                     override = True
                     reasons.append(f"Regime is CHOP: Overriding Long Premium to IRON CONDOR")
                else:
                     recommended = "CASH"
                     override = True
                     reasons.append("Regime is CHOP & Credit Banned: Overriding to CASH")

        # 3. High IV Rank Check
        # "If iv_rank high (>=60) and legacy is long premium -> override to defined-risk credit variant (reduce vega bleed)"
        if iv_rank >= 60.0:
            is_long_premium = "DEBIT" in legacy_strategy or "LONG" in legacy_strategy or "BUY" in legacy_strategy

            # Note: If we already overrode to CASH or CONDOR above, we might skip this or refine it.
            # If recommended is already CASH, don't change it back.
            if recommended != "CASH" and is_long_premium:
                 # Override to Credit
                 # Long Call -> Bull Put Spread
                 # Long Put -> Bear Call Spread

                 new_strat = None
                 if "CALL" in legacy_strategy:
                     new_strat = "CREDIT PUT SPREAD" # Bullish
                 elif "PUT" in legacy_strategy:
                     new_strat = "CREDIT CALL SPREAD" # Bearish

                 if new_strat and new_strat not in banned_strategies:
                     recommended = new_strat
                     override = True
                     reasons.append(f"High IV ({iv_rank}): Overriding Long Premium to {new_strat}")
                 elif "IRON CONDOR" not in banned_strategies and "CONDOR" not in legacy_strategy:
                     # Fallback to Condor if directional credit blocked?
                     # Or just CASH
                     pass

        # 4. Respect Banned Strategies
        # If the *recommended* strategy is banned, force CASH/HOLD
        # Note: We check normalized strings.
        # "CREDIT SPREAD" might cover "CREDIT PUT SPREAD" depending on policy implementation.
        # Here we do a simple check.
        if recommended in banned_strategies:
             recommended = "CASH"
             override = True
             reasons.append(f"Strategy {recommended} is Banned: Defaulting to CASH")

        # Constraints payload
        constraints = {
            "strategy.recommended": recommended,
            "strategy.override_selector": override,
            "strategy.banned": banned_strategies,
            "strategy.require_defined_risk": True # Always default to defined risk for agents
        }

        if recommended == "CASH" or recommended == "HOLD":
            # If we recommend CASH, that's effectively a veto on the *legacy* trade,
            # or a successful signal for "Do Nothing".
            # In the scanner context, returning "HOLD" strategy usually results in `None` candidate.
            pass

        return AgentSignal(
            agent_id=self.id,
            score=score,
            veto=False, # We don't veto the *process*, we just change the strategy.
                        # Unless recommended is CASH, which scanner might interpret as "no trade".
            reasons=reasons,
            metadata={"constraints": constraints}
        )
