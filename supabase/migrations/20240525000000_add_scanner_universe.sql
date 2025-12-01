create table scanner_universe (
  symbol text primary key,
  sector text,
  market_cap bigint,
  avg_volume_30d bigint,
  iv_rank float,
  liquidity_score int,
  earnings_date date,
  is_active boolean default true,
  last_updated timestamptz default now()
);

create index idx_universe_metrics on scanner_universe (is_active, avg_volume_30d, liquidity_score);

alter table scanner_universe enable row level security;

create policy "Allow authenticated read access" on scanner_universe
  for select using (auth.role() = 'authenticated');
