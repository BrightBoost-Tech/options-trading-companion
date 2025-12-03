export interface StrategyConfig {
  name: string;
  version: number;
  description?: string;
  regime_whitelist?: string[];
  conviction_floor: number;
  conviction_slope: number;
  max_risk_pct_per_trade: number;
  max_risk_pct_portfolio: number;
  max_concurrent_positions: number;
  max_spread_bps: number;
  max_days_to_expiry: number;
  min_underlying_liquidity: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  max_holding_days: number;
}

export interface BacktestRequest {
  start_date: string;
  end_date: string;
  ticker: string;
  param_grid?: Record<string, any[]>;
  strategy_name?: string;
}

export interface BacktestResult {
  id?: string;
  strategy_name: string;
  version: number;
  param_hash: string;
  start_date: string;
  end_date: string;
  ticker: string;
  trades_count: number;
  win_rate: number;
  total_pnl: number;
  metrics: {
    avg_pnl?: number;
    max_drawdown?: number;
    [key: string]: any;
  };
  status: string;
  batch_id?: string;
  created_at?: string;
}

export interface SuggestionLeg {
  symbol: string;
  action: 'buy' | 'sell';
  quantity: number;
  strike: number;
  type: 'call' | 'put';
  expiry: string;
}

export interface SuggestionMetrics {
  ev: number;
  win_rate: number;
  kelly: number;
  max_loss: number;
  max_profit: number;
}

export interface Suggestion {
  id: string;
  type: string;
  symbol: string; // e.g. "SPY"
  strategy: string; // e.g. "Bull Put Spread"
  expiration?: string;
  order_json: {
    legs: SuggestionLeg[];
    max_loss?: number;
    max_profit?: number;
  };
  score?: number;
  metrics?: SuggestionMetrics;

  // New context fields
  iv_rank?: number;
  iv_regime?: string;
  conviction?: number;

  // Risk impact (placeholders or real if backend sends them)
  delta_impact?: number;
  theta_impact?: number;

  timestamp?: string;

  // Frontend state (not from backend)
  staged?: boolean;
}

export interface GreekAlerts {
    delta_over_limit?: boolean;
    theta_over_limit?: boolean;
    gamma_over_limit?: boolean;
    vega_over_limit?: boolean;
}

export interface Greeks {
    delta: number;
    gamma: number;
    vega: number;
    theta: number;
}

export interface RiskMetrics {
    greeks?: Greeks;
    greek_alerts?: GreekAlerts;
    [key: string]: any;
}
