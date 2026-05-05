create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  name text not null,
  is_admin boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.watchlists (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete cascade,
  scope text not null default 'personal' check (scope in ('personal', 'operator')),
  tickers text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint watchlists_personal_owner_required check (
    (scope = 'personal' and owner_id is not null)
    or (scope = 'operator' and owner_id is null)
  )
);

create unique index if not exists watchlists_owner_scope_idx
  on public.watchlists(owner_id, scope)
  where scope = 'personal';

create unique index if not exists watchlists_operator_scope_idx
  on public.watchlists(scope)
  where scope = 'operator';

create table if not exists public.board_posts (
  id uuid primary key default gen_random_uuid(),
  category text not null check (category in ('칭찬', '버그', '건의', '기타')),
  content text not null check (char_length(content) <= 2000),
  author_id uuid not null references auth.users(id) on delete cascade,
  author_name text not null,
  hidden boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
  before update on public.profiles
  for each row execute function public.touch_updated_at();

drop trigger if exists watchlists_touch_updated_at on public.watchlists;
create trigger watchlists_touch_updated_at
  before update on public.watchlists
  for each row execute function public.touch_updated_at();

drop trigger if exists board_posts_touch_updated_at on public.board_posts;
create trigger board_posts_touch_updated_at
  before update on public.board_posts
  for each row execute function public.touch_updated_at();

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

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

create or replace function public.current_user_is_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1
    from public.profiles
    where id = auth.uid()
      and is_admin = true
  );
$$;

alter table public.profiles enable row level security;
alter table public.watchlists enable row level security;
alter table public.board_posts enable row level security;

drop policy if exists "profiles_read_own_or_admin" on public.profiles;
create policy "profiles_read_own_or_admin"
  on public.profiles
  for select
  using (id = auth.uid() or public.current_user_is_admin());

drop policy if exists "profiles_update_own_name" on public.profiles;
create policy "profiles_update_own_name"
  on public.profiles
  for update
  using (id = auth.uid())
  with check (id = auth.uid() and is_admin = false);

drop policy if exists "watchlists_read_personal_or_operator" on public.watchlists;
create policy "watchlists_read_personal_or_operator"
  on public.watchlists
  for select
  using (
    (scope = 'personal' and owner_id = auth.uid())
    or scope = 'operator'
    or public.current_user_is_admin()
  );

drop policy if exists "watchlists_insert_personal" on public.watchlists;
create policy "watchlists_insert_personal"
  on public.watchlists
  for insert
  with check (scope = 'personal' and owner_id = auth.uid());

drop policy if exists "watchlists_update_personal" on public.watchlists;
create policy "watchlists_update_personal"
  on public.watchlists
  for update
  using (scope = 'personal' and owner_id = auth.uid())
  with check (scope = 'personal' and owner_id = auth.uid());

drop policy if exists "watchlists_admin_operator_write" on public.watchlists;
create policy "watchlists_admin_operator_write"
  on public.watchlists
  for all
  using (scope = 'operator' and public.current_user_is_admin())
  with check (scope = 'operator' and owner_id is null and public.current_user_is_admin());

drop policy if exists "board_posts_read_visible_or_owner_or_admin" on public.board_posts;
create policy "board_posts_read_visible_or_owner_or_admin"
  on public.board_posts
  for select
  using (hidden = false or author_id = auth.uid() or public.current_user_is_admin());

drop policy if exists "board_posts_insert_own" on public.board_posts;
create policy "board_posts_insert_own"
  on public.board_posts
  for insert
  with check (author_id = auth.uid());

drop policy if exists "board_posts_delete_own_or_admin" on public.board_posts;
create policy "board_posts_delete_own_or_admin"
  on public.board_posts
  for delete
  using (author_id = auth.uid() or public.current_user_is_admin());

drop policy if exists "board_posts_admin_update" on public.board_posts;
create policy "board_posts_admin_update"
  on public.board_posts
  for update
  using (public.current_user_is_admin())
  with check (public.current_user_is_admin());

insert into public.watchlists (owner_id, scope, tickers)
values (null, 'operator', '{}')
on conflict do nothing;
