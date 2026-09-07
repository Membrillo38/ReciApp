-- Add ordered TikTok photo-carousel media while preserving legacy thumbnails.
alter table public.recipes
  add column if not exists carousel_image_urls jsonb not null default '[]'::jsonb;

alter table public.recipes
  drop constraint if exists recipes_carousel_image_urls_array_check;

alter table public.recipes
  add constraint recipes_carousel_image_urls_array_check
  check (
    jsonb_typeof(carousel_image_urls) = 'array'
    and jsonb_array_length(
      case
        when jsonb_typeof(carousel_image_urls) = 'array' then carousel_image_urls
        else '[]'::jsonb
      end
    ) <= 12
  );
