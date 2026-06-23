
import math
import os
import hashlib
import json
import logging
from typing import Dict, Any, Optional, List
from packages.quantum.services.replay.canonical import compute_content_hash
from packages.quantum.observability.feature_flags import is_iv_rank_none_routing_enabled

logger = logging.getLogger(__name__)

# --- Cluster 2: VRP-aware soft down-weight (debit / long-premium only) -------
# Long debit spreads want IV cheap relative to realized. The volatility-risk-
# premium proxy iv_rv_spread = atm_iv - rv_20d is already computed once in
# regime_engine_v3 (log-return rv after Cluster 1) — we REUSE it here, never
# recompute. A positive spread (IV rich vs realized) SOFTLY reduces the debit
# score; a non-positive spread (IV cheap/fair) gives a mild boost. This is a
# soft down-weight ONLY — there is no veto / no-buy logic anywhere in this path.
VRP_FLOOR = float(os.getenv("VRP_FLOOR", "0.7"))   # strongest down-weight (IV richest)
VRP_CEIL = float(os.getenv("VRP_CEIL", "1.1"))     # strongest boost (IV cheapest/fairest)
VRP_SCALE = float(os.getenv("VRP_SCALE", "0.10"))  # spread magnitude (vol pts) mapping to the multiplier; tanh ~saturates near this
# Log only when the multiplier materially moves a score (|1 - mult| >= this).
VRP_LOG_THRESHOLD = float(os.getenv("VRP_LOG_THRESHOLD", "0.02"))


def vrp_score_multiplier(iv_rv_spread: Optional[float]) -> float:
    """Map the VRP proxy iv_rv_spread (atm_iv - rv_20d) to a soft debit-score
    multiplier in [VRP_FLOOR, VRP_CEIL].

    Pure, monotonic, continuous (smooth tanh; no step/cliff at any threshold):
      - iv_rv_spread > 0  (IV rich vs realized): multiplier < 1.0, decreasing
        with richness, saturating at VRP_FLOOR.
      - iv_rv_spread <= 0 (IV cheap/fair):       multiplier >= 1.0, up to VRP_CEIL.
      - iv_rv_spread is None (unavailable):      1.0 (no-op — never penalize
        missing data; such names are already excluded upstream by Cluster 1's
        min-history gate, but we stay defensive).

    Asymmetric amplitude makes each side saturate exactly at its bound while the
    value stays continuous through the origin (multiplier(0) == 1.0).
    """
    if iv_rv_spread is None:
        return 1.0
    amp = (1.0 - VRP_FLOOR) if iv_rv_spread > 0 else (VRP_CEIL - 1.0)
    scale = VRP_SCALE if VRP_SCALE > 0 else 1e-9
    mult = 1.0 - amp * math.tanh(iv_rv_spread / scale)
    # Numerical safety clamp (tanh already bounds this to the exact endpoints).
    return max(VRP_FLOOR, min(VRP_CEIL, mult))

def _fast_norm_cdf(x: float) -> float:
    """
    Cumulative distribution function for the standard normal distribution.
    Approximation using error function (math.erf).
    Performance: ~250x faster than scipy.stats.norm.cdf
    Precision: within 1e-15 of scipy implementation
    """
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))

