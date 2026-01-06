-- v3_go_live_validation.sql

-- 1. Table: v3_go_live_state
create table if not exists v3_go_live_state (
    user_id uuid primary key references auth.users(id),
    paper_window_start timestamptz not null,
    paper_window_end timestamptz not null,
    paper_baseline_capital numeric not null default 100000,
    paper_consecutive_passes int not null default 0,
    paper_ready boolean not null default false,
    historical_last_run_at timestamptz null,
    historical_last_result jsonb not null default '{}'::jsonb,
    overall_ready boolean not null default false,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- 2. Table: v3_go_live_runs
create table if not exists v3_go_live_runs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id),
    mode text not null, -- 'paper'|'historical'|'consolidated'
    window_start timestamptz,
    window_end timestamptz,
    return_pct numeric,
    pnl_total numeric,
    segment_pnls jsonb default '{}'::jsonb,
    passed boolean not null,
    fail_reason text null,
    details_json jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);

-- 3. Table: v3_go_live_journal
create table if not exists v3_go_live_journal (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id),
    window_start timestamptz,
    window_end timestamptz,
    title text not null,
    summary text not null,
    details_json jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);

-- 4. Enable RLS
alter table v3_go_live_state enable row level security;
alter table v3_go_live_runs enable row level security;
alter table v3_go_live_journal enable row level security;

-- Policies for v3_go_live_state
create policy "Users can view their own state"
    on v3_go_live_state for select
    using (auth.uid() = user_id);

create policy "Users can insert their own state"
    on v3_go_live_state for insert
    with check (auth.uid() = user_id);

create policy "Users can update their own state"
    on v3_go_live_state for update
    using (auth.uid() = user_id);

-- Policies for v3_go_live_runs
create policy "Users can view their own runs"
    on v3_go_live_runs for select
    using (auth.uid() = user_id);

create policy "Users can insert their own runs"
    on v3_go_live_runs for insert
    with check (auth.uid() = user_id);

-- Policies for v3_go_live_journal
create policy "Users can view their own journal"
    on v3_go_live_journal for select
    using (auth.uid() = user_id);

create policy "Users can insert their own journal"
    on v3_go_live_journal for insert
    with check (auth.uid() = user_id);
