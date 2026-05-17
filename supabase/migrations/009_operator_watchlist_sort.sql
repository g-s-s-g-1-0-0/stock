alter table public.watchlists
  add column if not exists watchlist_sort jsonb not null default '{"primary":"registered","secondary":"registered"}'::jsonb;

update public.watchlists
set watchlist_sort = coalesce((
  select user_settings.watchlist_sort
  from public.user_settings
  join public.profiles on profiles.id = user_settings.owner_id
  where profiles.is_admin = true
  order by user_settings.updated_at desc
  limit 1
), watchlists.watchlist_sort)
where scope = 'operator' and owner_id is null;
