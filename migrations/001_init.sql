-- ReciApp self-hosted PostgreSQL bootstrap schema.
-- This file consolidates the useful public objects from the legacy Supabase migrations.

create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key default gen_random_uuid(),
  email text unique,
  apple_sub text unique,
  display_name text,
  is_pro boolean not null default false,
  pro_expires_at timestamptz,
  subscription_event_at timestamptz,
  subscription_event_id text,
  subscription_product_id text,
  subscription_currency text,
  subscription_price_cents numeric(12, 4),
  subscription_proceeds_cents numeric(12, 4),
  free_weekly_limit integer,
  pro_monthly_price_cents integer,
  pro_margin_ratio numeric(5, 4),
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.recipes (
  id uuid primary key default gen_random_uuid(),
  source_url_raw text not null,
  source_url_norm text not null unique,
  language_code text not null default 'en-US',
  platform text not null,
  title text not null,
  description text,
  author text,
  thumbnail_url text,
  carousel_image_urls jsonb not null default '[]'::jsonb,
  ingredients jsonb not null default '[]'::jsonb,
  ingredient_sections jsonb not null default '[]'::jsonb,
  steps jsonb not null default '[]'::jsonb,
  servings integer,
  prep_minutes integer,
  cook_minutes integer,
  tags jsonb not null default '[]'::jsonb,
  confidence double precision not null default 0.5,
  missing_fields jsonb not null default '[]'::jsonb,
  raw_transcript text,
  tips jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint recipes_carousel_image_urls_array_check check (
    jsonb_typeof(carousel_image_urls) = 'array'
    and jsonb_array_length(
      case
        when jsonb_typeof(carousel_image_urls) = 'array' then carousel_image_urls
        else '[]'::jsonb
      end
    ) <= 12
  )
);

create table public.user_recipes (
  user_id uuid not null references public.profiles (id) on delete cascade,
  recipe_id uuid not null references public.recipes (id) on delete cascade,
  saved_at timestamptz not null default now(),
  primary key (user_id, recipe_id)
);

create table public.extract_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles (id) on delete set null,
  status text not null default 'pending',
  source_url_raw text not null,
  source_url_norm text not null,
  language_code text not null default 'en-US',
  job_kind text not null default 'extract',
  recipe_id uuid references public.recipes (id) on delete set null,
  cache_hit boolean not null default false,
  cost_cents numeric(12, 4) not null default 0,
  error text,
  progress integer not null default 0,
  attempt_count integer not null default 0,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint extract_jobs_progress_check check (progress >= 0 and progress <= 100),
  constraint extract_jobs_job_kind_check check (job_kind in ('extract', 'translation')),
  constraint extract_jobs_attempt_count_check check (attempt_count >= 0 and attempt_count <= 5)
);

