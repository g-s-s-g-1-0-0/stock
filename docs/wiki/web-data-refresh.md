# 웹 즉시갱신 범위

최종 갱신: 2026-09-20

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
