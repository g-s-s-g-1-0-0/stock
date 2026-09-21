# QQQ 산업·가치분석 오분류

최종 확인: 2026-09-21

QQQ는 나스닥 100을 추종하는 ETF다. 라이브 화면에 보이는 `금융, 은행·자산운용·증권`과 가치분석 `-`/`보통`은 그 사실이 아니라, ETF로 인식하지 못한 결과다.

## 무엇이 들어오나

- 공식 이름: `Invesco QQQ Trust`. 이름에 `ETF`가 없다. (`data/cache/stocks.json` QQQ 행)
- Finviz 원천산업: `Financial | Exchange Traded Fund`. (`data/search_universe.json` QQQ `rawIndustry`)
- 키워드 `Financial`이 `금융, 은행·자산운용·증권`으로 매핑된다. (`calculator/industry_classification.py` KEYWORD_RULES)
- Finviz 문구 `Exchange Traded Fund`에는 부분문자열 `ETF`가 없어서, ETF 키워드 규칙도 안 탄다.
- ETF 판정은 이름·카테고리·산업에 `ETF`가 있는지, 또는 `fairPriceReason == etf`인지만 본다. (`calculator/pipeline.py` `is_etf_stock`, `web/src/App.tsx` `isEtfStock`)
- 그래서 QQQ는 `fairPriceReason: null`, 적정가 `-`, 밸류에이션 `보통`이다. PER·EPS 등도 `-`다. (`data/cache/valuation.json` QQQ)
- 현재가 `$722.10`(2026-09-18 종가 기준)은 시세 피드 값이다. 여기만 ETF와 무관하게 맞다.

비교: SOXL 이름은 `... ETF`라서 `fairPriceReason: etf`, 화면은 `ETF라 판단 불가`, 산업은 `반도체 레버리지 ETF`다.

## 왜 기업 가치처럼 보이나

적정가가 `-`인 이유는 ETF라서가 아니라 EPS가 없어서다. 비교할 가격 범위가 없으면 밸류에이션은 `보통`으로 떨어진다. (`calculator/pipeline.py` `fair_price_range`, `valuation_from_price_range`)

화면의 `ETF라 판단 불가`는 프론트가 ETF로 인식했을 때만 붙는다. QQQ는 그 분기를 타지 않는다.