create table public.usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles (id) on delete set null,
  kind text not null check (kind in ('extract_hit', 'extract_miss')),
  cost_cents numeric(12, 4) not null default 0,
  recipe_id uuid references public.recipes (id) on delete set null,
  job_id uuid references public.extract_jobs (id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.api_request_logs (
  id uuid primary key default gen_random_uuid(),
  method text not null,
  path text not null,
  status_code integer not null,
  duration_ms integer not null default 0,
  user_id uuid,
  ip text,
  correlation_id text,
  created_at timestamptz not null default now()
);

create table public.app_settings (
  id integer primary key default 1 check (id = 1),
  free_weekly_limit integer not null default 10,
  pro_margin_ratio numeric(5, 4) not null default 0.20,
  default_pro_monthly_price_cents integer not null default 499,
  updated_at timestamptz not null default now()
);

create table public.subscription_events (
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

create table public.api_spend_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles (id) on delete set null,
  job_id uuid not null unique references public.extract_jobs (id) on delete cascade,
  reserved_cents numeric(12, 4) not null check (reserved_cents >= 0),
  actual_cents numeric(12, 4) not null default 0 check (actual_cents >= 0),
  status text not null default 'reserved' check (status in ('reserved', 'settled', 'failed')),
  created_at timestamptz not null default now(),
  settled_at timestamptz
);

create table public.security_events (
  id uuid primary key default gen_random_uuid(),
  event text not null,
  user_id uuid references public.profiles (id) on delete set null,
  ip text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.spend_alerts (
  period_start date not null,
  scope text not null check (scope in ('daily', 'monthly')),
  threshold integer not null check (threshold in (50, 75, 90, 100)),
  created_at timestamptz not null default now(),
  primary key (period_start, scope, threshold)
);

create table public.extract_job_access (
  job_id uuid not null references public.extract_jobs (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (job_id, user_id)
);

create table public.apple_notification_events (
  event_id text primary key,
  notification_type text,
  signed_payload_sha256 text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'received' check (status in ('received', 'processed', 'skipped', 'failed')),
  created_at timestamptz not null default now()
);

create table public.recipe_translations (
  recipe_id uuid not null references public.recipes (id) on delete cascade,
  language_code text not null check (language_code in (
    'ar', 'bn', 'ca', 'zh-Hans', 'zh-Hant', 'hr', 'cs', 'da', 'nl',
    'en-AU', 'en-CA', 'en-GB', 'en-US', 'fi', 'fr-FR', 'fr-CA', 'de', 'el',
    'gu', 'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'ms', 'ml', 'mr',
    'nb', 'or', 'pl', 'pt-BR', 'pt-PT', 'pa', 'ro', 'ru', 'sk', 'sl',
    'es-MX', 'es-ES', 'sv', 'ta', 'te', 'th', 'tr', 'uk', 'ur', 'vi'
  )),
  payload jsonb not null default '{}'::jsonb,
  source_fingerprint text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (recipe_id, language_code)
);

create table public.auth_refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  user_agent text,
  ip_hash text
);

create index profiles_is_pro_idx on public.profiles (is_pro) where deleted_at is null;
create index recipes_platform_idx on public.recipes (platform);
create index user_recipes_user_idx on public.user_recipes (user_id, saved_at desc);
create index user_recipes_recipe_idx on public.user_recipes (recipe_id);
create index extract_jobs_user_idx on public.extract_jobs (user_id, created_at desc);
create unique index extract_jobs_active_extract_norm_unique
  on public.extract_jobs (source_url_norm)
  where status in ('pending', 'processing') and job_kind = 'extract';
create unique index extract_jobs_active_translation_unique
  on public.extract_jobs (recipe_id, language_code)
  where status in ('pending', 'processing') and job_kind = 'translation';
create index extract_jobs_claim_idx
  on public.extract_jobs (status, lease_until, created_at)
  where status in ('pending', 'processing');
create index usage_events_user_week_idx on public.usage_events (user_id, created_at desc);
create index usage_events_job_idx on public.usage_events (job_id);
create index usage_events_recipe_idx on public.usage_events (recipe_id);
create index api_request_logs_created_idx on public.api_request_logs (created_at desc);
create index api_request_logs_path_idx on public.api_request_logs (path, created_at desc);
create index subscription_events_user_idx on public.subscription_events (user_id, event_at desc);
create index api_spend_ledger_user_created_idx on public.api_spend_ledger (user_id, created_at desc);
create index security_events_created_idx on public.security_events (created_at desc);
create index security_events_user_idx on public.security_events (user_id);
create index extract_job_access_user_idx on public.extract_job_access (user_id, created_at desc);
create index recipe_translations_language_idx on public.recipe_translations (language_code, updated_at desc);
create index auth_refresh_tokens_user_idx on public.auth_refresh_tokens (user_id, created_at desc);
create index auth_refresh_tokens_active_idx
  on public.auth_refresh_tokens (user_id, expires_at)
  where revoked_at is null;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  new.updated_at = pg_catalog.now();
  return new;
end;
$$;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

create trigger recipes_set_updated_at
  before update on public.recipes
  for each row execute procedure public.set_updated_at();

create trigger extract_jobs_set_updated_at
  before update on public.extract_jobs
  for each row execute procedure public.set_updated_at();

create trigger recipe_translations_set_updated_at
  before update on public.recipe_translations
  for each row execute procedure public.set_updated_at();

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
set search_path = pg_catalog, public
as $$
declare
  v_daily numeric;
  v_monthly numeric;
  v_user_monthly numeric;
  v_id uuid;
  v_threshold integer;
begin
  update public.api_spend_ledger as ledger
     set status = 'failed',
         settled_at = pg_catalog.now()
   where ledger.status = 'reserved'
     and ledger.created_at < pg_catalog.now() - interval '2 hours';

  if p_reserved_cents <= 0 then
    return query select false, 'invalid_reservation', null::uuid, 0::numeric;
    return;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('reciapp-api-spend', 0));

  if exists (select 1 from public.api_spend_ledger as ledger where ledger.job_id = p_job_id) then
    select ledger.id
      into v_id
      from public.api_spend_ledger as ledger
     where ledger.job_id = p_job_id;
    return query select true, 'already_reserved', v_id, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_daily
    from public.api_spend_ledger as ledger
   where ledger.created_at >= pg_catalog.date_trunc('day', pg_catalog.now());
  if v_daily + p_reserved_cents > p_daily_budget_cents then
    return query select false, 'daily_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_monthly
    from public.api_spend_ledger as ledger
   where ledger.created_at >= pg_catalog.date_trunc('month', pg_catalog.now());
  if v_monthly + p_reserved_cents > p_monthly_budget_cents then
    return query select false, 'monthly_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_user_monthly
    from public.api_spend_ledger as ledger
   where ledger.user_id = p_user_id
     and ledger.created_at >= pg_catalog.date_trunc('month', pg_catalog.now());
  if v_user_monthly + p_reserved_cents > p_user_monthly_budget_cents then
    return query select false, 'user_monthly_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  insert into public.api_spend_ledger as ledger (user_id, job_id, reserved_cents)
  values (p_user_id, p_job_id, p_reserved_cents)
  returning ledger.id into v_id;

  v_daily := v_daily + p_reserved_cents;
  v_monthly := v_monthly + p_reserved_cents;
  foreach v_threshold in array array[50, 75, 90, 100] loop
    if p_daily_budget_cents > 0 and v_daily >= p_daily_budget_cents * v_threshold / 100 then
      insert into public.spend_alerts (period_start, scope, threshold)
      values (current_date, 'daily', v_threshold)
      on conflict do nothing;
    end if;
    if p_monthly_budget_cents > 0 and v_monthly >= p_monthly_budget_cents * v_threshold / 100 then
      insert into public.spend_alerts (period_start, scope, threshold)
      values (pg_catalog.date_trunc('month', pg_catalog.now())::date, 'monthly', v_threshold)
      on conflict do nothing;
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
set search_path = pg_catalog, public
as $$
begin
  update public.api_spend_ledger as ledger
     set actual_cents = greatest(coalesce(p_actual_cents, 0), 0),
         status = case when p_status in ('settled', 'failed') then p_status else 'failed' end,
         settled_at = pg_catalog.now()
   where ledger.job_id = p_job_id
     and ledger.status = 'reserved';
end;
$$;

create or replace function public.claim_next_extract_job(p_lease_seconds integer default 900)
returns table(
  id uuid,
  user_id uuid,
  source_url_raw text,
  source_url_norm text,
  language_code text,
  job_kind text,
  recipe_id uuid,
  attempt_count integer,
  lease_until timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_lease_seconds integer := greatest(30, least(coalesce(p_lease_seconds, 900), 1800));
begin
  update public.extract_jobs as job
     set status = 'failed',
         progress = 0,
         error = 'Job exhausted its retry limit. Retry the import.',
         lease_until = null
   where job.status in ('pending', 'processing')
     and job.attempt_count >= 5
     and (job.lease_until is null or job.lease_until < pg_catalog.now());

  update public.api_spend_ledger as ledger
     set actual_cents = 0,
         status = 'failed',
         settled_at = pg_catalog.now()
   where ledger.status = 'reserved'
     and exists (
       select 1
         from public.extract_jobs as job
        where job.id = ledger.job_id
          and job.status = 'failed'
          and job.error = 'Job exhausted its retry limit. Retry the import.'
     );

  return query
  with candidate as (
    select job.id
      from public.extract_jobs as job
     where job.attempt_count < 5
       and (
         job.status = 'pending'
         or (job.status = 'processing' and (job.lease_until is null or job.lease_until < pg_catalog.now()))
       )
     order by job.created_at
     for update skip locked
     limit 1
  ), claimed as (
    update public.extract_jobs as job
       set status = 'processing',
           progress = 0,
           attempt_count = job.attempt_count + 1,
           lease_until = pg_catalog.now() + pg_catalog.make_interval(secs => v_lease_seconds),
           error = null
      from candidate
     where job.id = candidate.id
     returning job.id, job.user_id, job.source_url_raw, job.source_url_norm,
               job.language_code, job.job_kind, job.recipe_id,
               job.attempt_count, job.lease_until
  )
  select claimed.id, claimed.user_id, claimed.source_url_raw, claimed.source_url_norm,
         claimed.language_code, claimed.job_kind, claimed.recipe_id,
         claimed.attempt_count, claimed.lease_until
    from claimed;
end;
$$;

insert into public.app_settings (
  id,
  free_weekly_limit,
  pro_margin_ratio,
  default_pro_monthly_price_cents
)
values (1, 10, 0.20, 499)
on conflict (id) do nothing;

revoke all on table public.api_request_logs from public;
revoke all on table public.subscription_events from public;
revoke all on table public.api_spend_ledger from public;
revoke all on table public.security_events from public;
revoke all on table public.spend_alerts from public;
revoke all on table public.apple_notification_events from public;
revoke all on table public.extract_job_access from public;
revoke all on table public.auth_refresh_tokens from public;
revoke all on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) from public;
revoke all on function public.settle_api_spend(uuid, numeric, text) from public;
revoke all on function public.claim_next_extract_job(integer) from public;
revoke all on function public.set_updated_at() from public;

do $$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'reciapp') then
    grant usage on schema public to reciapp;
    grant all privileges on all tables in schema public to reciapp;
    grant all privileges on all sequences in schema public to reciapp;
    grant execute on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) to reciapp;
    grant execute on function public.settle_api_spend(uuid, numeric, text) to reciapp;
    grant execute on function public.claim_next_extract_job(integer) to reciapp;
  end if;
end;
$$;
