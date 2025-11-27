
from typing import List, Dict, Any
from analytics.guardrails import is_earnings_safe, check_liquidity, sector_penalty
from analytics.scoring import calculate_otc_score, generate_badges
from analytics.sizing import calculate_contract_size

def enrich_trade_suggestions(
    trades: List[Dict[str, Any]],
    portfolio_value: float,
    market_data: Dict[str, Any],
    positions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Enriches raw trade suggestions with a safety and selection layer.

    Args:
        trades: A list of raw trade suggestions from the optimizer.
        portfolio_value: The total value of the portfolio.
        market_data: A dictionary containing market data for the symbols in the trades.

    Returns:
        A list of enriched trade suggestions with scores, badges, and rationales.
    """
    enriched_trades = []
    for trade in trades:
        symbol = trade['symbol']
        symbol_market_data = market_data.get(symbol, {})

        trade['strategy_type'] = 'credit'
        # 1. Apply Guardrails
        trade['is_earnings_safe'] = is_earnings_safe(symbol, symbol_market_data)
        trade['is_liquid'] = check_liquidity(symbol, symbol_market_data)
        trade['sector_penalty'] = sector_penalty(symbol, symbol_market_data, positions, portfolio_value)

        # 2. Calculate OTC Score
        trade['score'] = calculate_otc_score(trade, symbol_market_data)

        # 3. Generate Badges
        trade['badges'] = generate_badges(trade, symbol_market_data)

        # 4. Calculate Contract Size
        trade['contracts'] = calculate_contract_size(
            target_dollar_exposure=trade['value'],
            share_price=symbol_market_data.get('price', trade.get('est_price', 100)),
            option_delta=trade.get('delta', 0.5),
            max_loss_per_contract=trade.get('max_loss', 500),
            portfolio_value=portfolio_value
        )

        # 5. Generate Rationale
        rationale_parts = []
        if trade.get('iv_rank', 0) > 0.5:
            rationale_parts.append(f"High IV Rank ({trade.get('iv_rank', 0):.2f})")
        if trade.get('trend') == "UP":
            rationale_parts.append("Bullish trend")
        if trade['is_earnings_safe']:
            rationale_parts.append("Earnings safe")
        trade['rationale'] = "; ".join(rationale_parts) if rationale_parts else "Neutral outlook"


        enriched_trades.append(trade)

    return enriched_trades
