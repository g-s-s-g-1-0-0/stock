create table if not exists public.user_settings (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  watchlist_sort jsonb not null default '{"primary":"registered","secondary":"registered"}'::jsonb,
  notification_preferences jsonb not null default '{"opinionChangeEmail":true,"weeklyTrendReport":true,"earningsDayBefore":true,"adminAutoUpdateFailureEmail":true,"recipientEmail":""}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.api_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references auth.users(id) on delete set null,
  trigger_name text not null,
  status text not null check (status in ('success', 'failure')),
  message text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop trigger if exists user_settings_touch_updated_at on public.user_settings;
create trigger user_settings_touch_updated_at
  before update on public.user_settings
  for each row execute function public.touch_updated_at();

create index if not exists api_logs_created_at_idx
  on public.api_logs(created_at desc);

create index if not exists api_logs_trigger_status_idx
  on public.api_logs(trigger_name, status, created_at desc);

alter table public.user_settings enable row level security;
alter table public.api_logs enable row level security;

drop policy if exists "user_settings_read_own_or_admin" on public.user_settings;
create policy "user_settings_read_own_or_admin"
  on public.user_settings
  for select
  using (owner_id = auth.uid() or public.current_user_is_admin());

drop policy if exists "user_settings_insert_own" on public.user_settings;
create policy "user_settings_insert_own"
  on public.user_settings
  for insert
  with check (owner_id = auth.uid());

drop policy if exists "user_settings_update_own" on public.user_settings;
create policy "user_settings_update_own"
  on public.user_settings
  for update
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "api_logs_admin_read" on public.api_logs;
create policy "api_logs_admin_read"
  on public.api_logs
  for select
  using (public.current_user_is_admin());

drop policy if exists "api_logs_insert_own" on public.api_logs;
create policy "api_logs_insert_own"
  on public.api_logs
  for insert
  with check (actor_id = auth.uid());

drop policy if exists "api_logs_admin_delete" on public.api_logs;
create policy "api_logs_admin_delete"
  on public.api_logs
  for delete
  using (public.current_user_is_admin());

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
