-- 006 kept the original unique constraint and also added a fallback index.
-- Remove only the redundant fallback when the canonical constraint exists.
do $$
begin
  if to_regclass('public.recipes_source_url_norm_key') is not null then
    drop index if exists public.recipes_source_url_norm_uidx;
  end if;
end;
$$;