class OpportunityScorer:
    """
    Authoritative V3 Scorer for Unified EV scoring.
    Computes EV, POP, liquidity penalty, and total score for trade candidates.
    """

    @staticmethod
    def score(trade_candidate: Dict[str, Any], market_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates the definitive score for a trade candidate.

        Args:
            trade_candidate: Dictionary containing trade details (strikes, type, expiry, credit/debit, etc.)
            market_ctx: Dictionary containing market context (price, iv, regime, greeks, etc.)

        Returns:
            A dictionary with enriched metrics:
            - score: Total score (0-100)
            - metrics: {ev_amount, ev_percent, prob_profit, reward_to_risk, ...}
            - penalties: {liquidity, event_risk, ...}
            - features_hash: Unique hash of inputs
        """
        try:
            # 1. Extract Inputs
            symbol = trade_candidate.get('symbol') or trade_candidate.get('ticker')
            strategy_type = trade_candidate.get('type', 'unknown').lower()

            # Pricing / Structure
            underlying_price = float(market_ctx.get('price') or trade_candidate.get('underlying_price') or 100.0)
            short_strike = float(trade_candidate.get('short_strike') or 0.0)
            long_strike = float(trade_candidate.get('long_strike') or 0.0)

            # Determine credit vs debit
            is_credit = 'credit' in strategy_type or trade_candidate.get('credit') is not None

            # Prices
            if is_credit:
                premium = float(trade_candidate.get('credit', 0.0))
                max_profit = premium * 100
                width = abs(short_strike - long_strike) if short_strike and long_strike else 0.0
                max_loss = (width - premium) * 100 if width > 0 else 0.0 # Standard vertical spread
                # Handle Iron Condors or naked puts if needed (assuming verticals/IC for now)
            else:
                # #115c: anti-pattern 2 fix. Pre-fix `or 0.0` silently
                # produced premium=0 when both `debit` and `cost` were
                # None on a debit candidate — yielding max_loss=0 and
                # max_profit=width*100, a fabricated free-money score
                # purely from missing data. Same shape as PR-B-2 iv_rank
                # site at line 142. When the input is genuinely missing,
                # bail with an explicit error result rather than score
                # the malformed candidate.
                raw_premium = trade_candidate.get('debit') or trade_candidate.get('cost')
                if raw_premium is None:
                    logger.info(
                        "opportunity_scorer: debit/cost both None for %s — "
                        "skipping score (cannot evaluate without premium)",
                        symbol,
                    )
                    return {
                        "score": 0.0,
                        "metrics": {},
                        "penalties": {},
                        "features_hash": None,
                        "debug": {"reason": "premium_missing"},
                    }
                premium = float(raw_premium)
                max_loss = premium * 100
                width = abs(short_strike - long_strike) if short_strike and long_strike else 0.0
                max_profit = (width - premium) * 100 if width > 0 else 0.0

            # Time
            dte = int(trade_candidate.get('dte') or 30)
            t_years = dte / 365.0

            # Volatility & Drift
            iv = float(market_ctx.get('iv') or market_ctx.get('implied_volatility') or 0.30)
            # Use IV Rank as a proxy if raw IV is missing or suspicious, but prefer raw IV for pricing
            if iv > 5.0: # If IV is passed as percentage like 30.0 instead of 0.30
                iv = iv / 100.0

            # Expected Return (Drift)
            # For now, default to risk-neutral (0) or slight market drift if available
            mu = float(market_ctx.get('expected_return') or 0.05)

            # 2. Compute Probabilities (Lognormal Terminal Model)
            # We calculate the probability of expiring ITM for short and long legs

            # d2 = (ln(S/K) + (r - 0.5*sigma^2)*T) / (sigma*sqrt(T))
            # P(S_T > K) = N(d2)

            def get_prob_itm(S, K, T, sigma, r):
                if K <= 0.001: return 1.0 # Strike 0 or neg is essentially ITM for call, OTM for put?
                # Actually if K=0, we can't take log.
                # If strikes are missing, we skip prob calc.
                if T <= 0 or sigma <= 0: return 0.0 if S < K else 1.0
                if S <= 0: return 0.0

                try:
                    # Optimized using math (C-speed) vs numpy/scipy
                    d2 = (math.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                    return _fast_norm_cdf(d2)
                except:
                    return 0.5

            if short_strike > 0:
                prob_short_itm = get_prob_itm(underlying_price, short_strike, t_years, iv, mu)
            else:
                prob_short_itm = 0.5

            if long_strike > 0:
                prob_long_itm = get_prob_itm(underlying_price, long_strike, t_years, iv, mu)
            else:
                prob_long_itm = 0.5

            # Calculate POP and EV based on strategy structure
            metrics = OpportunityScorer._calculate_ev_pop(
                strategy_type, is_credit,
                max_profit, max_loss,
                prob_short_itm, prob_long_itm
            )

            # 3. Penalties

            # Liquidity Penalty
            bid = float(market_ctx.get('bid', 0.0))
            ask = float(market_ctx.get('ask', 0.0))
            liquidity_penalty = OpportunityScorer._calculate_liquidity_penalty(bid, ask, underlying_price)

            # Event Risk Penalty (Earnings)
            earnings_penalty = 0.0
            if not trade_candidate.get('is_earnings_safe', True):
                earnings_penalty = 0.5 # 50% penalty if earnings collision

            # 4. Total Score Calculation

            # Base Score on EV% and POP
            # Normalize EV% (e.g. 5% edge is good, 20% is great)
            # Normalize POP (50% is neutral, 90% is high)

            ev_score = min(metrics['ev_percent'] * 5.0, 50.0) # Cap at 50 pts
            pop_score = metrics['prob_profit'] * 50.0 # Max 50 pts

            # Add IV Rank Bonus
            # #115 PR-B-2: most-impactful site. Pre-fix `or 0.0` silently
            # awarded debit candidates the MAXIMUM 10-point bonus when
            # iv_rank was missing — `not is_credit and 0 < 50` is True,
            # `(50 - 0) * 0.2 = 10`. Anti-pattern 2 with active score
            # distortion. When IV_RANK_NONE_ROUTING_ENABLED and iv_rank
            # is genuinely None, set iv_bonus=0 (neither direction gets a
            # bonus) and skip the comparison entirely. Flag OFF preserves
            # the legacy distorted behavior so anything currently
            # depending on it stays stable until the operator flips.
            raw_iv_rank = market_ctx.get('iv_rank')
            iv_bonus = 0.0
            if is_iv_rank_none_routing_enabled() and raw_iv_rank is None:
                logger.info(
                    "opportunity_scorer: iv_rank missing for %s — "
                    "iv_bonus=0 (no fabricated max bonus)",
                    symbol,
                )
            else:
                iv_rank = float(raw_iv_rank or 0.0)
                if is_credit and iv_rank > 50:
                    iv_bonus = (iv_rank - 50) * 0.2 # Max 10 pts
                elif not is_credit and iv_rank < 50:
                     iv_bonus = (50 - iv_rank) * 0.2 # Max 10 pts

            raw_score = ev_score + pop_score + iv_bonus

            # Cluster 2: VRP soft down-weight — applied at the SAME stage as the
            # (50 - iv_rank) * 0.2 debit bonus above, DEBIT (long-premium) ONLY.
            # Credit / short-premium scoring is untouched (multiplier forced 1.0).
            # MULTIPLIES the score (never adds). Reuses the existing iv_rv_spread;
            # no vol is recomputed. Missing spread -> 1.0 no-op.
            iv_rv_spread = market_ctx.get('iv_rv_spread')
            if is_credit:
                vrp_multiplier = 1.0
            else:
                vrp_multiplier = vrp_score_multiplier(iv_rv_spread)
            pre_vrp_score = raw_score
            raw_score = raw_score * vrp_multiplier
            if abs(1.0 - vrp_multiplier) >= VRP_LOG_THRESHOLD:
                logger.info(
                    "opportunity_scorer: VRP down-weight %s — iv_rv_spread=%s "
                    "multiplier=%.3f score %.1f -> %.1f",
                    symbol,
                    f"{iv_rv_spread:.4f}" if iv_rv_spread is not None else "None",
                    vrp_multiplier, pre_vrp_score, raw_score,
                )

            # Apply Penalties
            total_multiplier = (1.0 - liquidity_penalty) * (1.0 - earnings_penalty)
            total_score = max(0.0, min(100.0, raw_score * total_multiplier))

            # 5. Feature Hash
            features = {
                "sym": symbol,
                "str": strategy_type,
                "strikes": f"{short_strike}/{long_strike}",
                "exp": trade_candidate.get('expiry'),
                "iv": round(iv, 4),
                "mu": round(mu, 4),
                "price": round(underlying_price, 2)
            }
            features_hash = compute_content_hash(features)

            return {
                "score": round(total_score, 1),
                "metrics": {
                    "ev_amount": round(metrics['ev_amount'], 2),
                    "ev_percent": round(metrics['ev_percent'], 2),
                    "prob_profit": round(metrics['prob_profit'], 4),
                    "reward_to_risk": round(metrics['reward_to_risk'], 2),
                    "max_profit": round(max_profit, 2),
                    "max_loss": round(max_loss, 2)
                },
                "penalties": {
                    "liquidity": liquidity_penalty,
                    "event_risk": earnings_penalty
                },
                "features_hash": features_hash,
                "debug": {
                    "raw_score": round(raw_score, 1),
                    "iv_bonus": round(iv_bonus, 1),
                    "prob_short_itm": round(prob_short_itm, 4),
                    # Cluster 2 VRP observability: pre/post score + multiplier,
                    # so we can later measure how often and how hard it bit.
                    "iv_rv_spread": round(iv_rv_spread, 4) if iv_rv_spread is not None else None,
                    "vrp_multiplier": round(vrp_multiplier, 3),
                    "pre_vrp_score": round(pre_vrp_score, 1),
                    "post_vrp_score": round(raw_score, 1)
                }
            }

        except Exception as e:
            logger.error(f"Scoring error for {trade_candidate.get('symbol')}: {e}")
            # Return safe fallback with structure matching the normal return
            # to avoid KeyErrors in consumers
            return {
                "score": 0.0,
                "metrics": {
                    "ev_amount": 0.0,
                    "ev_percent": 0.0,
                    "prob_profit": 0.0,
                    "reward_to_risk": 0.0,
                    "max_profit": 0.0,
                    "max_loss": 0.0
                },
                "penalties": {
                    "liquidity": 1.0,
                    "event_risk": 0.0
                },
                "features_hash": "error",
                "debug": {}
            }

    @staticmethod
    def _calculate_ev_pop(strategy_type, is_credit, max_profit, max_loss, p_short_itm, p_long_itm):
        """
        Calculates EV and POP based on simple probability of ITM for legs.
        This is a simplified payoff model.
        """
        # Default fallback
        ev = 0.0
        pop = 0.5

        # Credit Spread (Short Vertical)
        # Profit if underlying stays OTM (below short call or above short put)
        # Max Loss if underlying goes ITM past long strike
        if is_credit:
            # Approx: POP = 1 - Prob(Short ITM)
            # Actually for spread, it's slightly better, but conservative estimate:
            pop = 1.0 - p_short_itm

            # EV = (MaxProfit * POP) - (MaxLoss * (1 - POP))
            # This ignores the "in-between" strikes area, which is piecewise linear.
            # For a more robust EV, we should integrate.
            # But "Spread/Greeks-aware" implies we might use this discrete approx for now.
            # Refinement: 1 - POP is prob of *some* loss. Full loss prob is p_long_itm.
            # Prob of partial loss is p_short_itm - p_long_itm.

            prob_full_loss = p_long_itm
            prob_full_win = 1.0 - p_short_itm
            prob_partial = p_short_itm - p_long_itm

            avg_partial_loss = max_loss * 0.5 # Linear approx

            ev = (max_profit * prob_full_win) - (max_loss * prob_full_loss) - (avg_partial_loss * prob_partial)

        else:
            # Debit Spread (Long Vertical)
            # Profit if underlying goes ITM past short strike (which is the "higher" strike in call spread)
            # Wait, debit call: Long Low Strike, Short High Strike.
            # Profit if Price > Long Strike. Max Profit if Price > Short Strike.

            # Current inputs: short_strike, long_strike.
            # In a debit call spread, we Buy Long (Low) and Sell Short (High).
            # p_long_itm is prob Low strike is ITM (higher prob).
            # p_short_itm is prob High strike is ITM (lower prob).

            prob_full_win = p_short_itm
            prob_full_loss = 1.0 - p_long_itm
            prob_partial = p_long_itm - p_short_itm

            avg_partial_profit = max_profit * 0.5

            ev = (max_profit * prob_full_win) - (max_loss * prob_full_loss) + (avg_partial_profit * prob_partial)
            pop = p_long_itm # Probability of *some* profit (breakeven is roughly near long strike + debit)

        # Sanity Check EV
        ev_percent = (ev / max_loss * 100) if max_loss > 0 else 0.0

        rr = max_profit / max_loss if max_loss > 0 else 0.0

        return {
            "ev_amount": ev,
            "ev_percent": ev_percent,
            "prob_profit": pop,
            "reward_to_risk": rr
        }

    @staticmethod
    def _calculate_liquidity_penalty(bid, ask, price) -> float:
        if bid <= 0 or ask <= 0:
            return 1.0 # Max penalty (reject)

        spread = ask - bid
        if spread <= 0: return 0.0

        # Relative spread
        if bid == 0: return 1.0
        rel_spread = spread / bid

        # Penalty logic
        # < 1%: 0 penalty
        # 1% - 5%: scaling penalty
        # > 10%: heavy penalty

        if rel_spread < 0.01:
            return 0.0
        elif rel_spread < 0.011: # Tolerance buffer
             return 0.0
        elif rel_spread < 0.05:
            return (rel_spread - 0.01) * 5.0 # Scales 0 to 0.2
        elif rel_spread < 0.10:
            return 0.2 + (rel_spread - 0.05) * 10.0 # Scales 0.2 to 0.7
        else:
            return 0.9 # High penalty
