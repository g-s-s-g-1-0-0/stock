"""Batch cache generation for the web app.

Usage examples:
  python -m calculator.pipeline technical
  python -m calculator.pipeline valuation
  python -m calculator.pipeline market-trends
  python -m calculator.pipeline all
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

from .industry_classification import CATEGORY_VALUES, classify_stock
from .rules import IndicatorRow, evaluate_buy_condition, strategy_display_name
from .sheet_sources import calc_technical_row, fetch_text, fetch_valuation

ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "data" / "cache"
WEB_PUBLIC_API_DIR = ROOT_DIR / "web" / "public" / "api"

NEWS_SOURCES = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://finance.yahoo.com/news/rssindex",
    "https://trends.google.com/trending/rss?geo=US",
]

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MARKET_TREND_MODEL = "llama-3.3-70b-versatile"
CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FAIR_PRICE_UNAVAILABLE_LABEL = "적자 상태라 판단 불가"
PRICE_CHECK_REQUIRED_LABEL = "가격 확인 필요"
MAX_REFRESH_UNIVERSE = int(os.environ.get("MAX_REFRESH_UNIVERSE", "200"))

DEFAULT_UNIVERSE = [
    {"ticker": "005930", "name": "삼성전자", "market": "KR"},
    {"ticker": "NVDA", "name": "NVIDIA", "market": "US"},
    {"ticker": "AAPL", "name": "Apple", "market": "US"},
    {"ticker": "TSLA", "name": "Tesla", "market": "US"},
    {"ticker": "035420", "name": "NAVER", "market": "KR"},
    {"ticker": "042700", "name": "한미반도체", "market": "KR"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_cache(name: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC_API_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (CACHE_DIR, WEB_PUBLIC_API_DIR):
        (directory / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def read_cache(name: str) -> dict[str, Any]:
    path = CACHE_DIR / f"{name}.json"
    if not path.exists():
        path = WEB_PUBLIC_API_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def read_universe() -> list[dict[str, str]]:
    path = ROOT_DIR / "data" / "universe.json"
    if not path.exists():
        return DEFAULT_UNIVERSE
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_UNIVERSE
    if not isinstance(loaded, list):
        return DEFAULT_UNIVERSE
    return loaded[:MAX_REFRESH_UNIVERSE]


def read_search_universe() -> list[dict[str, Any]]:
    path = ROOT_DIR / "data" / "search_universe.json"
    if not path.exists():
        return read_universe()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return read_universe()
    rows = loaded.get("rows") if isinstance(loaded, dict) else loaded
    if not isinstance(rows, list):
        return read_universe()
    return rows


def fmt_number(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "-"
    try:
        if value != value:
            return "-"
    except TypeError:
        return "-"
    return f"{float(value):,.{decimals}f}"


def fmt_price(value: Any, market: str) -> str:
    if value is None:
        return "-"
    if market == "KR":
        return f"₩{round(float(value)):,.0f}"
    return f"${float(value):,.2f}"


def fmt_fear_greed_score(value: Any) -> str:
    try:
        return str(round(float(value)))
    except (TypeError, ValueError):
        return "-"


def fear_greed_rating_label(value: Any) -> str:
    labels = {
        "extreme fear": "극단적 공포",
        "fear": "공포",
        "neutral": "중립",
        "greed": "탐욕",
        "extreme greed": "극단적 탐욕",
    }
    key = str(value or "").strip().lower()
    return labels.get(key, str(value or "-"))


def fetch_cnn_fear_greed_rows() -> list[list[str]]:
    request = urllib.request.Request(
        CNN_FEAR_GREED_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
            "Origin": "https://edition.cnn.com",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    data = payload.get("fear_and_greed", {})
    current_score = fmt_fear_greed_score(data.get("score"))
    previous_close = fmt_fear_greed_score(data.get("previous_close"))

    if current_score == "-":
        return []
    return [
        ["CNN 공포·탐욕지수 당일·전날", f"{current_score} / {previous_close}"],
    ]


def fmt_amount(value: Any, market: str) -> str:
    if value is None:
        return "-"
    if market == "KR":
        return f"₩{round(float(value)):,.0f}"
    return f"${float(value):,.2f}"


def parse_percent(value: Any) -> float | None:
    if not isinstance(value, str) or value.strip() in ("", "-"):
        return None
    cleaned = value.replace("%", "").replace("+", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def rule_of_40(metric: dict[str, str]) -> str:
    growth = parse_percent(metric.get("salesYoyTtm"))
    margin = parse_percent(metric.get("operatingMargin"))
    if growth is None or margin is None:
        return "-"
    return f"{growth + margin:.2f}%"


def stock_industry(stock: dict[str, Any], metric: dict[str, str] | None = None) -> str:
    classified = classify_stock(stock)
    if classified["industry"] != "-":
        return classified["industry"]
    candidates = [
        metric.get("industry") if metric else None,
        stock.get("industry"),
        stock.get("rawIndustry"),
        stock.get("products"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() and candidate.strip() != "-":
            return candidate.strip()
    return "-"


def parse_amount(value: Any) -> float | None:
    if not isinstance(value, str) or value.strip() in ("", "-"):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def stock_category(stock: dict[str, Any]) -> str:
    category = stock.get("category")
    if isinstance(category, str) and category in CATEGORY_VALUES:
        return category
    return classify_stock(stock)["category"]


def fair_price_unavailable_reason(metric: dict[str, str]) -> str | None:
    eps = parse_amount(metric.get("epsTtm"))
    if eps is not None and eps <= 0:
        return "loss_making"
    return None


def fair_price_range(stock: dict[str, Any], metric: dict[str, str]) -> str:
    category = stock_category(stock)
    eps = parse_amount(metric.get("epsTtm"))
    if fair_price_unavailable_reason(metric) == "loss_making":
        return FAIR_PRICE_UNAVAILABLE_LABEL
    if category not in ("가치주", "혼합주", "성장주") or eps is None:
        return "-"

    if category == "가치주":
        return f"{fmt_price(eps * 10, stock['market'])} ~ {fmt_price(eps * 15, stock['market'])}"
    if category == "혼합주":
        return f"{fmt_price(eps * 15, stock['market'])} ~ {fmt_price(eps * 25, stock['market'])}"

    growth = parse_percent(metric.get("salesYoyTtm"))
    if growth is None:
        return "-"
    if growth < 10:
        low_multiple, high_multiple = 15, 20
    elif growth < 20:
        low_multiple, high_multiple = 20, 30
    elif growth < 30:
        low_multiple, high_multiple = 30, 40
    elif growth < 50:
        low_multiple, high_multiple = 40, 50
    else:
        low_multiple, high_multiple = 50, 70
    return f"{fmt_price(eps * low_multiple, stock['market'])} ~ {fmt_price(eps * high_multiple, stock['market'])}"


def price_validation_reason(stock: dict[str, Any], current_price: str, fair_price: str) -> str | None:
    current = parse_amount(current_price)
    parts = [parse_amount(part) for part in fair_price.split("~")]
    if current is None or len(parts) != 2 or parts[0] is None or parts[1] is None:
        return None
    low, high = parts
    if low <= 0 or high <= 0:
        return None
    # A common sheet failure is ticker collision: a US ticker such as STX can pick up
    # a Korean stock price, then get formatted as USD. Block absurdly distant values.
    if current > high * 5 or current < low / 5:
        return "price_outlier"
    return None


def valuation_from_price_range(current_price: str, fair_price: str, price_reason: str | None = None) -> str:
    current = parse_amount(current_price)
    parts = [parse_amount(part) for part in fair_price.split("~")]
    if fair_price == FAIR_PRICE_UNAVAILABLE_LABEL or price_reason == "price_outlier":
        return "판단 불가"
    if current is None or len(parts) != 2 or parts[0] is None or parts[1] is None:
        return "보통"
    low, high = parts
    if current < low:
        return "저평가"
    if current > high:
        return "고평가"
    return "보통"


def latest_technical_row(stock: dict[str, str]) -> dict[str, str] | None:
    row = calc_technical_row(stock["ticker"])
    price = float(row["close"])
    ind = IndicatorRow(
        stock_name=stock["ticker"],
        current_price=price,
        ma200=row["ma200"],
        rsi=row["rsi"],
        cci=row["cci"],
        macd_hist=row["macdHist"],
        macd_hist_d1=row["macdHistD1"],
        macd_hist_d2=row["macdHistD2"],
        pct_b=row["pctB"],
        pct_b_low=row["pctBLow"],
        bb_width=row["bbWidth"],
        bb_width_d1=row["bbWidthD1"],
        bb_width_avg60=row["bbWidthAvg60"],
        vol_ratio=row["volRatio"],
        plus_di=row["plusDI"],
        minus_di=row["minusDI"],
        adx=row["adx"],
        adx_d1=row["adxD1"],
        lr_slope=row["lrSlope"],
        lr_trendline=row["lrTrendline"],
        candle_low=row["low"],
    )
    buy = evaluate_buy_condition(ind, vix=None, ixic_dist=None, ixic_filter_active=False)
    strategy = buy["strategyName"] if buy["entryTriggered"] else "-"
    return {
        "ticker": stock["ticker"],
        "name": stock["name"],
        "market": stock["market"],
        "updatedAt": now_iso(),
        "currentPrice": fmt_price(price, stock["market"]),
        "opinion": "매수" if buy["entryTriggered"] else "관망",
        "entryStrategy": strategy,
        "RSI (D)": fmt_number(row["rsi"]),
        "RSI (D-1)": fmt_number(row["rsiD1"]),
        "RSI Signal": fmt_number(row["rsiSignal"]),
        "RSI 기울기": fmt_number(row["rsiSlope"]),
        "CCI (D)": fmt_number(row["cci"]),
        "CCI (D-1)": fmt_number(row["cciD1"]),
        "CCI Signal": fmt_number(row["cciSignal"]),
        "CCI 기울기": fmt_number(row["cciSlope"]),
        "MACD (12, 26, D)": fmt_number(row["macd"]),
        "MACD (12, 26, D-1)": fmt_number(row["macdD1"]),
        "MACD Signal": fmt_number(row["macdSignal"]),
        "MACD Histogram (D)": fmt_number(row["macdHist"]),
        "M - H (D-1)": fmt_number(row["macdHistD1"]),
        "M - H (D-2)": fmt_number(row["macdHistD2"]),
        "MACD 기울기": fmt_number(row["macdHist"] - row["macdHistD1"]),
        "+DI (DMI, 14)": fmt_number(row["plusDI"]),
        "-DI (DMI, 14)": fmt_number(row["minusDI"]),
        "ADX (14, D)": fmt_number(row["adx"]),
        "ADX (14, D-1)": fmt_number(row["adxD1"]),
        "ADX (14, D-2)": fmt_number(row["adxD2"]),
        "ADX 기울기": fmt_number(row["adxSlope"]),
        "Candle Open": fmt_price(row["open"], stock["market"]),
        "C - High": fmt_price(row["high"], stock["market"]),
        "C - Low": fmt_price(row["low"], stock["market"]),
        "C - Close": fmt_price(row["close"], stock["market"]),
        "C - Volume": f"{int(row['volume']):,}",
        "아래꼬리 길이": fmt_amount(row["lowerTail"], stock["market"]),
        "위꼬리 길이": fmt_amount(row["upperTail"], stock["market"]),
        "몸통 길이": fmt_amount(row["bodyLength"], stock["market"]),
        "거래량 (D)": f"{int(row['volume']):,}",
        "거래량 (D-1)": f"{int(row['prevVolume']):,}",
        "20일 평균 대비 거래량 (D)": f"{row['volRatio20'] * 100:.0f}%",
        "절대 거래량 (D)": f"{int(row['tradeValue']):,}",
        "볼린저밴드 %B (종가)": fmt_number(row["pctB"]),
        "볼린저밴드 %B (저가)": fmt_number(row["pctBLow"]),
        "볼린저밴드 Peak (D)": fmt_number(row["pctBPeak"]),
        "볼린저밴드 Peak (D-1)": fmt_number(row["pctBPeakD1"]),
        "볼린저밴드 폭 (D)": fmt_number(row["bbWidth"]),
        "볼린저밴드 폭 (D-1)": fmt_number(row["bbWidthD1"]),
        "지난 60일 볼린저밴드 폭 평균": fmt_number(row["bbWidthAvg60"]),
        "현재가": fmt_price(row["close"], stock["market"]),
        "5일 이동평균선": fmt_price(row["ma5"], stock["market"]),
        "20일 이동평균선": fmt_price(row["ma20"], stock["market"]),
        "60일 이동평균선": fmt_price(row["ma60"], stock["market"]),
        "144일 이동평균선": fmt_price(row["ma144"], stock["market"]),
        "200일 이동평균선": fmt_price(row["ma200"], stock["market"]),
        "120일 저가 회귀 추세선": fmt_price(row["lrTrendline"], stock["market"]),
        "실적발표일 (한국 시간 기준)": "-",
        "진입가": "-",
        "진입일": "-",
        "진입 전략": strategy,
    }


def build_technical_cache(universe: list[dict[str, str]] | None = None) -> dict[str, Any]:
    rows: dict[str, dict[str, str]] = read_cache("technical").get("rows", {})
    errors: list[dict[str, str]] = []
    market_snapshot = [
        ["시장 주요 이벤트", "당분간 없음"],
    ]
    try:
        market_snapshot.extend(fetch_cnn_fear_greed_rows())
    except Exception as exc:  # noqa: BLE001 - external market data should not block refresh
        errors.append({"ticker": "CNN_FEAR_GREED", "error": str(exc)})

    for stock in (universe or read_universe())[:MAX_REFRESH_UNIVERSE]:
        try:
            row = latest_technical_row(stock)
            if row:
                rows[stock["ticker"]] = row
        except Exception as exc:  # noqa: BLE001 - batch should preserve partial success
            errors.append({"ticker": stock["ticker"], "error": str(exc)})
    return {
        "meta": {
            "kind": "technical",
            "schedule": "0 */2 * * *",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso() if rows else None,
            "failedReason": "; ".join(f"{e['ticker']}: {e['error']}" for e in errors) if errors else None,
        },
        "marketSnapshot": market_snapshot,
        "rows": rows,
        "errors": errors,
    }


def build_valuation_cache(universe: list[dict[str, str]] | None = None) -> dict[str, Any]:
    columns = [
        "marketCap", "sales", "salesQoq", "salesYoyTtm", "salesPastYears",
        "currentRatio", "debtToEquity", "priceToFreeCashFlow", "priceToSales",
        "per", "pbr", "roe", "peg", "sharesOutstanding", "grossMargin",
        "operatingMargin", "epsTtm", "epsNextYear", "epsQoq", "industry",
    ]
    rows = read_cache("valuation").get("rows", {})
    errors: list[dict[str, str]] = []
    for stock in (universe or read_universe())[:MAX_REFRESH_UNIVERSE]:
        try:
            values = fetch_valuation(stock["ticker"])
            metric = dict(zip(columns, values))
            metric["industry"] = stock_industry(stock, metric)
            metric["ruleOf40"] = rule_of_40(metric)
            metric["earningsDate"] = "-"
            rows[stock["ticker"]] = metric
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": stock["ticker"], "error": str(exc)})
    return {
        "meta": {
            "kind": "valuation",
            "schedule": "0 0 * * *",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso() if rows else None,
            "failedReason": "; ".join(f"{e['ticker']}: {e['error']}" for e in errors) if errors else None,
        },
        "rows": rows,
        "errors": errors,
    }


def build_stocks_cache() -> dict[str, Any]:
    technical_rows = read_cache("technical").get("rows", {})
    valuation_rows = read_cache("valuation").get("rows", {})
    rows = []
    for stock in read_search_universe():
        technical = technical_rows.get(stock["ticker"], {})
        valuation = valuation_rows.get(stock["ticker"], {})
        fair_price_reason = fair_price_unavailable_reason(valuation)
        fair_price = fair_price_range(stock, valuation)
        current_price = technical.get("currentPrice", "-")
        price_reason = price_validation_reason(stock, current_price, fair_price)
        opinion_blocked = fair_price_reason == "loss_making" or price_reason == "price_outlier"
        rows.append({
            "ticker": stock["ticker"],
            "name": stock["name"],
            "market": stock["market"],
            "fairPrice": fair_price,
            "fairPriceReason": fair_price_reason,
            "currentPrice": current_price,
            "currentPriceReason": price_reason,
            "valuation": valuation_from_price_range(current_price, fair_price, price_reason),
            "opinion": "-" if opinion_blocked else technical.get("opinion", "관망"),
            "strategies": [] if opinion_blocked else [technical["진입 전략"]] if technical.get("진입 전략") not in (None, "-") else [],
            "category": stock_category(stock),
            "industry": stock_industry(stock, valuation),
            "updatedAt": technical.get("updatedAt", now_iso()),
        })
    return {
        "meta": {
            "kind": "stocks",
            "schedule": "derived",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        },
        "rows": rows,
    }


def sanitize_market_trend_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    replacements = {
        "芯": "칩",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    sanitized = re.sub(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", "", value)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def normalize_market_trend_summary(value: Any) -> str:
    sanitized = sanitize_market_trend_text(value)
    if not isinstance(sanitized, str):
        return ""
    replacements = [
        (r"모습을 보였다\.$", "모습을 보였습니다."),
        (r"부상했다\.$", "부상했습니다."),
        (r"커지고 있다\.$", "커지고 있습니다."),
        (r"두드러진다\.$", "두드러집니다."),
        (r"나타났다\.$", "나타났습니다."),
        (r"상승했다\.$", "상승했습니다."),
        (r"하락했다\.$", "하락했습니다."),
        (r"집중됐다\.$", "집중됐습니다."),
        (r"이어졌다\.$", "이어졌습니다."),
        (r"받았다\.$", "받았습니다."),
    ]
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


def sanitize_market_trend_rows(rows: list[Any]) -> list[Any]:
    sanitized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sanitized_rows.append({
            **row,
            "date": sanitize_market_trend_text(row.get("date", "")),
            "ranks": [sanitize_market_trend_text(rank) for rank in row.get("ranks", []) if isinstance(rank, str)],
            "summary": normalize_market_trend_summary(row.get("summary", "")),
        })
    return sanitized_rows


def fetch_market_trend_news() -> str:
    titles: list[str] = []
    for url in NEWS_SOURCES:
        try:
            html = fetch_text(url)
        except Exception:  # noqa: BLE001 - one broken feed should not block the weekly update
            continue

        matches = re.findall(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        for raw_title in matches[1:25]:
            title = unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", raw_title)).strip()
            title = re.sub(r"\s+", " ", title)
            if title:
                titles.append(title)

    return "\n".join(titles)


def parse_market_trend_analysis(text: str) -> dict[str, Any]:
    ranks: list[str] = []
    summary = ""

    for line in text.splitlines():
        rank_match = re.match(r"^\s*(\d+)위:\s*(.+?)\s*\|\s*(.+?)\s*$", line)
        if rank_match:
            ranks.append(f"{rank_match.group(2).strip()} | {rank_match.group(3).strip()}")
            continue

        summary_match = re.match(r"^\s*요약:\s*(.+?)\s*$", line)
        if summary_match:
            summary = summary_match.group(1).strip()

    return {
        "date": datetime.now().astimezone().strftime("%Y.%m.%d"),
        "ranks": ranks[:10],
        "summary": summary,
    }


def analyze_market_trends_with_groq(news_text: str, api_key: str) -> dict[str, Any]:
    prompt = f"""다음은 이번 주 미국 금융·기술 뉴스 헤드라인입니다.
