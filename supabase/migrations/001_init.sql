-- ReciApp initial schema: cache, users, usage, jobs
create extension if not exists "pgcrypto";

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  is_pro boolean not null default false,
  pro_expires_at timestamptz,
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.recipes (
  id uuid primary key default gen_random_uuid(),
  source_url_raw text not null,
  source_url_norm text not null unique,
  platform text not null,
  title text not null,
  description text,
  author text,
  thumbnail_url text,
  ingredients jsonb not null default '[]'::jsonb,
  steps jsonb not null default '[]'::jsonb,
  servings int,
  prep_minutes int,
  cook_minutes int,
  tags jsonb not null default '[]'::jsonb,
  confidence double precision not null default 0.5,
  missing_fields jsonb not null default '[]'::jsonb,
  raw_transcript text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.user_recipes (
  user_id uuid not null references public.profiles (id) on delete cascade,
  recipe_id uuid not null references public.recipes (id) on delete cascade,
  saved_at timestamptz not null default now(),
  primary key (user_id, recipe_id)
);

create table if not exists public.extract_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles (id) on delete set null,
  status text not null default 'pending',
  source_url_raw text not null,
  source_url_norm text not null,
  recipe_id uuid references public.recipes (id) on delete set null,
  cache_hit boolean not null default false,
  cost_cents numeric(12, 4) not null default 0,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  kind text not null check (kind in ('extract_hit', 'extract_miss')),
  cost_cents numeric(12, 4) not null default 0,
  recipe_id uuid references public.recipes (id) on delete set null,
  job_id uuid references public.extract_jobs (id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists recipes_platform_idx on public.recipes (platform);
create index if not exists user_recipes_user_idx on public.user_recipes (user_id, saved_at desc);
create index if not exists extract_jobs_user_idx on public.extract_jobs (user_id, created_at desc);
create index if not exists usage_events_user_week_idx on public.usage_events (user_id, created_at desc);
create index if not exists profiles_is_pro_idx on public.profiles (is_pro) where deleted_at is null;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', new.email)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists recipes_set_updated_at on public.recipes;
create trigger recipes_set_updated_at
  before update on public.recipes
  for each row execute procedure public.set_updated_at();

drop trigger if exists extract_jobs_set_updated_at on public.extract_jobs;
create trigger extract_jobs_set_updated_at
  before update on public.extract_jobs
  for each row execute procedure public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.recipes enable row level security;
alter table public.user_recipes enable row level security;
alter table public.extract_jobs enable row level security;
alter table public.usage_events enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (auth.uid() = id and deleted_at is null);

create policy "user_recipes_select_own" on public.user_recipes
  for select using (auth.uid() = user_id);

create policy "user_recipes_delete_own" on public.user_recipes
  for delete using (auth.uid() = user_id);

create policy "recipes_select_if_saved" on public.recipes
  for select using (
    exists (
      select 1 from public.user_recipes ur
      where ur.recipe_id = recipes.id and ur.user_id = auth.uid()
    )
  );
