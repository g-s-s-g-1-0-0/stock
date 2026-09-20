# 웹 즉시갱신 범위

최종 갱신: 2026-09-20

관리자 헤더의 즉시갱신 버튼은 현재 페이지에 맞는 GitHub Actions `refresh_scope`를 보낸다. 워크플로/API는 원래 페이지별 scope를 지원했지만, 2026-09-20 이전 UI는 scope를 넘기지 않아 기본값 `analysis`(가치+기술)만 실행됐다.

## 페이지 → scope

| 페이지 | scope | 실제 작업 |
|---|---|---|
| 가치 분석 | `valuation` | valuation |
| 기술 분석 | `technical` | technical |
| 시장 트렌드 | `market-trends` | stock-universe + market-trends |
| 시장 주요 이벤트 | `market-events` | market-events |
| HOME 등 | `analysis` | valuation + technical |

반영 확인도 해당 캐시의 `meta.updatedAt`만 본다. 예전처럼 아무 캐시나 바뀌면 성공으로 치지 않는다.

근거: `web/src/App.tsx:764-794`, `web/src/App.tsx:8997-9019`, `web/api/admin/trigger-refresh.js:3`, `.github/workflows/web-data-refresh.yml:105-114`
