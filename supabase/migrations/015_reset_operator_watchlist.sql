-- 운영자(공용) 관심종목을 빈 상태로 리셋한다.
-- 과거 마이그레이션(012/014)이 단일 tickers 를 가치/스윙 양쪽에 복사하면서
-- 유형별 목록이 기기마다 다르게 갈라지는 동기화 꼬임이 발생했다.
-- 어드민이 새로 등록한 단일 목록을 정본으로 다시 맞추기 위해 운영자 행을 초기화한다.
update public.watchlists
set tickers = '{}',
    tickers_by_type = jsonb_build_object(
      'long_term', '[]'::jsonb,
      'swing', '[]'::jsonb
    )
where scope = 'operator'
  and owner_id is null;
