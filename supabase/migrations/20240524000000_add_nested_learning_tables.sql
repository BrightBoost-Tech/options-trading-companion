-- 1. nested_regimes
create table if not exists nested_regimes (
  id uuid primary key default gen_random_uuid(),
  timestamp timestamptz not null,
  global_regime text,
  market_volatility_state text,
  source text,
  created_at timestamptz default now()
);

-- 2. model_states
create table if not exists model_states (
  id uuid primary key default gen_random_uuid(),
  scope text, -- GLOBAL or ticker
  model_version text,
  weights jsonb,
  last_updated timestamptz,
  cumulative_error float8,
  created_at timestamptz default now()
);

-- 3. inference_log
create table if not exists inference_log (
  trace_id uuid primary key default gen_random_uuid(),
  timestamp timestamptz not null,
  symbol_universe jsonb,
  inputs_snapshot jsonb,
  predicted_mu jsonb,
  predicted_sigma jsonb,
  optimizer_profile text,
  created_at timestamptz default now()
);

-- 4. outcomes_log
create table if not exists outcomes_log (
  trace_id uuid primary key references inference_log(trace_id),
  realized_pl_1d float8,
  realized_vol_1d float8,
  surprise_score float8,
  used_for_training boolean default false,
  created_at timestamptz default now()
);
