create or replace function public.delete_own_account()
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  target_user_id uuid := auth.uid();
begin
  if target_user_id is null then
    raise exception 'not authenticated';
  end if;

  -- api_logs uses on delete set null, so remove the user's audit rows explicitly.
  delete from public.api_logs
  where actor_id = target_user_id;

  delete from auth.users
  where id = target_user_id;
end;
$$;

revoke all on function public.delete_own_account() from public;
grant execute on function public.delete_own_account() to authenticated;
