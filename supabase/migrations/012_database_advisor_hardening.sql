-- Address Supabase advisor findings without exposing server-owned tables.

-- Triggers should not inherit a caller-controlled search_path.
alter function public.set_updated_at()
  set search_path = public;

-- Index every foreign key used by user recipe/job cleanup or joins.
create index if not exists security_events_user_idx
  on public.security_events (user_id);

create index if not exists usage_events_job_idx
  on public.usage_events (job_id);

create index if not exists usage_events_recipe_idx
  on public.usage_events (recipe_id);

create index if not exists user_recipes_recipe_idx
  on public.user_recipes (recipe_id);

-- Evaluate auth.uid() once per statement, not once per candidate row.
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select using ((select auth.uid()) = id and deleted_at is null);

drop policy if exists user_recipes_select_own on public.user_recipes;
create policy user_recipes_select_own on public.user_recipes
  for select using ((select auth.uid()) = user_id);

drop policy if exists user_recipes_delete_own on public.user_recipes;
create policy user_recipes_delete_own on public.user_recipes
  for delete using ((select auth.uid()) = user_id);

drop policy if exists user_recipes_insert_own on public.user_recipes;
create policy user_recipes_insert_own on public.user_recipes
  for insert with check ((select auth.uid()) = user_id);

drop policy if exists recipes_select_if_saved on public.recipes;
create policy recipes_select_if_saved on public.recipes
  for select using (
    exists (
      select 1 from public.user_recipes ur
      where ur.recipe_id = recipes.id
        and ur.user_id = (select auth.uid())
    )
  );

drop policy if exists extract_jobs_select_own on public.extract_jobs;
create policy extract_jobs_select_own on public.extract_jobs
  for select using ((select auth.uid()) = user_id);

drop policy if exists extract_job_access_select_own on public.extract_job_access;
create policy extract_job_access_select_own on public.extract_job_access
  for select using ((select auth.uid()) = user_id);
