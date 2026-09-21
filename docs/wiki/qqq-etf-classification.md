# ETF 산업·가치분석 분류

최종 확인: 2026-09-21

QQQ 같은 이름에 `ETF`가 없는 상장지수형 상품과, Netflix처럼 이름에 `ETF` 부분문자열이 들어가 비ETF가 오분류된 사례를 함께 다룬다.

## QQQ 사례

- 공식 이름: `Invesco QQQ Trust`. 이름에 `ETF`가 없다.
- Finviz 원천산업: `Financial | Exchange Traded Fund`. (`data/search_universe.json` QQQ `rawIndustry`)
- 나스닥 상장 파일 `ETF=Y` → `etfFlag: true`
- `looks_like_etf()`가 `etfFlag`, `Exchange Traded Fund`, `Invesco`+`Trust` 패턴으로 ETF를 판정한다. (`calculator/industry_classification.py`)
- 산업: `ETF, 테마·지수형 상장상품`. 가치분석: `fairPriceReason: etf`, `valuation: 판단 불가`. (`data/cache/stocks.json` QQQ)

## 자가진단 규칙 (`looks_like_etf`)

1. 나스닥/기타 상장 파일 `ETF=Y` → `etfFlag`
2. 이름·`rawIndustry`·`products`에 `\bETF\b`, `\bETN\b`, `Exchange Traded Fund`, `Index Fund`, `상장지수`
3. 발행사 토큰(`Invesco`, `iShares`, `SPDR` 등) + `Trust`/`Fund`/`Shares`/`Index`
4. 인버스·레버리지 ETF 큐레이션(`SOXL` 등)은 기존 산업 라벨 유지

`industry` 필드는 순환 오분류를 막기 위해 ETF 판정 입력에서 제외한다.

## 유니버스 갱신

- `calculator/build_stock_universe.py` `load_us_stocks()`가 상장 파일 ETF 플래그를 보존한다.
- `enrich_stock_industry()`가 ETF면 `etfFlag`를 세우고, 비ETF인데 산업만 ETF 라벨이면 재분류한다.
- `classify_stock()` fallback에서 비ETF 종목의 stale `industry` ETF 라벨은 무시한다. (`industry_classification.py:396`)

2026-09-21 전수조사: `search_universe.json` 약 47건 갱신, `etfFlag` 35건 추가, NFLX·BULL 등 false positive 7건 산업 `-`로 정리.

## 화면

- 백엔드: `calculator/pipeline.py` `is_etf_stock()`, `fair_price_unavailable_reason()`
- 프론트: `web/src/App.tsx` `isEtfStock()` — ETN, Exchange Traded Fund, Index Fund, 상장지수 포함

ETF로 판정되면 적정가 `-`, 밸류 `판단 불가`, 사유 `ETF라 판단 불가`.
