alter table public.extract_jobs
  add column if not exists progress integer not null default 0
  check (progress >= 0 and progress <= 100);
