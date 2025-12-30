export interface StrategyConfig {
  name: string;
  version: number;
  description?: string;
  // Parameters object to hold loose key-values for the editor
  parameters?: Record<string, any>;
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
  is_active?: boolean;
  user_id?: string;
  updated_at?: string;
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
  sharpe_ratio?: number; // Added for new TradeInbox compatibility
  trade_count?: number; // Added for new TradeInbox compatibility
  config_snapshot?: Record<string, any>; // Added for new TradeInbox compatibility
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
  return_on_risk?: number; // Added for Inbox
}

export interface Suggestion {
  id: string;
  user_id?: string;
  type?: string;
  kind?: string;
  window?: string;
  status?: string;
  symbol: string;
  display_symbol?: string;
  ticker?: string;
  direction?: string;
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
    quantity?: number; // Added for Inbox
    order_type?: string; // Added for Inbox
    [key: string]: any; // Catch-all for other order fields
  };
  metrics?: SuggestionMetrics; // Top level metrics convenience
  ev?: number;
  score?: number;
  risk_score?: number;

  sizing_metadata?: {
    capital_required?: number;
    max_loss_total?: number;
    risk_multiplier?: number;
    clamped_by?: string;
    clamp_reason?: string;
    dismiss?: {
        reason: string;
        dismissed_at: string;
    };
  };

  // Flattened Context Helpers
  iv_rank?: number;
  iv_regime?: string;
  conviction?: number;
  trace_id?: string;
  confidence?: number; // Added for Inbox

  // Greeks Impact (Top Level or Derived)
  delta_impact?: number;
  theta_impact?: number;

  timestamp?: string;
  created_at?: string;
  updated_at?: string; // Added for Inbox

  // Frontend state
  staged?: boolean;
  is_stale?: boolean; // Derived from createdAt vs stale threshold
  refreshed_at?: string; // Updated locally or from backend

  // Agent / AI Meta (Inbox v3)
  agent_summary?: {
    overall_score: number;
    decision: string;
    top_reasons: string[];
    vetoed?: boolean;
  };
}

export interface BatchStageRequest {
    suggestion_ids: string[];
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

export interface JobRun {
  id: string;
  job_name: string;
  idempotency_key?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'dead_lettered' | 'failed_retryable';
  attempt_count: number;
  max_attempts: number;
  scheduled_for: string;
  run_after: string;
  started_at?: string;
  finished_at?: string;
  duration_ms?: number;
  payload?: any;
  result?: any;
  error?: any;
  created_at: string;
}

export interface JobFilters {
    status?: string;
    job_name?: string;
}

export interface Position {
  symbol: string;
  quantity: number;
  current_price: number;
  cost_basis: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  asset_type: string; // "equity", "option", "crypto"
  updated_at?: string;
  // Greeks
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  iv?: number;
  pnl_severity?: 'critical' | 'warning' | 'success'; // Frontend styling helper
}

// --- Inbox v3 Types ---

export interface InboxMeta {
  total_ev_available: number;
  deployable_capital: number;
  stale_after_seconds: number;
}

export interface InboxResponse {
  hero: Suggestion | null;
  queue: Suggestion[];
  completed: Suggestion[];
  meta: InboxMeta;
}
