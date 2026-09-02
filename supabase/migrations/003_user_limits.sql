-- Per-user limits + global defaults (app_settings)

create table if not exists public.app_settings (
  id int primary key default 1 check (id = 1),
  free_weekly_limit int not null default 1,
  pro_margin_ratio numeric(5, 4) not null default 0.20,
  default_pro_monthly_price_cents int not null default 499,
  updated_at timestamptz not null default now()
);

insert into public.app_settings (id, free_weekly_limit, pro_margin_ratio, default_pro_monthly_price_cents)
values (1, 1, 0.20, 499)
on conflict (id) do nothing;

alter table public.profiles
  add column if not exists free_weekly_limit int,
  add column if not exists pro_monthly_price_cents int,
  add column if not exists pro_margin_ratio numeric(5, 4);

comment on column public.profiles.free_weekly_limit is 'Free tier weekly import cap; null = app_settings default';
comment on column public.profiles.pro_monthly_price_cents is 'Actual Pro price paid (cents); set by Superwall webhook';
comment on column public.profiles.pro_margin_ratio is 'Per-user margin override; null = app_settings default';

alter table public.app_settings enable row level security;
