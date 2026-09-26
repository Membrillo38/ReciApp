-- Repeated Share Extension submissions with the same delivery ID reuse the
-- original job instead of creating duplicate work or spend reservations.
alter table public.extract_jobs
  add column if not exists client_delivery_id uuid;

create unique index if not exists extract_jobs_user_delivery_unique
  on public.extract_jobs (user_id, client_delivery_id)
  where client_delivery_id is not null;
