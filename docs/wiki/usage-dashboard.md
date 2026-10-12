# 사용 현황

로그인 사용자가 제품 화면을 열면 서울 날짜 기준으로 사용자·화면·날마다 한 번 `usage_events`에 남긴다. 관리자 계정과 로그인하지 않은 방문은 집계하지 않는다.

D+N은 가입일로부터 N번째 서울 날짜에 방문이 있으면 재방문이다. 7일 내 재방문은 가입 다음 날부터 7일째까지 중 하루라도 방문한 경우다. 기록 시작일보다 앞선 날짜는 분모에서 뺀다.

어드민만 `/dashboard`와 상단 사용 현황에서 본다. 표는 `supabase/migrations/017_usage_events.sql`을 적용한 뒤 쌓인다.

근거: `web/src/usageMetrics.ts`, `web/src/UsageDashboard.tsx`, `web/src/App.tsx`, `supabase/migrations/017_usage_events.sql`, `web/vercel.json` (2026-10-12)
