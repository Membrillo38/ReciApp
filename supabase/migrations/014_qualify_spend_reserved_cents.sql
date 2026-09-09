-- RETURNS TABLE(reserved_cents ...) collides with api_spend_ledger.reserved_cents.
-- Unqualified SUM(...) then raises 42702 and POST /v1/extract returns 503.
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
  update public.api_spend_ledger as ledger
     set status = 'failed', settled_at = now()
   where ledger.status = 'reserved'
     and ledger.created_at < now() - interval '2 hours';

  if p_reserved_cents <= 0 then
    return query select false, 'invalid_reservation', null::uuid, 0::numeric;
    return;
  end if;

  perform pg_advisory_xact_lock(hashtextextended('reciapp-api-spend', 0));

  if exists (select 1 from public.api_spend_ledger as ledger where ledger.job_id = p_job_id) then
    select ledger.id into v_id from public.api_spend_ledger as ledger where ledger.job_id = p_job_id;
    return query select true, 'already_reserved', v_id, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_daily
    from public.api_spend_ledger as ledger
   where ledger.created_at >= date_trunc('day', now());
  if v_daily + p_reserved_cents > p_daily_budget_cents then
    return query select false, 'daily_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_monthly
    from public.api_spend_ledger as ledger
   where ledger.created_at >= date_trunc('month', now());
  if v_monthly + p_reserved_cents > p_monthly_budget_cents then
    return query select false, 'monthly_budget', null::uuid, p_reserved_cents;
    return;
  end if;

  select coalesce(sum(case when ledger.status = 'reserved' then ledger.reserved_cents else ledger.actual_cents end), 0)
    into v_user_monthly
    from public.api_spend_ledger as ledger
   where ledger.user_id = p_user_id and ledger.created_at >= date_trunc('month', now());
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

revoke all on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) from public, anon, authenticated;
grant execute on function public.reserve_api_spend(uuid, uuid, numeric, numeric, numeric, numeric) to service_role;
