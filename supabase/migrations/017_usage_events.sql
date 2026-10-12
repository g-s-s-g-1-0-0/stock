create table if not exists public.usage_logging (
  id int primary key default 1 check (id = 1),
  started_on date not null
);

insert into public.usage_logging (id, started_on)
values (1, (timezone('Asia/Seoul', now()))::date)
on conflict (id) do nothing;

create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid not null references auth.users(id) on delete cascade,
  page text not null,
  occurred_on date not null,
  created_at timestamptz not null default now(),
  constraint usage_events_page_check check (
    page in ('home', 'value-analysis', 'technical-analysis', 'market-events', 'market-trends')
  ),
  constraint usage_events_actor_page_day unique (actor_id, page, occurred_on)
);

create index if not exists usage_events_occurred_on_idx
  on public.usage_events (occurred_on desc);

alter table public.usage_logging enable row level security;
alter table public.usage_events enable row level security;

drop policy if exists "usage_logging_admin_read" on public.usage_logging;
create policy "usage_logging_admin_read"
  on public.usage_logging
  for select
  using (public.current_user_is_admin());

drop policy if exists "usage_events_admin_read" on public.usage_events;
create policy "usage_events_admin_read"
  on public.usage_events
  for select
  using (public.current_user_is_admin());

create or replace function public.record_usage(visited_page text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  if visited_page is null or visited_page not in (
    'home', 'value-analysis', 'technical-analysis', 'market-events', 'market-trends'
  ) then
    raise exception 'invalid page';
  end if;

  insert into public.usage_events (actor_id, page, occurred_on)
  values (auth.uid(), visited_page, (timezone('Asia/Seoul', now()))::date)
  on conflict (actor_id, page, occurred_on) do nothing;
end;
$$;

revoke all on function public.record_usage(text) from public;
revoke all on function public.record_usage(text) from anon;
grant execute on function public.record_usage(text) to authenticated;
