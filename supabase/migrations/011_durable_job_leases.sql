-- Durable extraction claims for a separately deployed Render worker.
-- The web process remains compatible with BackgroundTasks until WORKER_ENABLED
-- is explicitly enabled after this migration is applied.
alter table public.extract_jobs
  add column if not exists attempt_count integer not null default 0,
  add column if not exists lease_until timestamptz;

alter table public.extract_jobs
  drop constraint if exists extract_jobs_attempt_count_check;

alter table public.extract_jobs
  add constraint extract_jobs_attempt_count_check
  check (attempt_count >= 0 and attempt_count <= 5);

create index if not exists extract_jobs_claim_idx
  on public.extract_jobs (status, lease_until, created_at)
  where status in ('pending', 'processing');

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
set search_path = public
as $$
declare
  v_lease_seconds integer := greatest(30, least(coalesce(p_lease_seconds, 900), 1800));
begin
  -- A worker that died after spending money must not reserve that money
  -- forever. The next claim attempt settles exhausted jobs as failed.
  update public.extract_jobs j
     set status = 'failed',
         progress = 0,
         error = 'Job exhausted its retry limit. Retry the import.',
         lease_until = null
   where j.status in ('pending', 'processing')
     and j.attempt_count >= 5
     and (j.lease_until is null or j.lease_until < now());

  update public.api_spend_ledger s
     set actual_cents = 0,
         status = 'failed',
         settled_at = now()
   where s.status = 'reserved'
     and exists (
       select 1
         from public.extract_jobs j
        where j.id = s.job_id
          and j.status = 'failed'
          and j.error = 'Job exhausted its retry limit. Retry the import.'
     );

  return query
  with candidate as (
    select j.id
      from public.extract_jobs j
     where j.attempt_count < 5
       and (
         j.status = 'pending'
         or (j.status = 'processing' and (j.lease_until is null or j.lease_until < now()))
       )
     order by j.created_at
     for update skip locked
     limit 1
  ), claimed as (
    update public.extract_jobs j
       set status = 'processing',
           progress = 0,
           attempt_count = j.attempt_count + 1,
           lease_until = now() + make_interval(secs => v_lease_seconds),
           error = null
      from candidate c
     where j.id = c.id
     returning j.id, j.user_id, j.source_url_raw, j.source_url_norm,
               j.language_code, j.job_kind, j.recipe_id,
               j.attempt_count, j.lease_until
  )
  select c.id, c.user_id, c.source_url_raw, c.source_url_norm,
         c.language_code, c.job_kind, c.recipe_id,
         c.attempt_count, c.lease_until
    from claimed c;
end;
$$;

revoke all on function public.claim_next_extract_job(integer) from public, anon, authenticated;
grant execute on function public.claim_next_extract_job(integer) to service_role;
