# packages/quantum/analytics/strategy_selector.py
from __future__ import annotations

from typing import Optional, Union

from .regime_engine_v3 import RegimeState


class StrategySelector:
    def determine_strategy(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
        effective_regime: Optional[Union[RegimeState, str]] = None,
    ) -> dict:
        """
        Converts sentiment + volatility/regime context into a concrete options structure.

        Inputs
        - sentiment: BULLISH | BEARISH | NEUTRAL | EARNINGS (case-insensitive)
        - effective_regime: RegimeState (preferred) OR legacy string ("normal"/"elevated"/"shock"/...)

        Output dict fields:
        - ticker, strategy, legs, rationale
        - meta (non-breaking extra context for debugging/analytics)
        """
        s = (sentiment or "NEUTRAL").upper().strip()
        if s not in {"BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"}:
            s = "NEUTRAL"

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

        # 1) CHOP: range-bound first, regardless of directional lean
        if is_chop and s in {"BULLISH", "BEARISH", "NEUTRAL"}:
            suggestion.update(
                strategy="IRON_CONDOR",
                rationale="Chop regime. Neutral theta harvest with defined risk.",
                legs=[
                    {"side": "sell", "type": "put", "delta_target": -0.20},
                    {"side": "buy", "type": "put", "delta_target": -0.10},
                    {"side": "sell", "type": "call", "delta_target": 0.20},
                    {"side": "buy", "type": "call", "delta_target": 0.10},
                ],
            )
            return suggestion

        # 2) SHOCK: default to defense unless you explicitly want otherwise
        if regime_state == RegimeState.SHOCK and s != "EARNINGS":
            suggestion.update(
                strategy="CASH",
                rationale="Shock regime. Default to capital preservation; avoid new risk.",
                legs=[],
            )
            return suggestion

        # 3) Directional routing
        if s == "BULLISH":
            if is_low_vol:
                suggestion.update(
                    strategy="LONG_CALL_DEBIT_SPREAD",
                    rationale="Bullish + low/suppressed IV. Buy defined-risk upside.",
                    legs=[
                        {"side": "buy", "type": "call", "delta_target": 0.65},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ],
                )
            elif is_high_vol:
                suggestion.update(
                    strategy="SHORT_PUT_CREDIT_SPREAD",
                    rationale="Bullish + elevated IV. Sell defined-risk put premium.",
                    legs=[
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                        {"side": "buy", "type": "put", "delta_target": -0.15},
                    ],
                )
            else:
                suggestion.update(
                    strategy="LONG_CALL_DEBIT_SPREAD",
                    rationale="Bullish + normal IV. Defined-risk vertical.",
                    legs=[
                        {"side": "buy", "type": "call", "delta_target": 0.60},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ],
                )

        elif s == "BEARISH":
            if is_low_vol:
                suggestion.update(
                    strategy="LONG_PUT_DEBIT_SPREAD",
                    rationale="Bearish + low/suppressed IV. Buy defined-risk downside.",
                    legs=[
                        {"side": "buy", "type": "put", "delta_target": -0.65},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ],
                )
            elif is_high_vol:
                suggestion.update(
                    strategy="SHORT_CALL_CREDIT_SPREAD",
                    rationale="Bearish + elevated IV. Sell defined-risk call premium.",
                    legs=[
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                        {"side": "buy", "type": "call", "delta_target": 0.15},
                    ],
                )
            else:
                suggestion.update(
                    strategy="LONG_PUT_DEBIT_SPREAD",
                    rationale="Bearish + normal IV. Defined-risk vertical.",
                    legs=[
                        {"side": "buy", "type": "put", "delta_target": -0.60},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ],
                )

        # 4) Neutral routing
        elif s == "NEUTRAL":
            # Only sell premium when IV is rich enough; otherwise skip.
            if is_high_vol:
                suggestion.update(
                    strategy="IRON_CONDOR",
                    rationale="Neutral + elevated IV. Sell both sides with defined risk.",
                    legs=[
                        {"side": "sell", "type": "put", "delta_target": -0.20},
                        {"side": "buy", "type": "put", "delta_target": -0.10},
                        {"side": "sell", "type": "call", "delta_target": 0.20},
                        {"side": "buy", "type": "call", "delta_target": 0.10},
                    ],
                )
            else:
                suggestion.update(
                    strategy="HOLD",
                    rationale="Neutral + low/normal IV. Not enough edge to sell premium; skip.",
                    legs=[],
                )

        # 5) Earnings routing (conservative until long-vol builders exist)
        elif s == "EARNINGS":
            if is_high_vol:
                suggestion.update(
                    strategy="IRON_CONDOR",
                    rationale="Earnings + rich IV. Defined-risk premium sale (condor).",
                    legs=[
                        {"side": "sell", "type": "put", "delta_target": -0.20},
                        {"side": "buy", "type": "put", "delta_target": -0.10},
                        {"side": "sell", "type": "call", "delta_target": 0.20},
                        {"side": "buy", "type": "call", "delta_target": 0.10},
                    ],
                )
            else:
                suggestion.update(
                    strategy="HOLD",
                    rationale="Earnings but IV not rich enough for premium sale; skip.",
                    legs=[],
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
