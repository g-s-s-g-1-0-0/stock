-- 운영자(공수성가) 관심종목을 투자 성향(가치/스윙)별로 저장하기 위한 컬럼.
-- 기존 단일 tickers 컬럼은 활성 유형의 목록으로 계속 유지하고,
-- tickers_by_type 에 유형별 전체 목록을 보관해 일반 계정이 자신의 성향에 맞는 목록만 가져올 수 있게 한다.
alter table public.watchlists
  add column if not exists tickers_by_type jsonb;

-- 컬럼 추가 직후, 기존 단일 tickers(현재 서버 기준 목록)를 두 성향에 동일하게 채워
-- 기기 간 동기화의 시작 기준을 서버 값으로 통일한다. 이미 값이 있는 행은 건드리지 않는다.
update public.watchlists
set tickers_by_type = jsonb_build_object(
  'long_term', coalesce(to_jsonb(tickers), '[]'::jsonb),
  'swing', coalesce(to_jsonb(tickers), '[]'::jsonb)
)
where tickers_by_type is null;
