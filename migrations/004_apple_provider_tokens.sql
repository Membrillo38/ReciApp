-- Encrypted Sign in with Apple refresh tokens for account-deletion revocation.
-- Apply after 001_init.sql (and ideally 002_row_level_security.sql + 003_free_yearly_limit.sql).

create table if not exists public.auth_provider_tokens (
  user_id uuid not null references public.profiles (id) on delete cascade,
  provider text not null,
  token_ciphertext text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, provider),
  constraint auth_provider_tokens_provider_check check (provider = 'apple')
);

drop trigger if exists auth_provider_tokens_set_updated_at on public.auth_provider_tokens;
create trigger auth_provider_tokens_set_updated_at
  before update on public.auth_provider_tokens
  for each row execute procedure public.set_updated_at();

-- RLS only when migration 002 helpers exist. Current prod role bypasses RLS anyway.
do $$
begin
  if to_regprocedure('public.app_is_service()') is not null
     and to_regprocedure('public.app_is_auth()') is not null
     and to_regprocedure('public.app_user_id()') is not null then
    execute 'alter table public.auth_provider_tokens enable row level security';
    execute 'alter table public.auth_provider_tokens force row level security';
    execute 'drop policy if exists reciapp_service on public.auth_provider_tokens';
    execute $p$
      create policy reciapp_service on public.auth_provider_tokens
        using (public.app_is_service())
        with check (public.app_is_service())
    $p$;
    execute 'drop policy if exists auth_provider_tokens_auth on public.auth_provider_tokens';
    execute $p$
      create policy auth_provider_tokens_auth on public.auth_provider_tokens
        using (public.app_is_auth())
        with check (public.app_is_auth())
    $p$;
    execute 'drop policy if exists auth_provider_tokens_self on public.auth_provider_tokens';
    execute $p$
      create policy auth_provider_tokens_self on public.auth_provider_tokens
        using (user_id = public.app_user_id())
        with check (user_id = public.app_user_id())
    $p$;
  else
    execute 'alter table public.auth_provider_tokens no force row level security';
    execute 'alter table public.auth_provider_tokens disable row level security';
  end if;
end;
$$;

revoke all on table public.auth_provider_tokens from public;

do $$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'reciapp') then
    grant all privileges on table public.auth_provider_tokens to reciapp;
  end if;
end;
$$;
