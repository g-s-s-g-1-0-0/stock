create table if not exists public.board_comments (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references public.board_posts(id) on delete cascade,
  content text not null check (char_length(content) <= 500),
  author_id uuid not null references auth.users(id) on delete cascade,
  author_name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists board_comments_touch_updated_at on public.board_comments;
create trigger board_comments_touch_updated_at
  before update on public.board_comments
  for each row execute function public.touch_updated_at();

create index if not exists board_comments_post_created_at_idx
  on public.board_comments(post_id, created_at asc);

create or replace function public.enforce_board_comment_limit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if (
    select count(*)
    from public.board_comments
    where post_id = new.post_id
  ) >= 50 then
    raise exception 'board comment limit reached';
  end if;

  return new;
end;
$$;

drop trigger if exists board_comments_limit on public.board_comments;
create trigger board_comments_limit
  before insert on public.board_comments
  for each row execute function public.enforce_board_comment_limit();

alter table public.board_comments enable row level security;

drop policy if exists "board_comments_read_visible_post_or_owner_or_admin" on public.board_comments;
create policy "board_comments_read_visible_post_or_owner_or_admin"
  on public.board_comments
  for select
  using (
    exists (
      select 1
      from public.board_posts
      where board_posts.id = board_comments.post_id
        and (
          board_posts.hidden = false
          or board_posts.author_id = auth.uid()
          or public.current_user_is_admin()
        )
    )
  );

drop policy if exists "board_comments_insert_own_on_visible_post" on public.board_comments;
create policy "board_comments_insert_own_on_visible_post"
  on public.board_comments
  for insert
  with check (
    author_id = auth.uid()
    and exists (
      select 1
      from public.board_posts
      where board_posts.id = board_comments.post_id
        and board_posts.hidden = false
    )
  );

drop policy if exists "board_comments_delete_own_or_admin" on public.board_comments;
create policy "board_comments_delete_own_or_admin"
  on public.board_comments
  for delete
  using (author_id = auth.uid() or public.current_user_is_admin());
