
from typing import List, Dict, Any, Optional
from packages.quantum.analytics.guardrails import is_earnings_safe, check_liquidity, sector_penalty, apply_slippage_guardrail
from packages.quantum.analytics.scoring import generate_badges
from packages.quantum.analytics.opportunity_scorer import OpportunityScorer
from packages.quantum.analytics.sizing import calculate_contract_size
from supabase import Client

# #62a-D8 (2026-05-10): ExitStatsService import removed alongside the
# dropped trade_executions table. The service always returned
# insufficient_history=True (table had zero rows for entire lifetime);
# the rationale code below always took the "Insufficient history" branch.

def enrich_trade_suggestions(
    trades: List[Dict[str, Any]],
    portfolio_value: float,
    market_data: Dict[str, Any],
    positions: List[Dict[str, Any]],
    supabase_client: Optional[Client] = None
) -> List[Dict[str, Any]]:
    """
    Enriches raw trade suggestions with a safety and selection layer.

    Args:
        trades: A list of raw trade suggestions from the optimizer.
        portfolio_value: The total value of the portfolio.
        market_data: A dictionary containing market data for the symbols in the trades.
        positions: A list of current positions.
        supabase_client: Optional Supabase client for fetching stats.

    Returns:
        A list of enriched trade suggestions with scores, badges, and rationales.
    """
    enriched_trades = []
    for trade in trades:
        symbol = trade.get('symbol') or trade.get('ticker')
        symbol_market_data = market_data.get(symbol, {})

        if not trade.get('strategy_type'):
            trade['strategy_type'] = 'credit'

        # 1. Apply Guardrails
        trade['is_earnings_safe'] = is_earnings_safe(symbol, symbol_market_data)
        trade['is_liquid'] = check_liquidity(symbol, symbol_market_data)
        trade['sector_penalty'] = sector_penalty(symbol, symbol_market_data, positions, portfolio_value)

        # 2. V3 Scoring (Authoritative)
        scored_output = OpportunityScorer.score(trade, symbol_market_data)
        trade['score'] = scored_output['score']
        trade['metrics'] = scored_output['metrics']
        trade['penalties'] = scored_output['penalties']
        trade['features_hash'] = scored_output['features_hash']

        # 2b. Slippage Guardrail (Optional: already in V3 scoring as liquidity_penalty, but kept for hard rejection)
        quote = {
            "bid": symbol_market_data.get("bid", 0.0),
            "ask": symbol_market_data.get("ask", 0.0),
        }
        slippage_mult = apply_slippage_guardrail(trade, quote)

        if slippage_mult == 0.0:
            # Hard reject this trade – skip adding
            continue

        # Note: V3 Score already accounts for liquidity penalty, but slippage_mult might be a hard guardrail.
        # If we keep it, it just reinforces the reject. We shouldn't double penalize the score if V3 already did.
        # But 'apply_slippage_guardrail' returns 0.8 or 1.0.
        # OpportunityScorer returns 0.9 or similar.
        # Let's trust V3 scorer for the score value, but use guardrail for HARD rejection (0.0).

        # 3. Generate Badges
        trade['badges'] = generate_badges(trade, symbol_market_data)

        # 4. Calculate Contract Size
        trade['contracts'] = calculate_contract_size(
            target_dollar_exposure=trade.get('value', 0),
            share_price=symbol_market_data.get('price', trade.get('est_price', 100)),
            option_delta=trade.get('delta', 0.5),
            max_loss_per_contract=trade.get('metrics', {}).get('max_loss', 500),
            portfolio_value=portfolio_value
        )

        # 5. Historical Stats (#62a-D8: ExitStatsService removed; always
        # returned insufficient_history=True from empty trade_executions).
        regime = symbol_market_data.get("iv_regime", "normal")
        trade['stats'] = {
            "win_rate": None,
            "avg_pnl": None,
            "sample_size": 0,
            "regime": regime,
            "insufficient_history": True,
        }

        # 6. Generate Rationale
        rationale_parts = []
        iv_rank_val = trade.get('iv_rank') or symbol_market_data.get('iv_rank')
        if iv_rank_val is not None and iv_rank_val > 50:
            rationale_parts.append(f"High IV Rank ({iv_rank_val:.2f})")
        if trade.get('trend') == "UP":
            rationale_parts.append("Bullish trend")
        if trade['is_earnings_safe']:
            rationale_parts.append("Earnings safe")

        rationale_parts.append("Insufficient history")

        trade['rationale'] = "; ".join(rationale_parts) if rationale_parts else "Neutral outlook"

        enriched_trades.append(trade)

    return enriched_trades
