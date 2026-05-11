alter table public.user_settings
  add column if not exists investment_type text
  check (investment_type in ('swing', 'long_term'));

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, name)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(nullif(new.raw_user_meta_data->>'name', ''), split_part(coalesce(new.email, ''), '@', 1), '사용자')
  )
  on conflict (id) do update
    set email = excluded.email,
        name = excluded.name;

  insert into public.watchlists (owner_id, scope, tickers)
  values (new.id, 'personal', '{}')
  on conflict do nothing;

  insert into public.user_settings (owner_id)
  values (new.id)
  on conflict do nothing;

  return new;
end;
$$;
