-- Suggestion Logs
create table suggestion_logs (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users not null,
  created_at timestamptz default now(),

  regime_context jsonb not null,

  symbol text not null,
  strategy_type text not null,
  direction text not null,

  target_price numeric not null,
  stop_loss numeric,
  confidence_score numeric not null,

  was_accepted boolean default false,
  trade_execution_id uuid
);

-- Trade Executions
create table trade_executions (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users not null,
  timestamp timestamptz default now(),

  symbol text not null,
  fill_price numeric not null,
  quantity integer not null,
  fees numeric default 0.0,

  suggestion_id uuid references suggestion_logs(id),

  realized_pnl numeric,
  exit_timestamp timestamptz
);

-- Weekly Snapshots
create table weekly_snapshots (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users not null,
  week_id text not null, -- "2025-W48"

  date_start timestamptz not null,
  date_end timestamptz not null,

  dominant_regime text,
  avg_ivr numeric,

  user_metrics jsonb not null,
  system_metrics jsonb not null,
  synthesis jsonb not null,

  created_at timestamptz default now(),

  unique(user_id, week_id)
);

-- Add foreign key back link for suggestion_logs -> trade_executions
alter table suggestion_logs
  add constraint fk_suggestion_execution
  foreign key (trade_execution_id)
  references trade_executions(id);

-- RLS Policies
alter table suggestion_logs enable row level security;
alter table trade_executions enable row level security;
alter table weekly_snapshots enable row level security;

create policy "Users can view own suggestion logs" on suggestion_logs
  for select using (auth.uid() = user_id);

create policy "Users can insert own suggestion logs" on suggestion_logs
  for insert with check (auth.uid() = user_id);

create policy "Users can update own suggestion logs" on suggestion_logs
  for update using (auth.uid() = user_id);

create policy "Users can view own trade executions" on trade_executions
  for select using (auth.uid() = user_id);

create policy "Users can insert own trade executions" on trade_executions
  for insert with check (auth.uid() = user_id);

create policy "Users can update own trade executions" on trade_executions
  for update using (auth.uid() = user_id);

create policy "Users can view own weekly snapshots" on weekly_snapshots
  for select using (auth.uid() = user_id);

create policy "Users can insert own weekly snapshots" on weekly_snapshots
  for insert with check (auth.uid() = user_id);

create policy "Users can update own weekly snapshots" on weekly_snapshots
  for update using (auth.uid() = user_id);
