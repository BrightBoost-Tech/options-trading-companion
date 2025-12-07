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
  max_drawdown?: number; // Added optional field
  avg_roi?: number; // Added optional field
  metrics: {
    avg_pnl?: number;
    max_drawdown?: number;
    [key: string]: any;
  };
  status: string;
  batch_id?: string;
  created_at: string; // Made required as it's used in UI
}

export interface StrategyBacktest {
  id: string;
  strategy_name: string;
  version: number;
  param_hash: string | null;
  start_date: string;
  end_date: string;
  ticker: string;
  trades_count: number;
  win_rate: number;
  max_drawdown: number;
  avg_roi: number;
  total_pnl: number;
  status: "pending" | "completed" | "error";
  created_at: string;
}

export interface SuggestionLeg {
  symbol: string;
  quantity: number;
  action?: 'buy' | 'sell';
  strike?: number;
  type?: 'call' | 'put';
  expiry?: string;
  option_symbol?: string; // Added for flexibility
  display_symbol?: string;
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
  type?: string;
  kind?: string;
  window?: string;
  status?: string;
  symbol: string;
  display_symbol?: string;
  ticker?: string;
  direction: string;
  strategy: string;
  expiration?: string;
  rationale?: string;
  historical_stats?: {
    sample_size?: number;
    win_rate?: number;
    avg_pnl?: number;
    [key: string]: any;
  };
  order_json: {
    legs?: SuggestionLeg[];
    max_loss?: number;
    max_profit?: number;
    price?: number;
    limit_price?: number;
    metrics?: SuggestionMetrics;
    context?: {
        iv_rank?: number;
        iv_regime?: string;
        [key: string]: any;
    };
    [key: string]: any; // Catch-all for other order fields
  };
  metrics?: SuggestionMetrics; // Top level metrics convenience
  ev?: number;
  score?: number;
  risk_score?: number;

  // Flattened Context Helpers
  iv_rank?: number;
  iv_regime?: string;
  conviction?: number;
  trace_id?: string;

  // Greeks Impact (Top Level or Derived)
  delta_impact?: number;
  theta_impact?: number;

  timestamp?: string;
  created_at?: string;

  // Frontend state
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

export interface PortfolioSnapshot {
    user_id: string;
    created_at: string;
    buying_power?: number;
    net_liquidity?: number;
    risk_metrics?: RiskMetrics;
    holdings?: any[];
    spreads?: any[];
}
