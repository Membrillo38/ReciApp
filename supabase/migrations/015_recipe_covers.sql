-- Public recipe cover JPEGs selected from the first two seconds of source video.
insert into storage.buckets (id, name, public)
values ('recipe-covers', 'recipe-covers', true)
on conflict (id) do nothing;

drop policy if exists "recipe_covers_public_read" on storage.objects;
create policy "recipe_covers_public_read"
on storage.objects
for select
using (bucket_id = 'recipe-covers');
