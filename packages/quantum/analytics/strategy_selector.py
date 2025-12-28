# packages/quantum/analytics/strategy_selector.py
from __future__ import annotations

from typing import Optional, Union, List

from .regime_engine_v3 import RegimeState
from .strategy_policy import StrategyPolicy


class StrategySelector:
    def determine_strategy(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
        effective_regime: Optional[Union[RegimeState, str]] = None,
        banned_strategies: Optional[List[str]] = None,
    ) -> dict:
        """
        Converts sentiment + volatility/regime context into a concrete options structure.

        Inputs
        - sentiment: BULLISH | BEARISH | NEUTRAL | EARNINGS (case-insensitive)
        - effective_regime: RegimeState (preferred) OR legacy string ("normal"/"elevated"/"shock"/...)
        - banned_strategies: List of strategy keys or categories to exclude.

        Output dict fields:
        - ticker, strategy, legs, rationale
        - meta (non-breaking extra context for debugging/analytics)
        """
        s = (sentiment or "NEUTRAL").upper().strip()
        if s not in {"BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"}:
            s = "NEUTRAL"

        # Initialize Policy
        policy = StrategyPolicy(banned_strategies)

        regime_state = self._coerce_regime(effective_regime, iv_rank)

        # IV heuristics remain useful even with regimes (backward compatibility + extra signal)
        iv_low = iv_rank is not None and iv_rank < 30
        iv_high = iv_rank is not None and iv_rank > 50

        is_low_vol = iv_low or regime_state == RegimeState.SUPPRESSED
        is_high_vol = iv_high or regime_state in {
            RegimeState.ELEVATED,
            RegimeState.SHOCK,
            RegimeState.REBOUND,
        }
        is_chop = regime_state == RegimeState.CHOP

        suggestion = {
            "ticker": ticker,
            "strategy": "HOLD",
            "legs": [],
            "rationale": "",
            "meta": {
                "sentiment": s,
                "iv_rank": iv_rank,
                "effective_regime": regime_state.value,
            },
        }

        # Helper to apply suggestion safely with policy check
        def apply_suggestion(strat: str, rationale: str, legs: list):
            if policy.is_allowed(strat):
                suggestion.update(strategy=strat, rationale=rationale, legs=legs)
            else:
                # If banned, we might want to fallback or just stay HOLD.
                # For now, we revert to HOLD if the primary choice is banned.
                # Ideally, we could try an alternative (e.g. Debit Spread instead of Credit Spread).

                # Simple fallback logic:
                # If Credit Spread is banned, try Debit Spread if direction matches.
                # Note: This is a basic heuristic.

                fallback_strat = None
                fallback_legs = []
                fallback_rationale = ""

                if "SHORT_PUT_CREDIT_SPREAD" in strat:
                    # Bullish credit banned -> Bullish debit
                    fallback_strat = "LONG_CALL_DEBIT_SPREAD"
                    fallback_rationale = f"{rationale} (Fallback: Credit banned). Using Debit Spread."
                    fallback_legs = [
                        {"side": "buy", "type": "call", "delta_target": 0.60},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ]
                elif "SHORT_CALL_CREDIT_SPREAD" in strat:
                    # Bearish credit banned -> Bearish debit
                    fallback_strat = "LONG_PUT_DEBIT_SPREAD"
                    fallback_rationale = f"{rationale} (Fallback: Credit banned). Using Debit Spread."
                    fallback_legs = [
                        {"side": "buy", "type": "put", "delta_target": -0.60},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ]
                elif "IRON_CONDOR" in strat:
                    # Neutral credit banned -> No good debit alternative for pure neutral income without credit
                    # Could do Long Iron Condor (Debit) but that is a volatility play (Long Vega), not neutral/short-vol.
                    # So fallback is HOLD.
                    pass

                if fallback_strat and policy.is_allowed(fallback_strat):
                    suggestion.update(strategy=fallback_strat, rationale=fallback_rationale, legs=fallback_legs)
                else:
                    # Final fallback: HOLD
                    reason = policy.get_rejection_reason(strat)
                    suggestion.update(
                        strategy="HOLD",
                        rationale=f"Strategy {strat} banned. {reason or ''} No valid fallback."
                    )


        # 1) CHOP: range-bound first, regardless of directional lean
        if is_chop and s in {"BULLISH", "BEARISH", "NEUTRAL"}:
            apply_suggestion(
                "IRON_CONDOR",
                "Chop regime. Neutral theta harvest with defined risk.",
                [
                    {"side": "sell", "type": "put", "delta_target": -0.20},
                    {"side": "buy", "type": "put", "delta_target": -0.10},
                    {"side": "sell", "type": "call", "delta_target": 0.20},
                    {"side": "buy", "type": "call", "delta_target": 0.10},
                ]
            )
            return suggestion

        # 2) SHOCK: default to defense unless you explicitly want otherwise
        if regime_state == RegimeState.SHOCK and s != "EARNINGS":
            apply_suggestion(
                "CASH",
                "Shock regime. Default to capital preservation; avoid new risk.",
                []
            )
            return suggestion

        # 3) Directional routing
        if s == "BULLISH":
            if is_low_vol:
                apply_suggestion(
                    "LONG_CALL_DEBIT_SPREAD",
                    "Bullish + low/suppressed IV. Buy defined-risk upside.",
                    [
                        {"side": "buy", "type": "call", "delta_target": 0.65},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ]
                )
            elif is_high_vol:
                apply_suggestion(
                    "SHORT_PUT_CREDIT_SPREAD",
                    "Bullish + elevated IV. Sell defined-risk put premium.",
                    [
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                        {"side": "buy", "type": "put", "delta_target": -0.15},
                    ]
                )
            else:
                apply_suggestion(
                    "LONG_CALL_DEBIT_SPREAD",
                    "Bullish + normal IV. Defined-risk vertical.",
                    [
                        {"side": "buy", "type": "call", "delta_target": 0.60},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ]
                )

        elif s == "BEARISH":
            if is_low_vol:
                apply_suggestion(
                    "LONG_PUT_DEBIT_SPREAD",
                    "Bearish + low/suppressed IV. Buy defined-risk downside.",
                    [
                        {"side": "buy", "type": "put", "delta_target": -0.65},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ]
                )
            elif is_high_vol:
                apply_suggestion(
                    "SHORT_CALL_CREDIT_SPREAD",
                    "Bearish + elevated IV. Sell defined-risk call premium.",
                    [
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                        {"side": "buy", "type": "call", "delta_target": 0.15},
                    ]
                )
            else:
                apply_suggestion(
                    "LONG_PUT_DEBIT_SPREAD",
                    "Bearish + normal IV. Defined-risk vertical.",
                    [
                        {"side": "buy", "type": "put", "delta_target": -0.60},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ]
                )

        # 4) Neutral routing
        elif s == "NEUTRAL":
            # Only sell premium when IV is rich enough; otherwise skip.
            if is_high_vol:
                apply_suggestion(
                    "IRON_CONDOR",
                    "Neutral + elevated IV. Sell both sides with defined risk.",
                    [
                        {"side": "sell", "type": "put", "delta_target": -0.20},
                        {"side": "buy", "type": "put", "delta_target": -0.10},
                        {"side": "sell", "type": "call", "delta_target": 0.20},
                        {"side": "buy", "type": "call", "delta_target": 0.10},
                    ]
                )
            else:
                apply_suggestion(
                    "HOLD",
                    "Neutral + low/normal IV. Not enough edge to sell premium; skip.",
                    []
                )

        # 5) Earnings routing (conservative until long-vol builders exist)
        elif s == "EARNINGS":
            if is_high_vol:
                apply_suggestion(
                    "IRON_CONDOR",
                    "Earnings + rich IV. Defined-risk premium sale (condor).",
                    [
                        {"side": "sell", "type": "put", "delta_target": -0.20},
                        {"side": "buy", "type": "put", "delta_target": -0.10},
                        {"side": "sell", "type": "call", "delta_target": 0.20},
                        {"side": "buy", "type": "call", "delta_target": 0.10},
                    ]
                )
            else:
                apply_suggestion(
                    "HOLD",
                    "Earnings but IV not rich enough for premium sale; skip.",
                    []
                )

        return suggestion

    @staticmethod
    def _coerce_regime(
        effective_regime: Optional[Union[RegimeState, str]],
        iv_rank: Optional[float],
    ) -> RegimeState:
        """
        Coerce effective_regime into RegimeState safely.
        If missing/invalid, infer from iv_rank as a legacy fallback.
        """
        if isinstance(effective_regime, RegimeState):
            return effective_regime

        if isinstance(effective_regime, str) and effective_regime.strip():
            try:
                return RegimeState(effective_regime.strip().lower())
            except Exception:
                pass

        # Legacy fallback using IV rank only
        if iv_rank is None:
            return RegimeState.NORMAL
        if iv_rank >= 95:
            return RegimeState.SHOCK
        if iv_rank >= 80:
            return RegimeState.ELEVATED
        if iv_rank <= 20:
            return RegimeState.SUPPRESSED
        return RegimeState.NORMAL
