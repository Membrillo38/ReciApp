-- Legacy migration retained for ordered installs. Final product cap is 3
-- recipes per calendar year (UTC), not 1 per week; 007 reapplies this value
-- for databases that already ran the old version of this migration.
update public.app_settings
   set free_weekly_limit = 3,
       updated_at = now()
 where id = 1
   and free_weekly_limit in (1, 10);

alter table public.app_settings
  alter column free_weekly_limit set default 3;

-- Drop stale weekly overrides so users inherit the yearly 3.
update public.profiles
   set free_weekly_limit = null
 where free_weekly_limit in (1, 10);