주식 시장에서 현재 가장 주목받는 섹터/테마를 1위부터 10위까지 순위를 매겨주세요.

[분석 기준]
- 단순 언급 빈도가 아닌, 실제 자금이 몰리고 있는 테마 중심
- "AI 인프라" 같은 넓은 개념도 이번 주 특히 주목받는 세부 요소로 구체화
  예) "AI인프라 | 광통신, 트랜시버" / "AI인프라 | 전력인프라, 데이터센터냉각"
- 각 순위마다 섹터명과 핵심 키워드 3~5개

[출력 형식 — 반드시 이 형식으로만 출력, 다른 설명 없이]
1위: 섹터명 | 키워드1, 키워드2, 키워드3
2위: 섹터명 | 키워드1, 키워드2, 키워드3
...
10위: 섹터명 | 키워드1, 키워드2, 키워드3
요약: 이번 주 전체 시장 분위기 한 줄

[뉴스 헤드라인]
{news_text[:6000]}"""

    request = urllib.request.Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps({
            "model": GROQ_MARKET_TREND_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 1024,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))

    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("Groq 응답에 분석 텍스트가 없습니다.")

    parsed = parse_market_trend_analysis(content)
    if len(parsed["ranks"]) < 10:
        raise RuntimeError("Groq 분석 결과에서 10개 순위를 파싱하지 못했습니다.")
    if not parsed["summary"]:
        raise RuntimeError("Groq 분석 결과에서 시장요약을 파싱하지 못했습니다.")
    return parsed


def upsert_market_trend_row(rows: list[Any], new_row: dict[str, Any]) -> list[Any]:
    sanitized_rows = sanitize_market_trend_rows(rows)
    existing_index = next((index for index, row in enumerate(sanitized_rows) if row.get("date") == new_row["date"]), None)
    if existing_index is None:
        sanitized_rows.append(new_row)
    else:
        sanitized_rows[existing_index] = new_row
    return sanitized_rows[-26:]


def build_market_trends_cache() -> dict[str, Any]:
    existing = read_cache("market-trends")
    rows = sanitize_market_trend_rows(existing.get("rows", [])) if isinstance(existing.get("rows"), list) else []
    api_key = os.environ.get("GROQ_API_KEY", "").strip()

    if not api_key:
        return {
            "meta": {
                **existing.get("meta", {}),
                "kind": "market-trends",
                "schedule": "0 0 * * 1",
                "updatedAt": now_iso(),
                "lastSuccessfulRun": existing.get("meta", {}).get("lastSuccessfulRun"),
                "failedReason": "GROQ_API_KEY 환경변수가 설정되어 있지 않아 기존 시장 트렌드 캐시를 유지했습니다.",
            },
            "rows": rows,
        }

    try:
        news_text = fetch_market_trend_news()
        if not news_text:
            raise RuntimeError("RSS 뉴스 헤드라인을 수집하지 못했습니다.")
        new_row = analyze_market_trends_with_groq(news_text, api_key)
        rows = upsert_market_trend_row(rows, new_row)
    except urllib.error.HTTPError as exc:
        return {
            "meta": {
                **existing.get("meta", {}),
                "kind": "market-trends",
                "schedule": "0 0 * * 1",
                "updatedAt": now_iso(),
                "lastSuccessfulRun": existing.get("meta", {}).get("lastSuccessfulRun"),
                "failedReason": f"Groq API 호출 실패: HTTP {exc.code}",
            },
            "rows": rows,
        }
    except Exception as exc:  # noqa: BLE001 - web cache should preserve the last successful trend data
        return {
            "meta": {
                **existing.get("meta", {}),
                "kind": "market-trends",
                "schedule": "0 0 * * 1",
                "updatedAt": now_iso(),
                "lastSuccessfulRun": existing.get("meta", {}).get("lastSuccessfulRun"),
                "failedReason": str(exc),
            },
            "rows": rows,
        }

    return {
        "meta": {
            "kind": "market-trends",
            "schedule": "0 0 * * 1",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso() if rows else None,
            "failedReason": None,
        },
        "rows": rows,
    }


def build_market_events_cache() -> dict[str, Any]:
    existing = read_cache("market-events")
    if isinstance(existing.get("groups"), list) and existing["groups"]:
        existing["meta"] = {
            **existing.get("meta", {}),
            "kind": "market-events",
            "schedule": "manual",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        }
        return existing

    return {
        "meta": {
            "kind": "market-events",
            "schedule": "manual",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        },
        "groups": [],
    }


def run(job: str, universe: list[dict[str, str]] | None = None) -> None:
    jobs = {
        "stocks": build_stocks_cache,
        "valuation": lambda: build_valuation_cache(universe),
        "technical": lambda: build_technical_cache(universe),
        "market-trends": build_market_trends_cache,
        "market-events": build_market_events_cache,
    }
    selected = ["valuation", "technical", "stocks", "market-trends", "market-events"] if job == "all" else [job]
    for name in selected:
        payload = jobs[name]()
        write_cache(name, payload)
        print(f"wrote {name}: {payload['meta']['updatedAt']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=["all", "stocks", "valuation", "technical", "market-trends", "market-events"])
    args = parser.parse_args()
    run(args.job)


if __name__ == "__main__":
    main()
