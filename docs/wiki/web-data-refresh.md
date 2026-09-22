# 웹 즉시갱신 범위

최종 갱신: 2026-09-22

## 2시간 기술 갱신 흐름

외부 cron이 `technical` scope로 `/api/admin/trigger-refresh`를 호출하면 GitHub Actions가 돈다. 정시 5분 전(예: 9:55) 트리거 → 러너에서 `technical.json`·`trade-logs.json` 갱신 → **정시까지 대기** → **캐시 push(화면 반영)** → 의견 변경 메일 발송 → `web-notification-state.json`만 별도 push.

2026-09-22 이전에는 메일을 먼저 보내고 캐시를 나중에 push해서, 메일은 왔는데 화면·트레이딩로그는 이전 슬롯(예: 8시) 그대로인 구간이 있었다. 프로덕션은 `web/public/api/*.json`을 GitHub published copy(`/api/cache/` → raw)에서 읽는다.

관리자 HOME 트레이딩로그 = `trade-logs.json`. 일반 계정 = Supabase `personal_trade_logs`(갱신은 같은 `record_web_api_logs.py` 단계).

근거: `.github/workflows/web-data-refresh.yml`, `web/src/api.ts`, `scripts/record_web_api_logs.py`, `OPERATIONS.md`

## 페이지 → scope

| 페이지 | scope | 실제 작업 |
|---|---|---|
| 가치 분석 | `valuation` | valuation |
| 기술 분석 | `technical` | technical |
| 시장 트렌드 | `market-trends` | stock-universe + market-trends |
| 시장 주요 이벤트 | `market-events` | market-events |
| HOME 등 | `analysis` | valuation + technical |

버튼 문구는 `즉시 갱신`으로 두고, 실제 실행 범위만 페이지에 맞춘다. API는 `page` 쿼리/바디를 scope보다 우선한다. HTML은 no-cache라 배포 후 새로고침하면 새 번들을 받는다.

근거: GitHub Actions `35496196604` (`case "analysis"`, `Resolved refresh tasks: valuation technical`), `web/src/App.tsx:764-794`, `web/api/admin/trigger-refresh.js:29-44`, `web/vercel.json`

## 주간 트렌드 메일

- 발송 창은 KST 월요일 00:00~03:00이다. 같은 계정·같은 리포트 날짜는 `weeklyTrend` sentKeys로 한 번만 보낸다.
- 2026-09-21 00:01 KST(`35518206006`, 외부 `workflow_dispatch` · scope `market-trends`)가 `Sent weekly trend notifications: 2 (already_sent=0)`로 수신자 2명에게 보냈다. 지연된 GitHub 주간 cron(`35526973342`, 02:47 KST)은 `already_sent=2`로 건너뛰었다.
- 같은 시각에 일간 cron과 주간 cron이 겹쳐 두 번 트리거된다. 이번엔 두 번째가 `valuation`만 돌아 트렌드 메일은 추가 발송하지 않았다.
- 수신자 중복 제거는 `owner_id` 기준이라, 계정이 둘이면 같은 리포트가 두 통이다.
- 2026-09-21 수신자는 관리자 `gssg.rich100@gmail.com`(`a15b9df6-…`, 스윙)과 일반 계정 `pretotyper.sth@gmail.com`(`9fb8fefb-…`, 장기, 2026-08-23 생성)이다. 둘 다 `weeklyTrendReport`가 켜져 있고 `recipientEmail` 덮어쓰기는 없다.

근거: GitHub Actions `35518206006`, `35526973342`, `35527036311`; `scripts/web_refresh_notifications.py`의 `send_weekly_trend_notifications`, `dedupe_recipients`
