-- Raise Pro fair-use margin to 40% (OpenAI budget = monthly price × 0.60).
alter table public.app_settings
  alter column pro_margin_ratio set default 0.40;

update public.app_settings
   set pro_margin_ratio = 0.40
 where id = 1;

-- Profiles that still carry the old 20% default follow the new global margin.
update public.profiles
   set pro_margin_ratio = 0.40
 where pro_margin_ratio is null
    or pro_margin_ratio = 0.20;
