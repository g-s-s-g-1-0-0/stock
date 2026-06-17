-- Keep personal/operator watchlists synchronized across devices by ensuring
-- every row has the investment-type map used by the web app.
alter table public.watchlists
  add column if not exists tickers_by_type jsonb;

alter table public.watchlists
  alter column tickers_by_type set default jsonb_build_object(
    'long_term', '[]'::jsonb,
    'swing', '[]'::jsonb
  );

update public.watchlists
set tickers_by_type = jsonb_build_object(
  'long_term', coalesce(to_jsonb(tickers), '[]'::jsonb),
  'swing', coalesce(to_jsonb(tickers), '[]'::jsonb)
)
where tickers_by_type is null;
