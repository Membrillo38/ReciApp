-- Additive security hardening. No public API columns or endpoint contracts change.

alter table public.api_request_logs
  add column if not exists correlation_id text;

create unique index if not exists extract_jobs_active_norm_unique
  on public.extract_jobs (source_url_norm)
  where status in ('pending', 'processing');

alter table public.profiles
  add column if not exists subscription_event_at timestamptz,
  add column if not exists subscription_event_id text,
  add column if not exists subscription_product_id text,
  add column if not exists subscription_currency text,
  add column if not exists subscription_price_cents numeric(12, 4),
  add column if not exists subscription_proceeds_cents numeric(12, 4);

alter table public.usage_events alter column user_id drop not null;
alter table public.usage_events drop constraint if exists usage_events_user_id_fkey;
alter table public.usage_events
  add constraint usage_events_user_id_fkey foreign key (user_id)
  references public.profiles (id) on delete set null;

create table if not exists public.subscription_events (
  event_id text primary key,
  event_name text not null,
  event_at timestamptz not null,
  user_id uuid references public.profiles (id) on delete set null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'received' check (status in ('received', 'processed', 'skipped', 'failed')),
  error text,
  received_at timestamptz not null default now(),
  processed_at timestamptz
);

create index if not exists subscription_events_user_idx
  on public.subscription_events (user_id, event_at desc);

create table if not exists public.api_spend_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  job_id uuid not null unique references public.extract_jobs (id) on delete cascade,
  reserved_cents numeric(12, 4) not null check (reserved_cents >= 0),
  actual_cents numeric(12, 4) not null default 0 check (actual_cents >= 0),
  status text not null default 'reserved' check (status in ('reserved', 'settled', 'failed')),
  created_at timestamptz not null default now(),
  settled_at timestamptz
);

alter table public.api_spend_ledger alter column user_id drop not null;
alter table public.api_spend_ledger drop constraint if exists api_spend_ledger_user_id_fkey;
alter table public.api_spend_ledger
  add constraint api_spend_ledger_user_id_fkey foreign key (user_id)
  references public.profiles (id) on delete set null;

create index if not exists api_spend_ledger_user_created_idx
  on public.api_spend_ledger (user_id, created_at desc);

