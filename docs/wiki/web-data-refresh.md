# 웹 즉시갱신 범위

최종 갱신: 2026-09-21

관리자 헤더의 즉시갱신 버튼은 현재 페이지에 맞는 GitHub Actions `refresh_scope`를 보낸다. 워크플로/API는 원래 페이지별 scope를 지원했지만, UI가 기본값 `analysis`(가치+기술)만 보내 시장 트렌드·이벤트가 빠졌다.

2026-09-20 16:11 KST 클릭은 이미 수정 커밋 `8cf4c583` 위에서 돌았지만 입력은 여전히 `analysis`였다. 열린 탭이 이전 번들(`index-BwP8r0WL.js`)을 들고 있었고, 새 번들(`index-CFbummpT.js`)은 그 직후에야 HTML에 붙었다. 가치분석 `updatedAt`은 당일 자정으로 고정돼 기술분석만 바뀐 것처럼 보인다.

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
