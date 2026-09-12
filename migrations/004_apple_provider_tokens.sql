-- Encrypted Sign in with Apple refresh tokens for account-deletion revocation.
-- Apply after 001_init.sql, 002_row_level_security.sql and 003_free_yearly_limit.sql.

create table public.auth_provider_tokens (
  user_id uuid not null references public.profiles (id) on delete cascade,
  provider text not null,
  token_ciphertext text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, provider),
  constraint auth_provider_tokens_provider_check check (provider = 'apple')
);

create trigger auth_provider_tokens_set_updated_at
  before update on public.auth_provider_tokens
  for each row execute procedure public.set_updated_at();

alter table public.auth_provider_tokens enable row level security;
alter table public.auth_provider_tokens force row level security;

drop policy if exists reciapp_service on public.auth_provider_tokens;
create policy reciapp_service on public.auth_provider_tokens
  using (public.app_is_service())
  with check (public.app_is_service());

create policy auth_provider_tokens_auth on public.auth_provider_tokens
  using (public.app_is_auth())
  with check (public.app_is_auth());

create policy auth_provider_tokens_self on public.auth_provider_tokens
  using (user_id = public.app_user_id())
  with check (user_id = public.app_user_id());

revoke all on table public.auth_provider_tokens from public;

do $$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'reciapp') then
    grant all privileges on table public.auth_provider_tokens to reciapp;
  end if;
end;
$$;
