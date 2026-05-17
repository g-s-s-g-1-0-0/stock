alter table public.user_settings
  add column if not exists personal_trade_logs jsonb not null default '[]'::jsonb,
  add column if not exists contribution_settings jsonb not null default '{}'::jsonb,
  add column if not exists portfolio_state_initialized boolean not null default false;

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

  insert into public.user_settings (owner_id, personal_trade_logs, contribution_settings, portfolio_state_initialized)
  values (new.id, '[]'::jsonb, '{}'::jsonb, false)
  on conflict do nothing;

  return new;
end;
$$;
