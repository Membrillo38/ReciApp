-- Preserve recipe component boundaries and actionable source tips.
alter table public.recipes
  add column if not exists ingredient_sections jsonb not null default '[]'::jsonb,
  add column if not exists tips jsonb not null default '[]'::jsonb;
