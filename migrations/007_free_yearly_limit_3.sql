-- Finalize the product rule: Free users get 3 new recipes per UTC calendar
-- year. The column name remains legacy for API/database compatibility.
update public.app_settings
   set free_weekly_limit = 3,
       updated_at = now()
 where id = 1;

alter table public.app_settings
  alter column free_weekly_limit set default 3;

-- Remove old per-profile weekly overrides. The API enforces the yearly cap;
-- null makes future subscription transitions inherit the global default.
update public.profiles
   set free_weekly_limit = null
 where free_weekly_limit is not null;
