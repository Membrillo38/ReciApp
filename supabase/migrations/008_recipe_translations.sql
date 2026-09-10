-- Share one translation cache entry across every user.
alter table public.extract_jobs
  add column if not exists job_kind text not null default 'extract';

alter table public.extract_jobs
  drop constraint if exists extract_jobs_job_kind_check;

alter table public.extract_jobs
  add constraint extract_jobs_job_kind_check
  check (job_kind in ('extract', 'translation'));

create table if not exists public.recipe_translations (
  recipe_id uuid not null references public.recipes (id) on delete cascade,
  language_code text not null check (language_code in (
    'ar', 'bn', 'ca', 'zh-Hans', 'zh-Hant', 'hr', 'cs', 'da', 'nl',
    'en-AU', 'en-CA', 'en-GB', 'en-US', 'fi', 'fr-FR', 'fr-CA', 'de', 'el',
    'gu', 'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'ms', 'ml', 'mr',
    'nb', 'or', 'pl', 'pt-BR', 'pt-PT', 'pa', 'ro', 'ru', 'sk', 'sl',
    'es-MX', 'es-ES', 'sv', 'ta', 'te', 'th', 'tr', 'uk', 'ur', 'vi'
  )),
  payload jsonb not null default '{}'::jsonb,
  source_fingerprint text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (recipe_id, language_code)
);

create index if not exists recipe_translations_language_idx
  on public.recipe_translations (language_code, updated_at desc);

drop index if exists public.extract_jobs_active_norm_unique;
drop index if exists public.extract_jobs_active_language_norm_unique;

create unique index if not exists extract_jobs_active_extract_norm_unique
  on public.extract_jobs (source_url_norm)
  where status in ('pending', 'processing') and job_kind = 'extract';

create unique index if not exists extract_jobs_active_translation_unique
  on public.extract_jobs (recipe_id, language_code)
  where status in ('pending', 'processing') and job_kind = 'translation';

alter table public.recipe_translations enable row level security;
revoke all on public.recipe_translations from anon, authenticated;

drop trigger if exists recipe_translations_set_updated_at on public.recipe_translations;
create trigger recipe_translations_set_updated_at
  before update on public.recipe_translations
  for each row execute procedure public.set_updated_at();
