-- Keep the base recipe cache unique by source URL.
alter table public.recipes
    add column if not exists language_code text not null default 'en-US';

alter table public.extract_jobs
    add column if not exists language_code text not null default 'en-US';

drop index if exists public.recipes_source_language_uidx;
drop index if exists public.extract_jobs_active_language_norm_unique;
drop index if exists public.extract_jobs_source_language_idx;

-- Existing deployments retain recipes_source_url_norm_key from 001_init.
-- This fallback also repairs environments where the old constraint was removed.
create unique index if not exists recipes_source_url_norm_uidx
  on public.recipes (source_url_norm);
