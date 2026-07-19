# packages/quantum/analytics/strategy_selector.py
from __future__ import annotations

import logging
import os
from typing import Optional, Union, List

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

        # Helper to apply a chosen suggestion.
        def apply_suggestion(strat: str, rationale: str, legs: list):
            suggestion.update(strategy=strat, rationale=rationale, legs=legs)


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

    def get_candidates(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
        effective_regime: Optional[Union[RegimeState, str]] = None,
        phase_exclusions_out: Optional[List[dict]] = None,
    ) -> List[dict]:
        """
        Return ordered list of candidate strategies to evaluate.

        Regime informs the candidate POOL, not the winner.
        EV after costs picks the winner downstream.

        phase_exclusions_out: optional caller-owned list (funnel phase-2
        observability seam). When the PHASE GATE removes a strategy from
        the pool, one ``{"strategy": <name>, "phase": <phase>}`` dict per
        DISTINCT excluded strategy is appended. Report-only: the returned
        candidate list is identical whether or not the list is passed,
        and an empty pool with no exclusions stays an honest HOLD verdict
        at the caller. SHOCK's early empty return happens BEFORE the
        phase gate and reports nothing (not a phase exclusion).

        Returns list of dicts, each with:
          strategy, legs, rationale (same shape as determine_strategy output)
        Max 3 candidates per symbol.
        """
        s = (sentiment or "NEUTRAL").upper().strip()
        if s not in {"BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"}:
            s = "NEUTRAL"

        regime_state = self._coerce_regime(effective_regime, iv_rank)

        is_low_vol = (iv_rank is not None and iv_rank < 30) or regime_state == RegimeState.SUPPRESSED
        is_high_vol = (iv_rank is not None and iv_rank > 50) or regime_state in {
            RegimeState.ELEVATED, RegimeState.SHOCK, RegimeState.REBOUND,
        }

        # SHOCK → no trades
        if regime_state == RegimeState.SHOCK and s != "EARNINGS":
            return []

        # Build candidate pool based on sentiment + vol
        pool: List[tuple] = []  # (strategy_name, rationale, legs)

        if s == "BULLISH":
            if is_high_vol:
                pool.append((
                    "SHORT_PUT_CREDIT_SPREAD",
                    "Bullish + elevated IV. Sell put premium.",
                    [{"side": "sell", "type": "put", "delta_target": -0.30},
                     {"side": "buy", "type": "put", "delta_target": -0.15}],
                ))
                pool.append((
                    "LONG_CALL_DEBIT_SPREAD",
                    "Bullish fallback. Debit spread if credit spreads too wide.",
                    [{"side": "buy", "type": "call", "delta_target": 0.65},
                     {"side": "sell", "type": "call", "delta_target": 0.30}],
                ))
            elif is_low_vol:
                pool.append((
                    "LONG_CALL_DEBIT_SPREAD",
                    "Bullish + low IV. Buy cheap premium.",
                    [{"side": "buy", "type": "call", "delta_target": 0.65},
                     {"side": "sell", "type": "call", "delta_target": 0.30}],
                ))
            else:
                pool.append((
                    "LONG_CALL_DEBIT_SPREAD",
                    "Bullish + normal IV. Debit vertical.",
                    [{"side": "buy", "type": "call", "delta_target": 0.60},
                     {"side": "sell", "type": "call", "delta_target": 0.30}],
                ))
                pool.append((
                    "SHORT_PUT_CREDIT_SPREAD",
                    "Bullish alternative. Credit spread for premium.",
                    [{"side": "sell", "type": "put", "delta_target": -0.30},
                     {"side": "buy", "type": "put", "delta_target": -0.15}],
                ))

        elif s == "BEARISH":
            if is_high_vol:
                pool.append((
                    "SHORT_CALL_CREDIT_SPREAD",
                    "Bearish + elevated IV. Sell call premium.",
                    [{"side": "sell", "type": "call", "delta_target": 0.30},
                     {"side": "buy", "type": "call", "delta_target": 0.15}],
                ))
                pool.append((
                    "LONG_PUT_DEBIT_SPREAD",
                    "Bearish fallback. Debit spread if credit spreads too wide.",
                    [{"side": "buy", "type": "put", "delta_target": -0.65},
                     {"side": "sell", "type": "put", "delta_target": -0.30}],
                ))
            elif is_low_vol:
                pool.append((
                    "LONG_PUT_DEBIT_SPREAD",
                    "Bearish + low IV. Buy cheap premium.",
                    [{"side": "buy", "type": "put", "delta_target": -0.65},
                     {"side": "sell", "type": "put", "delta_target": -0.30}],
                ))
            else:
                pool.append((
                    "LONG_PUT_DEBIT_SPREAD",
                    "Bearish + normal IV. Debit vertical.",
                    [{"side": "buy", "type": "put", "delta_target": -0.60},
                     {"side": "sell", "type": "put", "delta_target": -0.30}],
                ))
                pool.append((
                    "SHORT_CALL_CREDIT_SPREAD",
                    "Bearish alternative. Credit spread for premium.",
                    [{"side": "sell", "type": "call", "delta_target": 0.30},
                     {"side": "buy", "type": "call", "delta_target": 0.15}],
                ))

        elif s == "NEUTRAL" or regime_state == RegimeState.CHOP:
            if is_high_vol or regime_state == RegimeState.CHOP:
                pool.append((
                    "IRON_CONDOR",
                    "Neutral + elevated IV. Defined-risk premium sale.",
                    [{"side": "sell", "type": "put", "delta_target": -0.20},
                     {"side": "buy", "type": "put", "delta_target": -0.10},
                     {"side": "sell", "type": "call", "delta_target": 0.20},
                     {"side": "buy", "type": "call", "delta_target": 0.10}],
                ))

        elif s == "EARNINGS":
            if is_high_vol:
                pool.append((
                    "IRON_CONDOR",
                    "Earnings + rich IV. Defined-risk premium sale.",
                    [{"side": "sell", "type": "put", "delta_target": -0.20},
                     {"side": "buy", "type": "put", "delta_target": -0.10},
                     {"side": "sell", "type": "call", "delta_target": 0.20},
                     {"side": "buy", "type": "call", "delta_target": 0.10}],
                ))

        # Phase-aware strategy exclusion
        _phase = os.environ.get("CURRENT_PROGRESSION_PHASE", "alpaca_paper")
        _phase_excluded = set()
        if _phase == "alpaca_paper":
            _phase_excluded.add("IRON_CONDOR")

        # Filter by policy, phase, and cap at 3
        candidates = []
        _reported_exclusions = set()
        for strat, rationale, legs in pool:
            if strat in _phase_excluded:
                logging.getLogger(__name__).info(
                    f"[SCANNER_MULTI] {strat} excluded (phase={_phase})"
                )
                # Funnel phase-2: report the exclusion to the caller so
                # the scanner can record a TYPED strategy_phase_excluded
                # rejection with strategy attribution (distinct from the
                # generic strategy_hold_no_candidates bucket). Report-only
                # — never changes the candidate pool built below.
                if (
                    phase_exclusions_out is not None
                    and strat not in _reported_exclusions
                ):
                    _reported_exclusions.add(strat)
                    phase_exclusions_out.append(
                        {"strategy": strat, "phase": _phase}
                    )
                continue
            if len(candidates) < 3:
                candidates.append({
                    "ticker": ticker,
                    "strategy": strat,
                    "legs": legs,
                    "rationale": rationale,
                    "meta": {
                        "sentiment": s,
                        "iv_rank": iv_rank,
                        "effective_regime": regime_state.value,
                    },
                })

        return candidates

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
