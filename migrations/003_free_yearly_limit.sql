-- Free plan: 10 recipes per calendar year (UTC), not 1 per week.
update public.app_settings
   set free_weekly_limit = 10,
       updated_at = now()
 where id = 1
   and free_weekly_limit = 1;

alter table public.app_settings
  alter column free_weekly_limit set default 10;

-- Drop stale weekly=1 overrides so users inherit the yearly 10.
update public.profiles
   set free_weekly_limit = null
 where free_weekly_limit = 1;
