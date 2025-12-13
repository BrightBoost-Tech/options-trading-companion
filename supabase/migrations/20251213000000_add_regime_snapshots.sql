create table if not exists regime_snapshots (
  id uuid default gen_random_uuid() primary key,
  as_of_ts timestamptz not null,
  state text not null,
  risk_score float not null,
  risk_scaler float not null,
  components jsonb not null default '{}'::jsonb,
  details jsonb not null default '{}'::jsonb,
  engine_version text not null default 'v3',
  created_at timestamptz not null default now()
);

create index if not exists idx_regime_snapshots_ts on regime_snapshots(as_of_ts desc);

create table if not exists symbol_regime_snapshots (
  id uuid default gen_random_uuid() primary key,
  symbol text not null,
  as_of_ts timestamptz not null,
  state text not null,
  score float not null,
  metrics jsonb not null default '{}'::jsonb,
  quality_flags jsonb not null default '{}'::jsonb,
  engine_version text not null default 'v3',
  created_at timestamptz not null default now()
);

create index if not exists idx_symbol_regime_snapshots_ts on symbol_regime_snapshots(as_of_ts desc);
create index if not exists idx_symbol_regime_snapshots_symbol on symbol_regime_snapshots(symbol);