create table if not exists public.security_events (
  id uuid primary key default gen_random_uuid(),
  event text not null,
  user_id uuid references public.profiles (id) on delete set null,
  ip text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.spend_alerts (
  period_start date not null,
  scope text not null check (scope in ('daily', 'monthly')),
  threshold integer not null check (threshold in (50, 75, 90, 100)),
  created_at timestamptz not null default now(),
  primary key (period_start, scope, threshold)
);

create table if not exists public.extract_job_access (
  job_id uuid not null references public.extract_jobs (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (job_id, user_id)
);

create index if not exists extract_job_access_user_idx
  on public.extract_job_access (user_id, created_at desc);

create index if not exists security_events_created_idx
  on public.security_events (created_at desc);

create table if not exists public.apple_notification_events (
  event_id text primary key,
  notification_type text,
  signed_payload_sha256 text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'received' check (status in ('received', 'processed', 'skipped', 'failed')),
  created_at timestamptz not null default now()
);

alter table public.subscription_events enable row level security;
alter table public.api_spend_ledger enable row level security;
alter table public.security_events enable row level security;
alter table public.spend_alerts enable row level security;
alter table public.apple_notification_events enable row level security;
alter table public.extract_job_access enable row level security;

revoke all on public.subscription_events from anon, authenticated;
revoke all on public.api_spend_ledger from anon, authenticated;
revoke all on public.security_events from anon, authenticated;
revoke all on public.spend_alerts from anon, authenticated;
revoke all on public.apple_notification_events from anon, authenticated;
revoke all on public.extract_job_access from anon, authenticated;
revoke all on public.api_request_logs from anon, authenticated;

drop policy if exists extract_jobs_select_own on public.extract_jobs;
create policy extract_jobs_select_own on public.extract_jobs
  for select using (auth.uid() = user_id);

drop policy if exists extract_job_access_select_own on public.extract_job_access;
create policy extract_job_access_select_own on public.extract_job_access
  for select using (auth.uid() = user_id);

drop policy if exists user_recipes_insert_own on public.user_recipes;
create policy user_recipes_insert_own on public.user_recipes
  for insert with check (auth.uid() = user_id);

-- The server calls these functions with the service_role only. The functions
-- serialize reservations so concurrent requests cannot overspend a budget.
create or replace function public.reserve_api_spend(
  p_user_id uuid,
  p_job_id uuid,
  p_reserved_cents numeric,
  p_daily_budget_cents numeric,
  p_monthly_budget_cents numeric,
  p_user_monthly_budget_cents numeric
)
returns table(allowed boolean, reason text, reservation_id uuid, reserved_cents numeric)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_daily numeric;
  v_monthly numeric;
  v_user_monthly numeric;
  v_id uuid;
  v_threshold integer;
begin
  update public.api_spend_ledger
     set status = 'failed', settled_at = now()
   where status = 'reserved'
     and created_at < now() - interval '2 hours';

  if p_reserved_cents <= 0 then
    return query select false, 'invalid_reservation', null::uuid, 0::numeric;
    return;
  end if;

  perform pg_advisory_xact_lock(hashtextextended('reciapp-api-spend', 0));

  if exists (select 1 from public.api_spend_ledger where job_id = p_job_id) then
    select id into v_id from public.api_spend_ledger where job_id = p_job_id;
    return query select true, 'already_reserved', v_id, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when status = 'reserved' then reserved_cents else actual_cents end), 0)
    into v_daily
    from public.api_spend_ledger
   where created_at >= date_trunc('day', now());
  if v_daily + p_reserved_cents > p_daily_budget_cents then
    return query select false, 'daily_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when status = 'reserved' then reserved_cents else actual_cents end), 0)
    into v_monthly
    from public.api_spend_ledger
   where created_at >= date_trunc('month', now());
  if v_monthly + p_reserved_cents > p_monthly_budget_cents then
    return query select false, 'monthly_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when status = 'reserved' then reserved_cents else actual_cents end), 0)
    into v_user_monthly
    from public.api_spend_ledger
   where user_id = p_user_id and created_at >= date_trunc('month', now());
  if v_user_monthly + p_reserved_cents > p_user_monthly_budget_cents then
    return query select false, 'user_monthly_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  insert into public.api_spend_ledger (user_id, job_id, reserved_cents)
  values (p_user_id, p_job_id, p_reserved_cents)
  returning id into v_id;

  v_daily := v_daily + p_reserved_cents;
  v_monthly := v_monthly + p_reserved_cents;
  foreach v_threshold in array ARRAY[50, 75, 90, 100] loop
    if p_daily_budget_cents > 0 and v_daily >= p_daily_budget_cents * v_threshold / 100 then
      insert into public.spend_alerts (period_start, scope, threshold)
      values (current_date, 'daily', v_threshold) on conflict do nothing;
    end if;
    if p_monthly_budget_cents > 0 and v_monthly >= p_monthly_budget_cents * v_threshold / 100 then
      insert into public.spend_alerts (period_start, scope, threshold)
      values (date_trunc('month', now())::date, 'monthly', v_threshold) on conflict do nothing;
    end if;
  end loop;
  return query select true, 'reserved', v_id, p_reserved_cents;
end;
$$;

create or replace function public.settle_api_spend(
  p_job_id uuid,
  p_actual_cents numeric,
  p_status text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.api_spend_ledger
     set actual_cents = greatest(coalesce(p_actual_cents, 0), 0),
         status = case when p_status in ('settled', 'failed') then p_status else 'failed' end,
         settled_at = now()
   where job_id = p_job_id and status = 'reserved';
end;
$$;

revoke all on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) from public, anon, authenticated;
revoke all on function public.settle_api_spend(uuid, numeric, text) from public, anon, authenticated;
grant execute on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) to service_role;
grant execute on function public.settle_api_spend(uuid, numeric, text) to service_role;

create or replace function public.purge_expired_data()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.recipes
     set raw_transcript = null
   where raw_transcript is not null
     and created_at < now() - interval '30 days';
  delete from public.api_request_logs where created_at < now() - interval '14 days';
  delete from public.security_events where created_at < now() - interval '90 days';
end;
$$;

revoke all on function public.purge_expired_data() from public, anon, authenticated;
grant execute on function public.purge_expired_data() to service_role;

revoke all on function public.handle_new_user() from public, anon, authenticated;
revoke all on function public.set_updated_at() from public, anon, authenticated;
