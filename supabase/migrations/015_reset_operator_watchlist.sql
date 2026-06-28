-- 운영자(공용) 관심종목은 단일 tickers 목록을 정본으로 유지한다.
-- 과거 마이그레이션(012/014)이 단일 tickers 를 가치/스윙 양쪽에 복사하면서
-- 유형별 목록이 기기마다 다르게 갈라지는 동기화 꼬임이 발생했다.
-- 초기화하지 말고 현재 서버 tickers 를 기준으로 유형별 캐시만 맞춘다.
update public.watchlists
set tickers_by_type = jsonb_build_object(
  'long_term', coalesce(to_jsonb(tickers), '[]'::jsonb),
  'swing', coalesce(to_jsonb(tickers), '[]'::jsonb)
)
where scope = 'operator'
  and owner_id is null;
