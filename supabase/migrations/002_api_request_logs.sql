-- API request log for admin dashboard
create table if not exists public.api_request_logs (
  id uuid primary key default gen_random_uuid(),
  method text not null,
  path text not null,
  status_code int not null,
  duration_ms int not null default 0,
  user_id uuid,
  ip text,
  created_at timestamptz not null default now()
);

create index if not exists api_request_logs_created_idx
  on public.api_request_logs (created_at desc);

create index if not exists api_request_logs_path_idx
  on public.api_request_logs (path, created_at desc);

alter table public.api_request_logs enable row level security;
