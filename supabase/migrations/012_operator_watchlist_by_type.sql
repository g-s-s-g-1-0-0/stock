-- 운영자(공수성가) 관심종목을 투자 성향(가치/스윙)별로 저장하기 위한 컬럼.
-- 기존 단일 tickers 컬럼은 활성 유형의 목록으로 계속 유지하고,
-- tickers_by_type 에 유형별 전체 목록을 보관해 일반 계정이 자신의 성향에 맞는 목록만 가져올 수 있게 한다.
alter table public.watchlists
  add column if not exists tickers_by_type jsonb;
