-- UI preference only: retain all per-type watchlists, trades and allocation settings.
update public.user_settings set investment_type = 'long_term'
where investment_type is distinct from 'long_term';
alter table public.user_settings alter column investment_type set default 'long_term';
-- Prevent older clients from re-enabling swing while maintenance is active.
create or replace function public.enforce_investment_maintenance()
returns trigger language plpgsql set search_path = public as $$
begin
  new.investment_type := 'long_term';
  return new;
end;
$$;
create trigger investment_maintenance before insert or update on public.user_settings
for each row execute function public.enforce_investment_maintenance();
