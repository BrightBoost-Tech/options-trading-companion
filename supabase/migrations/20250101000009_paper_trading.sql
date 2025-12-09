-- Migration for Paper Trading support

-- 1. paper_portfolios
create table if not exists paper_portfolios (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users(id) on delete cascade not null,
  name text default 'Main Paper' not null,
  cash_balance numeric not null default 100000.0,
  net_liq numeric not null default 100000.0,
  created_at timestamptz default now() not null,
  updated_at timestamptz default now() not null
);

-- 2. paper_orders
create table if not exists paper_orders (
  id uuid default gen_random_uuid() primary key,
  portfolio_id uuid references paper_portfolios(id) on delete cascade not null,
  status text not null, -- 'filled', 'open', 'cancelled'
  order_json jsonb not null default '{}'::jsonb, -- stores the full TradeTicket
  filled_at timestamptz default now(),
  created_at timestamptz default now() not null
);

-- 3. paper_positions
create table if not exists paper_positions (
  id uuid default gen_random_uuid() primary key,
  portfolio_id uuid references paper_portfolios(id) on delete cascade not null,
  strategy_key text not null, -- e.g. "SPY_iron_condor" to group legs
  symbol text not null,
  quantity numeric not null default 0,
  avg_entry_price numeric not null default 0,
  current_mark numeric, -- last known price
  unrealized_pl numeric default 0,
  created_at timestamptz default now() not null,
  updated_at timestamptz default now() not null,
  unique(portfolio_id, strategy_key)
);

-- 4. paper_ledger
create table if not exists paper_ledger (
  id uuid default gen_random_uuid() primary key,
  portfolio_id uuid references paper_portfolios(id) on delete cascade not null,
  amount numeric not null, -- negative for debit, positive for credit
  balance_after numeric not null,
  description text,
  created_at timestamptz default now() not null
);

-- RLS Policies (basic owner access)
alter table paper_portfolios enable row level security;
alter table paper_orders enable row level security;
alter table paper_positions enable row level security;
alter table paper_ledger enable row level security;

create policy "Users can view own paper portfolios" on paper_portfolios
  for select using (auth.uid() = user_id);
create policy "Users can update own paper portfolios" on paper_portfolios
  for update using (auth.uid() = user_id);
create policy "Users can insert own paper portfolios" on paper_portfolios
  for insert with check (auth.uid() = user_id);

create policy "Users can view own paper orders" on paper_orders
  for select using (
    exists (select 1 from paper_portfolios p where p.id = paper_orders.portfolio_id and p.user_id = auth.uid())
  );
create policy "Users can insert own paper orders" on paper_orders
  for insert with check (
    exists (select 1 from paper_portfolios p where p.id = paper_orders.portfolio_id and p.user_id = auth.uid())
  );

create policy "Users can view own paper positions" on paper_positions
  for select using (
    exists (select 1 from paper_portfolios p where p.id = paper_positions.portfolio_id and p.user_id = auth.uid())
  );
create policy "Users can update own paper positions" on paper_positions
  for update using (
    exists (select 1 from paper_portfolios p where p.id = paper_positions.portfolio_id and p.user_id = auth.uid())
  );
create policy "Users can insert own paper positions" on paper_positions
  for insert with check (
    exists (select 1 from paper_portfolios p where p.id = paper_positions.portfolio_id and p.user_id = auth.uid())
  );
create policy "Users can delete own paper positions" on paper_positions
  for delete using (
    exists (select 1 from paper_portfolios p where p.id = paper_positions.portfolio_id and p.user_id = auth.uid())
  );

create policy "Users can view own paper ledger" on paper_ledger
  for select using (
    exists (select 1 from paper_portfolios p where p.id = paper_ledger.portfolio_id and p.user_id = auth.uid())
  );
create policy "Users can insert own paper ledger" on paper_ledger
  for insert with check (
    exists (select 1 from paper_portfolios p where p.id = paper_ledger.portfolio_id and p.user_id = auth.uid())
  );
