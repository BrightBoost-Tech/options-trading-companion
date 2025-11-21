
-- Migration to add snaptrade_users table
-- This table stores the mapping between our internal user_id and SnapTrade's user_id/secret.

create table if not exists public.snaptrade_users (
    user_id uuid references auth.users(id) on delete cascade primary key,
    snaptrade_user_id text not null,
    snaptrade_user_secret text not null,
    created_at timestamptz default now()
);

-- RLS Policies (if RLS is enabled, which is best practice)
alter table public.snaptrade_users enable row level security;

create policy "Users can view their own SnapTrade credentials"
    on public.snaptrade_users for select
    using (auth.uid() = user_id);

create policy "Users can insert their own SnapTrade credentials"
    on public.snaptrade_users for insert
    with check (auth.uid() = user_id);

-- Add comment
comment on table public.snaptrade_users is 'Stores SnapTrade user credentials for each app user.';
