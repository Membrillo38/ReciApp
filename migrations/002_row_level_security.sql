-- Row Level Security for the self-hosted reciapp role.
-- The API sets SET LOCAL app.actor / app.user_id on every transaction.
-- Empty actor: no policy matches (fail closed). Table owner is forced through RLS.

create or replace function public.app_is_service()
returns boolean
language sql
stable
parallel safe
set search_path = pg_catalog, public
as $$
  select coalesce(current_setting('app.actor', true), '') = 'service'
$$;

create or replace function public.app_is_auth()
returns boolean
language sql
stable
parallel safe
set search_path = pg_catalog, public
as $$
  select coalesce(current_setting('app.actor', true), '') = 'auth'
$$;

create or replace function public.app_user_id()
returns uuid
language sql
stable
parallel safe
set search_path = pg_catalog, public
as $$
  select nullif(current_setting('app.user_id', true), '')::uuid
$$;

revoke all on function public.app_is_service() from public;
revoke all on function public.app_is_auth() from public;
revoke all on function public.app_user_id() from public;

do $$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'reciapp') then
    grant execute on function public.app_is_service() to reciapp;
    grant execute on function public.app_is_auth() to reciapp;
    grant execute on function public.app_user_id() to reciapp;
  end if;
end;
$$;

-- Security definer jobs/spend must see every row even under FORCE RLS.
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
  perform set_config('app.actor', 'service', true);

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
  perform set_config('app.actor', 'service', true);
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
  perform set_config('app.actor', 'service', true);
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

do $$
declare
  t text;
begin
  foreach t in array array[
    'profiles',
    'recipes',
    'user_recipes',
    'extract_jobs',
    'usage_events',
    'api_request_logs',
    'app_settings',
    'subscription_events',
    'api_spend_ledger',
    'security_events',
    'spend_alerts',
    'extract_job_access',
    'apple_notification_events',
    'recipe_translations',
    'auth_refresh_tokens'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('drop policy if exists reciapp_service on public.%I', t);
    execute format(
      'create policy reciapp_service on public.%I using (public.app_is_service()) with check (public.app_is_service())',
      t
    );
  end loop;
end;
$$;

create policy profiles_auth on public.profiles
  using (public.app_is_auth())
  with check (public.app_is_auth());
create policy profiles_self on public.profiles
  using (id = public.app_user_id())
  with check (id = public.app_user_id());

create policy recipes_user_select on public.recipes
  for select using (public.app_user_id() is not null);
create policy recipes_user_insert on public.recipes
  for insert with check (public.app_user_id() is not null);
create policy recipes_user_update on public.recipes
  for update using (public.app_user_id() is not null)
  with check (public.app_user_id() is not null);

create policy recipe_translations_user_select on public.recipe_translations
  for select using (public.app_user_id() is not null);
create policy recipe_translations_user_insert on public.recipe_translations
  for insert with check (public.app_user_id() is not null);
create policy recipe_translations_user_update on public.recipe_translations
  for update using (public.app_user_id() is not null)
  with check (public.app_user_id() is not null);

create policy user_recipes_self on public.user_recipes
  using (user_id = public.app_user_id())
  with check (user_id = public.app_user_id());

create policy extract_jobs_select on public.extract_jobs
  for select using (
    user_id = public.app_user_id()
    or exists (
      select 1 from public.extract_job_access access
       where access.job_id = extract_jobs.id
         and access.user_id = public.app_user_id()
    )
    or (
      public.app_user_id() is not null
      and status in ('pending', 'processing')
    )
  );
create policy extract_jobs_insert on public.extract_jobs
  for insert with check (user_id = public.app_user_id());
create policy extract_jobs_update on public.extract_jobs
  for update using (
    user_id = public.app_user_id()
    or exists (
      select 1 from public.extract_job_access access
       where access.job_id = extract_jobs.id
         and access.user_id = public.app_user_id()
    )
  )
  with check (
    user_id = public.app_user_id()
    or user_id is null
    or exists (
      select 1 from public.extract_job_access access
       where access.job_id = extract_jobs.id
         and access.user_id = public.app_user_id()
    )
  );

create policy extract_job_access_self on public.extract_job_access
  using (user_id = public.app_user_id())
  with check (user_id = public.app_user_id());

create policy usage_events_self on public.usage_events
  using (user_id = public.app_user_id() or (user_id is null and public.app_user_id() is not null))
  with check (user_id = public.app_user_id() or user_id is null);

create policy api_spend_ledger_self on public.api_spend_ledger
  using (user_id = public.app_user_id() or (user_id is null and public.app_user_id() is not null))
  with check (user_id = public.app_user_id() or user_id is null);

create policy auth_refresh_tokens_auth on public.auth_refresh_tokens
  using (public.app_is_auth())
  with check (public.app_is_auth());
create policy auth_refresh_tokens_self on public.auth_refresh_tokens
  using (user_id = public.app_user_id())
  with check (user_id = public.app_user_id());

create policy app_settings_read on public.app_settings
  for select using (public.app_user_id() is not null or public.app_is_auth());

create policy api_request_logs_insert on public.api_request_logs
  for insert with check (true);

create policy security_events_insert on public.security_events
  for insert with check (true);
create policy security_events_self_update on public.security_events
  for update using (user_id = public.app_user_id())
  with check (user_id = public.app_user_id() or user_id is null);
