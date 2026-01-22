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
  vega_impact?: number;

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

  // PR4: Market Data Quality Gate Fields
  blocked_reason?: string;  // e.g., "marketdata_quality_gate"
  blocked_detail?: string;  // e.g., "SPY:WARN_STALE|QQQ:FAIL_CROSSED"
  marketdata_quality?: {
    event?: string;
    policy?: string;
    effective_action?: string;  // "skip_fatal" | "skip_policy" | "defer" | "downrank" | "downrank_fallback_to_defer"
    warning_count?: number;
    fatal_count?: number;
    has_warning?: boolean;
    has_fatal?: boolean;
    symbols?: Array<{
      symbol: string;
      code: string;  // "OK" | "WARN_STALE" | "WARN_WIDE_SPREAD" | "FAIL_CROSSED" | etc.
      score?: number | null;
      freshness_ms?: number | null;
    }>;
    downrank_applied?: boolean;
    warn_penalty?: number;
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
  include_backlog?: boolean;  // PR4.1: indicates if backlog mode is active
}

export interface InboxResponse {
  // v4: New explicit buckets
  active_executable?: Suggestion[];
  active_blocked?: Suggestion[];
  staged_today?: Suggestion[];
  completed_today?: Suggestion[];
  // Legacy fields (backwards compat)
  hero: Suggestion | null;
  queue: Suggestion[];
  completed: Suggestion[];
  meta: InboxMeta;
}

// v4: Trace response for Details Drawer
export interface TraceIntegrity {
  stored_hash: string;
  computed_hash: string;
  signature_valid: boolean;
}

export interface TraceAttribution {
  drivers_agents?: Array<{ agent: string; signal: string; weight?: number }>;
  drivers_regime?: { regime: string; context?: string };
  vetoes?: Array<{ agent: string; reason: string }>;
  [key: string]: any;
}

export interface TraceAuditEvent {
  event: string;
  timestamp: string;
  verification?: {
    status: string;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface TraceResponse {
  status: 'VERIFIED' | 'TAMPERED' | 'UNVERIFIED';
  trace_id: string;
  integrity: TraceIntegrity;
  lifecycle: {
    suggestion: Suggestion;
    audit_log: TraceAuditEvent[];
    attribution: TraceAttribution | null;
  };
}

// --- Discrete Optimizer Types ---

export interface CandidateTrade {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty_max: number;
  ev_per_unit: number;
  premium_per_unit: number;
  delta: number;
  gamma: number;
  vega: number;
  tail_risk_contribution: number;
  metadata?: Record<string, any>;
}

export interface DiscreteConstraints {
  max_cash: number;
  max_vega: number;
  max_delta_abs: number;
  target_delta?: number;
  max_gamma: number;
  max_contracts?: number;
}

export interface DiscreteParameters {
  lambda_tail: number;
  lambda_cash: number;
  lambda_vega: number;
  lambda_delta: number;
  lambda_gamma: number;
  num_samples: number;
  relaxation_schedule?: number;
  mode: 'hybrid' | 'classical_only' | 'quantum_only';
  trial_mode?: boolean;
  max_candidates_for_dirac: number;
  max_dirac_calls: number;
  dirac_timeout_s: number;
}

export interface DiscreteSolveRequest {
  candidates: CandidateTrade[];
  constraints: DiscreteConstraints;
  parameters: DiscreteParameters;
}

export interface SelectedTrade {
  id: string;
  qty: number;
  reason: string;
}

export interface DiscreteSolveMetrics {
  expected_profit: number;
  total_premium: number;
  tail_risk_value: number;
  delta: number;
  gamma: number;
  vega: number;
  objective_value: number;
  runtime_ms: number;
}

export interface DiscreteSolveResponse {
  status: string;
  strategy_used: 'dirac3' | 'classical';
  selected_trades: SelectedTrade[];
  metrics: DiscreteSolveMetrics;
  diagnostics: Record<string, any>;
}

// --- PR C: Ops Console Types ---

export interface OpsControlState {
  mode: string;  // "paper" | "micro_live" | "live"
  paused: boolean;
  pause_reason?: string | null;
  updated_at: string;
}

export interface FreshnessItem {
  symbol: string;
  freshness_ms: number | null;
  status: string;  // "OK" | "WARN" | "STALE" | "ERROR"
  score: number | null;
  issues: string[] | null;
}

export interface PipelineJobState {
  status: string;
  created_at: string | null;
  finished_at: string | null;
}

export interface HealthBlock {
  status: string;  // "healthy" | "degraded" | "unhealthy" | "paused"
  issues: string[];
  checks: Record<string, string>;
}

export interface OpsDashboardState {
  control: OpsControlState;
  freshness: FreshnessItem[];
  pipeline: Record<string, PipelineJobState>;
  health: HealthBlock;
}

// --- GET /ops/health Response Types ---

export interface OpsDataFreshness {
  is_stale: boolean;
  stale_reason?: string | null;
  as_of?: string | null;
  age_seconds?: number | null;
  source: string;  // "job_runs" | "trade_suggestions" | "none"
}

export interface OpsExpectedJob {
  name: string;
  cadence: string;  // "daily" | "weekly"
  last_success_at?: string | null;
  status: string;  // "ok" | "late" | "never_run" | "error"
}

export interface OpsJobsStatus {
  expected: OpsExpectedJob[];
  recent_failures: Array<Record<string, any>>;
}

export interface OpsIntegrity {
  recent_incidents: number;
  last_incident_at?: string | null;
}

export interface OpsSuggestionsStats {
  last_cycle_date?: string | null;
  count_last_cycle: number;
}

export interface OpsHealthResponse {
  now: string;
  paused: boolean;
  pause_reason?: string | null;
  data_freshness: OpsDataFreshness;
  jobs: OpsJobsStatus;
  integrity: OpsIntegrity;
  suggestions: OpsSuggestionsStats;
}
