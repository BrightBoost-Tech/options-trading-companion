-- Create table for storing daily 30-day ATM IV points
create table if not exists public.underlying_iv_points (
    id uuid primary key default gen_random_uuid(),
    underlying text not null,
    as_of_date date not null,
    as_of_ts timestamptz not null,
    spot numeric not null,
    iv_30d numeric null,
    iv_30d_method text not null default 'var_interp_spot_atm',

    -- Term structure components used for interpolation
    expiry1 date null,
    expiry2 date null,
    iv1 numeric null,
    iv2 numeric null,
    strike1 numeric null,
    strike2 numeric null,

    source text not null default 'polygon',
    recency text null,
    quality_score int null,
    inputs jsonb null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Unique index to prevent duplicate daily points for an underlying
create unique index if not exists idx_underlying_iv_points_unique
    on public.underlying_iv_points (underlying, as_of_date);

-- Index for efficient querying of recent history
create index if not exists idx_underlying_iv_points_lookup
    on public.underlying_iv_points (underlying, as_of_date desc);

-- Trigger to auto-update updated_at
create or replace function public.handle_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger set_updated_at_underlying_iv_points
    before update on public.underlying_iv_points
    for each row
    execute procedure public.handle_updated_at();

-- RLS Policies (if RLS is enabled globally, good practice to add)
alter table public.underlying_iv_points enable row level security;

create policy "Allow read access to all users"
    on public.underlying_iv_points for select
    using (true);

create policy "Allow service role full access"
    on public.underlying_iv_points for all
    using (true)
    with check (true);
