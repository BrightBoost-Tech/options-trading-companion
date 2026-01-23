
import math
import hashlib
import json
import logging
from typing import Dict, Any, Optional, List
import numpy as np
from scipy.stats import norm
from packages.quantum.services.replay.canonical import compute_content_hash

logger = logging.getLogger(__name__)

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
                premium = float(trade_candidate.get('debit') or trade_candidate.get('cost') or 0.0)
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
                try:
                    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
                    return norm.cdf(d2)
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
            iv_rank = float(market_ctx.get('iv_rank') or 0.0)
            iv_bonus = 0.0
            if is_credit and iv_rank > 50:
                iv_bonus = (iv_rank - 50) * 0.2 # Max 10 pts
            elif not is_credit and iv_rank < 50:
                 iv_bonus = (50 - iv_rank) * 0.2 # Max 10 pts

            raw_score = ev_score + pop_score + iv_bonus

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
                    "prob_short_itm": round(prob_short_itm, 4)
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
