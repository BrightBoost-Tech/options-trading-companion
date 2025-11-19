"""
Portfolio backtesting using historical data
"""
import numpy as np
from typing import Dict, List
from datetime import datetime, timedelta


def backtest_portfolio(
    weights: Dict[str, float],
    historical_data: List[Dict],
    initial_value: float = 10000
) -> Dict:
    """
    Backtest a portfolio allocation on historical data
    
    Args:
        weights: Dict of {symbol: weight}
        historical_data: List of dicts with 'symbol', 'prices', 'returns', 'dates'
        initial_value: Starting portfolio value
        
    Returns:
        Dict with performance metrics
    """
    
    # Align all data to the same dates
    min_length = min(len(data['returns']) for data in historical_data)
    
    # Calculate portfolio returns
    portfolio_returns = []
    for i in range(min_length):
        daily_return = 0
        for data in historical_data:
            symbol = data['symbol']
            weight = weights.get(symbol, 0)
            daily_return += weight * data['returns'][-(min_length - i)]
        portfolio_returns.append(daily_return)
    
    # Calculate portfolio values over time
    portfolio_values = [initial_value]
    for ret in portfolio_returns:
        portfolio_values.append(portfolio_values[-1] * (1 + ret))
    
    # Calculate metrics
    total_return = (portfolio_values[-1] - initial_value) / initial_value
    
    # Sharpe ratio
    mean_return = np.mean(portfolio_returns)
    std_return = np.std(portfolio_returns)
    sharpe = (mean_return * 252) / (std_return * np.sqrt(252)) if std_return > 0 else 0
    
    # Max drawdown
    peak = portfolio_values[0]
    max_dd = 0
    for value in portfolio_values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak
        if drawdown > max_dd:
            max_dd = drawdown
    
    # Winning days
    winning_days = sum(1 for r in portfolio_returns if r > 0)
    win_rate = winning_days / len(portfolio_returns) if portfolio_returns else 0
    
    # Get dates for the backtest period
    dates = historical_data[0]['dates'][-min_length:]
    
    return {
        'total_return': float(total_return),
        'total_return_pct': float(total_return * 100),
        'sharpe_ratio': float(sharpe),
        'max_drawdown': float(max_dd),
        'max_drawdown_pct': float(max_dd * 100),
        'win_rate': float(win_rate),
        'win_rate_pct': float(win_rate * 100),
        'initial_value': initial_value,
        'final_value': float(portfolio_values[-1]),
        'trading_days': min_length,
        'start_date': dates[0],
        'end_date': dates[-1],
        'daily_returns': portfolio_returns[-30:],  # Last 30 days for charting
        'portfolio_values': [float(v) for v in portfolio_values[-30:]]  # Last 30 days
    }


if __name__ == '__main__':
    # Test
    from market_data import calculate_portfolio_inputs
    
    symbols = ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI']
    
    print("Running backtest...")
    # This is a simplified test - in production, we'd use the actual historical data
    print("Backtest module ready!")
