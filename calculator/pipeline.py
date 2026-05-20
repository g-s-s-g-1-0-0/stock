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
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .industry_classification import CATEGORY_VALUES, classify_stock, summarize_industry
from .market_regime import build_qqq_market_state, qqq_recent_ma200_min_distance
from .rules import IndicatorRow, compute_nasdaq_filter_active, evaluate_buy_condition, strategy_display_name
from .sheet_sources import USER_AGENT, calc_rsi, calc_technical_row, fetch_ohlcv, fetch_text, fetch_us_extended_price, fetch_us_ohlcv, fetch_valuation

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
GROQ_MARKET_TREND_MODEL = os.environ.get("GROQ_MARKET_TREND_MODEL", "").strip() or "llama-3.3-70b-versatile"
CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FAIR_PRICE_UNAVAILABLE_LABEL = "적자 상태라 판단 불가"
MAX_REFRESH_UNIVERSE = int(os.environ.get("MAX_REFRESH_UNIVERSE", "200"))
KST = ZoneInfo("Asia/Seoul")

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def publish_iso(default: str | None = None) -> str:
    raw_publish_at = os.environ.get("WEB_REFRESH_PUBLISH_AT", "").strip()
    if not raw_publish_at:
        return default or now_iso()
    try:
        publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
    except ValueError:
        return default or now_iso()
    return publish_at.astimezone(timezone.utc).isoformat(timespec="seconds")


def clean_stock_name(name: Any) -> str:
    value = str(name or "").strip()
    if not value:
        return "-"

    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+-\s*$", "", value).strip()

    for marker in (
        " American Depositary",
        " Depositary Shares",
        " Class A Common Stock",
        " Class B Common Stock",
        " Common Stock",
        " common shares",
        " ordinary shares",
        " ADS",
    ):
        if marker in value:
            value = value.split(marker, 1)[0].strip()

    value = re.sub(r"\bWhen-Issued\b", "", value, flags=re.IGNORECASE).strip(" ,-")
    value = re.sub(r"\s+-\s*$", "", value).strip()

    suffix_patterns = (
        r",?\s+Incorporated\.?$",
        r",?\s+Corporation\.?$",
        r",?\s+Corp\.?$",
        r",?\s+Limited\.?$",
        r",?\s+Ltd\.?$",
        r",?\s+Inc\.?$",
        r",?\s+N\.V\.?$",
        r",?\s+Co\.?$",
    )
    changed = True
    while changed:
        changed = False
        for pattern in suffix_patterns:
            cleaned = re.sub(pattern, "", value, flags=re.IGNORECASE).strip(" ,-")
            if cleaned != value and cleaned:
                value = cleaned
                changed = True

    return value or "-"


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


def parse_market_event_date(value: Any) -> date | None:
    match = re.match(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})$", str(value or "").strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def current_market_event_label(payload: dict[str, Any] | None = None, today: date | None = None) -> str:
    payload = payload if payload is not None else read_cache("market-events")
    groups = payload.get("groups") if isinstance(payload, dict) else []
    if not isinstance(groups, list):
        return "당분간 없음"

    today = today or datetime.now(KST).date()
    active_titles: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = str(group.get("title") or "").strip()
        entries = group.get("entries")
        if not title or not isinstance(entries, list):
            continue
        if any(isinstance(entry, dict) and parse_market_event_date(entry.get("date")) == today for entry in entries):
            if title not in active_titles:
                active_titles.append(title)

    return ", ".join(active_titles) if active_titles else "당분간 없음"


def has_value(value: Any) -> bool:
    return str(value or "").strip() not in ("", "-")


def is_invalid_cached_value(key: str, value: Any) -> bool:
    text = str(value or "").strip()
    return key == "marketCap" and text.endswith("%")


def preserve_existing_values(new_row: dict[str, str], existing_row: dict[str, Any]) -> dict[str, str]:
    if not existing_row:
        return new_row
    merged: dict[str, str] = {}
    for key, value in new_row.items():
        previous_value = existing_row.get(key)
        should_preserve = (
            not has_value(value)
            and has_value(previous_value)
            and not is_invalid_cached_value(key, previous_value)
        )
        merged[key] = str(previous_value if should_preserve else value)
    return merged


def read_universe() -> list[dict[str, str]]:
    path = ROOT_DIR / "data" / "universe.json"
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
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


def fetch_weekly_rsi(symbol: str = "QQQ") -> float:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol)
        + "?range=2y&interval=1wk"
    )
    payload = json.loads(fetch_text(url))
    result = payload.get("chart", {}).get("result", [{}])[0]
    closes = [
        float(value)
        for value in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if value is not None
    ]
    rsi_values = calc_rsi(closes)
    if not rsi_values:
        raise RuntimeError(f"{symbol} weekly RSI source has insufficient data.")
    return round(rsi_values[-1], 2)


def fmt_signed_percent(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "-"
    if parsed != parsed:
        return "-"
    return f"{parsed:+.2f}%"


def fmt_signed_number(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "-"
    if parsed != parsed:
        return "-"
    return f"{parsed:+.2f}"


def qqq_market_state_snapshot() -> dict[str, Any]:
    qqq = calc_technical_row("QQQ")
    qqq_rows = fetch_us_ohlcv("QQQ", range_value="2y")
    weekly_rsi = fetch_weekly_rsi("QQQ")
    recent_min_dist = qqq_recent_ma200_min_distance(qqq_rows)
    state = build_qqq_market_state(qqq, recent_min_dist=recent_min_dist, weekly_rsi=weekly_rsi)
    state.update({
        "ma20": qqq.get("ma20"),
        "ma60": qqq.get("ma60"),
        "ma144": qqq.get("ma144"),
    })
    return state


def build_market_snapshot() -> tuple[list[list[str]], dict[str, Any], float | None]:
    market_event = current_market_event_label()
    rows = [
        ["시장 주요 이벤트", market_event],
    ]
    vix_today: float | None = None

    try:
        vix_rows = fetch_ohlcv("^VIX")
        vix_today = float(vix_rows[-1]["close"])
        rows.append([
            "VIX (변동성지수) 당일·전날",
            f"{fmt_number(vix_rows[-1]['close'])} / {fmt_number(vix_rows[-2]['close'])}",
        ])
    except Exception as exc:  # noqa: BLE001 - snapshot rows are best-effort
        rows.append(["VIX (변동성지수) 당일·전날", f"수집 실패: {exc}"])

    try:
        rows.extend(fetch_cnn_fear_greed_rows())
    except Exception as exc:  # noqa: BLE001
        rows.append(["CNN 공포·탐욕지수 당일·전날", f"수집 실패: {exc}"])

    try:
        tnx_rows = fetch_ohlcv("^TNX")
        rows.append(["미국 10년물 금리", fmt_number(tnx_rows[-1]["close"], 3)])
    except Exception as exc:  # noqa: BLE001
        rows.append(["미국 10년물 금리", f"수집 실패: {exc}"])

    try:
        dollar_rows = fetch_ohlcv("DX-Y.NYB")
        rows.append(["달러 인덱스", fmt_number(dollar_rows[-1]["close"])])
    except Exception as exc:  # noqa: BLE001
        rows.append(["달러 인덱스", f"수집 실패: {exc}"])

    qqq_state: dict[str, Any] = {}
    try:
        qqq_state = qqq_market_state_snapshot()
        rows.extend([
            ["QQQ 주봉 RSI (14)", fmt_number(qqq_state.get("weeklyRsi"))],
            ["QQQ 일봉 RSI (14, 당일)", fmt_number(qqq_state.get("dailyRsi"))],
            ["QQQ 일봉 RSI (14, 전날)", fmt_number(qqq_state.get("dailyRsiPrev"))],
            ["QQQ MACD Histogram (D/D-1/D-2)", " / ".join([
                fmt_signed_number(qqq_state.get("macdHist")),
                fmt_signed_number(qqq_state.get("macdHistD1")),
                fmt_signed_number(qqq_state.get("macdHistD2")),
            ])],
            ["QQQ 60거래일 최저 이격도", fmt_signed_percent(qqq_state.get("recent60MinPremiumPercent"))],
            ["QQQ 매수 차단 기준", f">{fmt_signed_percent(qqq_state.get('buyBlockMax'))}"],
            ["나스닥 (QQQ, 당일)", fmt_number(qqq_state.get("currentPrice"))],
            ["나스닥 (QQQ, 20일 이동평균선)", fmt_number(qqq_state.get("ma20"))],
            ["나스닥 (QQQ, 60일 이동평균선)", fmt_number(qqq_state.get("ma60"))],
            ["나스닥 (QQQ, 144일 이동평균선)", fmt_number(qqq_state.get("ma144"))],
            ["나스닥 (QQQ, 200일 이동평균선)", fmt_number(qqq_state.get("ma200"))],
            ["나스닥 (QQQ, 200일선 이격도)", fmt_signed_percent(qqq_state.get("premiumPercent"))],
        ])
    except Exception as exc:  # noqa: BLE001
        rows.append(["나스닥 (QQQ)", f"수집 실패: {exc}"])

    return rows, qqq_state, vix_today


def build_market_snapshot_rows() -> list[list[str]]:
    rows, _, _ = build_market_snapshot()
    return rows


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
            return summarize_industry(candidate)
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


def valuation_from_price_range(current_price: str, fair_price: str) -> str:
    current = parse_amount(current_price)
    parts = [parse_amount(part) for part in fair_price.split("~")]
    if fair_price == FAIR_PRICE_UNAVAILABLE_LABEL:
        return "판단 불가"
    if current is None or len(parts) != 2 or parts[0] is None or parts[1] is None:
        return "보통"
    low, high = parts
    if current < low:
        return "저평가"
    if current > high:
        return "고평가"
    return "보통"


def latest_technical_row(
    stock: dict[str, str],
    earnings_date: str = "-",
    *,
    qqq_market_state: dict[str, Any] | None = None,
    vix: float | None = None,
    market_event: str = "당분간 없음",
) -> dict[str, str] | None:
    row = calc_technical_row(stock["ticker"])
    price = float(row["close"])
    display_price = price
    if stock["market"] == "US":
        try:
            display_price = fetch_us_extended_price(stock["ticker"]) or price
        except Exception:  # noqa: BLE001 - extended quote is best-effort display data
            display_price = price
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
    ixic_dist = qqq_market_state.get("premiumPercent") if qqq_market_state else None
    nasdaq_buy_block_max = qqq_market_state.get("buyBlockMax") if qqq_market_state else None
    ixic_filter_active = compute_nasdaq_filter_active(ixic_dist)
    buy = evaluate_buy_condition(
        ind,
        vix=vix,
        ixic_dist=ixic_dist,
        ixic_filter_active=ixic_filter_active,
        nasdaq_buy_block_max=nasdaq_buy_block_max,
    )
    event_watch_active = market_event != "당분간 없음"
    opinion = "관망" if event_watch_active else "매수" if buy["entryTriggered"] else "관망"
    opinion_reason = f"이벤트 기간 관망 ({market_event})" if event_watch_active else "-"
    strategy = buy["strategyName"] if buy["entryTriggered"] else "-"
    entry_signal_codes = [
        group
        for group in ("A", "B", "C", "D", "E", "F")
        if all(buy["conditions"].get(group, []))
    ]
    buy_block_label = f"나스닥 상단 차단 아님(≤{float(nasdaq_buy_block_max):.0f}%)" if nasdaq_buy_block_max is not None else "나스닥 상단 차단 아님"
    strategy_labels = {
        "A": ["현재가 > MA200", "MACD 골든크로스", "종가%B > 80", "RSI > 70", "나스닥 강세 필터"],
        "B": ["현재가 < MA200", "VIX >= 30", "RSI < 35 또는 CCI < -150", "LR 추세선 상승", "저가 추세선 터치", buy_block_label],
        "C": ["현재가 > MA200", "전일 BB 스퀴즈", "당일 BB 확장", "거래량 폭발", "종가%B > 55", "MACD Hist > 0", "나스닥 강세 필터"],
        "D": ["현재가 > MA200", "+DI > -DI", "ADX > 30", "ADX 상승", "MACD Hist > 0", "종가%B 30~75", "나스닥 강세 필터"],
        "E": ["현재가 > MA200", "BB폭 압축", "저가%B <= 50", "나스닥 바닥/정상 필터"],
        "F": ["현재가 > MA200", "저가%B <= 3", "나스닥 바닥/정상 필터"],
    }
    condition_summaries = []
    for group, labels in strategy_labels.items():
        values = buy["conditions"].get(group, [])
        passed = sum(1 for value in values if value)
        details = " / ".join(f"{label}:{'통과' if value else '실패'}" for label, value in zip(labels, values))
        condition_summaries.append(f"{group}그룹 {passed}/{len(values)} - {details}")
    market_line = (
        f"시장 국면: {qqq_market_state.get('regimeLabel')} / "
        f"QQQ 이격도 {fmt_signed_percent(qqq_market_state.get('premiumPercent'))} / "
        f"최근 60거래일 최저 {fmt_signed_percent(qqq_market_state.get('recent60MinPremiumPercent'))} / "
        f"매수 차단선 > {fmt_signed_percent(qqq_market_state.get('buyBlockMax'))} / "
        f"이벤트: {market_event}"
    ) if qqq_market_state else "시장 국면: 데이터 없음"
    decision_log = "\n".join([
        f"{stock['ticker']} 최종 판단: {opinion}",
        f"진입 전략: {strategy}",
        market_line,
        *condition_summaries,
    ])
    return {
        "ticker": stock["ticker"],
        "name": clean_stock_name(stock["name"]),
        "market": stock["market"],
        "updatedAt": now_iso(),
        "currentPrice": fmt_price(display_price, stock["market"]),
        "opinion": opinion,
        "opinionReason": opinion_reason,
        "marketEvent": market_event,
        "entryStrategy": strategy,
        "entrySignalCodes": ",".join(entry_signal_codes),
        "entrySignals": ", ".join(strategy_display_name(code) for code in entry_signal_codes),
        "decisionLog": decision_log,
        "conditionSummary": " | ".join(condition_summaries),
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
        "MACD 기울기": fmt_number(row["macdSlope"]),
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
        "거래량 (D)": f"{row['volRatio'] * 100:.0f}%",
        "거래량 (D-1)": f"{row['prevVolRatio'] * 100:.0f}%",
        "20일 평균 대비 거래량 (D)": f"{row['volRatio20'] * 100:.0f}%",
        "절대 거래량 (D)": f"{int(row['volume']):,}",
        "볼린저밴드 %B (종가)": fmt_number(row["pctB"]),
        "볼린저밴드 %B (저가)": fmt_number(row["pctBLow"]),
        "볼린저밴드 Peak (D)": fmt_number(row["pctBPeak"]),
        "볼린저밴드 Peak (D-1)": fmt_number(row["pctBPeakD1"]),
        "볼린저밴드 폭 (D)": fmt_number(row["bbWidth"]),
        "볼린저밴드 폭 (D-1)": fmt_number(row["bbWidthD1"]),
        "지난 60일 볼린저밴드 폭 평균": fmt_number(row["bbWidthAvg60"]),
        "현재가": fmt_price(display_price, stock["market"]),
        "5일 이동평균선": fmt_price(row["ma5"], stock["market"]),
        "20일 이동평균선": fmt_price(row["ma20"], stock["market"]),
        "60일 이동평균선": fmt_price(row["ma60"], stock["market"]),
        "144일 이동평균선": fmt_price(row["ma144"], stock["market"]),
        "200일 이동평균선": fmt_price(row["ma200"], stock["market"]),
        "120일 저가 회귀 추세선": fmt_price(row["lrTrendline"], stock["market"]),
        "실적발표일 (한국 시간 기준)": earnings_date or "-",
        "진입가": "-",
        "진입일": "-",
        "진입 전략": strategy,
    }


def build_technical_cache(universe: list[dict[str, str]] | None = None) -> dict[str, Any]:
    existing = read_cache("technical")
    existing_meta = existing.get("meta", {}) if isinstance(existing, dict) else {}
    existing_rows = dict(existing.get("rows", {})) if isinstance(existing.get("rows"), dict) else {}
    source_universe = (universe if universe is not None else read_universe())[:MAX_REFRESH_UNIVERSE]
    if not source_universe and existing_rows:
        return {
            **existing,
            "meta": {
                **existing_meta,
                "kind": "technical",
                "updatedAt": publish_iso(),
                "failedReason": "refresh universe is empty; preserved existing technical cache",
            },
        }
    rows: dict[str, dict[str, str]] = {}
    valuation_rows = read_cache("valuation").get("rows", {})
    errors: list[dict[str, str]] = []
    successful_rows = 0
    refreshed_at = publish_iso()
    qqq_market_state: dict[str, Any] = {}
    vix_today: float | None = None
    try:
        market_snapshot, qqq_market_state, vix_today = build_market_snapshot()
    except Exception as exc:  # noqa: BLE001 - external market data should not block refresh
        market_snapshot = [["시장 주요 이벤트", "당분간 없음"]]
        errors.append({"ticker": "CNN_FEAR_GREED", "error": str(exc)})
    market_event = market_snapshot[0][1] if market_snapshot and len(market_snapshot[0]) > 1 else "당분간 없음"

    for stock in source_universe:
        try:
            metric = valuation_rows.get(stock["ticker"], {})
            earnings_date = metric.get("earningsDate", "-") if isinstance(metric, dict) else "-"
            row = latest_technical_row(
                stock,
                earnings_date=earnings_date,
                qqq_market_state=qqq_market_state,
                vix=vix_today,
                market_event=market_event,
            )
            if row:
                rows[stock["ticker"]] = row
                successful_rows += 1
        except Exception as exc:  # noqa: BLE001 - batch should preserve partial success
            if stock["ticker"] in existing_rows:
                rows[stock["ticker"]] = existing_rows[stock["ticker"]]
            errors.append({"ticker": stock["ticker"], "error": str(exc)})
    return {
        "meta": {
            "kind": "technical",
            "schedule": "0 */2 * * *",
            "updatedAt": refreshed_at,
            "lastSuccessfulRun": refreshed_at if successful_rows else existing_meta.get("lastSuccessfulRun"),
            "failedReason": "; ".join(f"{e['ticker']}: {e['error']}" for e in errors) if errors else None,
            "successfulRows": successful_rows,
        },
        "marketSnapshot": market_snapshot,
        "qqqMarketState": qqq_market_state,
        "rows": rows,
        "errors": errors,
    }


def build_valuation_cache(universe: list[dict[str, str]] | None = None) -> dict[str, Any]:
    columns = [
        "marketCap", "sales", "salesQoq", "salesYoyTtm", "salesPastYears",
        "currentRatio", "debtToEquity", "priceToFreeCashFlow", "priceToSales",
        "per", "pbr", "roe", "peg", "sharesOutstanding", "grossMargin",
        "operatingMargin", "epsTtm", "epsNextYear", "epsQoq", "earningsDate", "industry",
    ]
    existing = read_cache("valuation")
    existing_meta = existing.get("meta", {}) if isinstance(existing, dict) else {}
    existing_rows = dict(existing.get("rows", {})) if isinstance(existing.get("rows"), dict) else {}
    source_universe = (universe if universe is not None else read_universe())[:MAX_REFRESH_UNIVERSE]
    if not source_universe and existing_rows:
        return {
            **existing,
            "meta": {
                **existing_meta,
                "kind": "valuation",
                "updatedAt": now_iso(),
                "failedReason": "refresh universe is empty; preserved existing valuation cache",
            },
        }
    rows: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    successful_rows = 0
    refreshed_at = now_iso()
    for stock in source_universe:
        try:
            values = fetch_valuation(stock["ticker"])
            metric = dict(zip(columns, values))
            metric = preserve_existing_values(metric, existing_rows.get(stock["ticker"], {}))
            metric["industry"] = stock_industry(stock, metric)
            metric["ruleOf40"] = rule_of_40(metric)
            metric["earningsDate"] = metric.get("earningsDate") or "-"
            rows[stock["ticker"]] = metric
            successful_rows += 1
        except Exception as exc:  # noqa: BLE001
            if stock["ticker"] in existing_rows:
                rows[stock["ticker"]] = existing_rows[stock["ticker"]]
            errors.append({"ticker": stock["ticker"], "error": str(exc)})
    return {
        "meta": {
            "kind": "valuation",
            "schedule": "0 0 * * *",
            "updatedAt": refreshed_at,
            "lastSuccessfulRun": refreshed_at if successful_rows else existing_meta.get("lastSuccessfulRun"),
            "failedReason": "; ".join(f"{e['ticker']}: {e['error']}" for e in errors) if errors else None,
            "successfulRows": successful_rows,
        },
        "rows": rows,
        "errors": errors,
    }


def build_stock_search_cache() -> dict[str, Any]:
    rows = []
    for stock in read_search_universe():
        rows.append({
            "ticker": stock["ticker"],
            "name": clean_stock_name(stock["name"]),
            "market": stock["market"],
            "category": stock_category(stock),
            "industry": stock_industry(stock, {}),
        })
    return {
        "meta": {
            "kind": "stock-search",
            "schedule": "derived",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        },
        "rows": rows,
    }


def strategy_codes_from_technical(technical: dict[str, Any]) -> list[str]:
    raw = technical.get("entrySignalCodes") or technical.get("entrySignals") or technical.get("entryStrategy") or technical.get("진입 전략")
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw or "").replace("/", ",").split(",")

    codes: list[str] = []
    for value in values:
        code = str(value or "").split(".", 1)[0].strip().upper()
        if code in {"A", "B", "C", "D", "E", "F"} and code not in codes:
            codes.append(code)
    return codes


def stock_strategies_from_technical(technical: dict[str, Any]) -> list[str]:
    codes = strategy_codes_from_technical(technical)
    if codes:
        return [strategy_display_name(code) for code in codes]

    entry_strategy = technical.get("진입 전략") or technical.get("entryStrategy")
    return [entry_strategy] if entry_strategy not in (None, "-") else []


def sync_existing_stock_strategies(rows: list[Any], technical_rows: dict[str, Any]) -> list[Any]:
    synced_rows = []
    for row in rows:
        if not isinstance(row, dict):
            synced_rows.append(row)
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        technical = technical_rows.get(ticker, {})
        if isinstance(technical, dict) and technical:
            synced_rows.append({**row, "strategies": stock_strategies_from_technical(technical)})
        else:
            synced_rows.append(row)
    return synced_rows


def build_stocks_cache(universe: list[dict[str, str]] | None = None) -> dict[str, Any]:
    existing = read_cache("stocks")
    existing_rows = existing.get("rows", []) if isinstance(existing, dict) else []
    source_universe = universe if universe is not None else read_universe()
    if not source_universe and existing_rows:
        technical_rows = read_cache("technical").get("rows", {})
        return {
            **existing,
            "meta": {
                **(existing.get("meta", {}) if isinstance(existing, dict) else {}),
                "kind": "stocks",
                "updatedAt": now_iso(),
                "failedReason": None,
            },
            "rows": sync_existing_stock_strategies(existing_rows, technical_rows if isinstance(technical_rows, dict) else {}),
        }
    technical_rows = read_cache("technical").get("rows", {})
    valuation_rows = read_cache("valuation").get("rows", {})
    search_rows_by_ticker = {
        str(row.get("ticker", "")).strip().upper(): row
        for row in read_search_universe()
        if isinstance(row, dict)
    }
    rows_by_ticker: dict[str, dict[str, Any]] = {}
    for stock in source_universe:
        ticker = str(stock.get("ticker", "")).strip().upper()
        if ticker:
            rows_by_ticker[ticker] = {**search_rows_by_ticker.get(ticker, {}), **stock, "ticker": ticker}

    rows = []
    for stock in rows_by_ticker.values():
        technical = technical_rows.get(stock["ticker"], {})
        valuation = valuation_rows.get(stock["ticker"], {})
        fair_price_reason = fair_price_unavailable_reason(valuation)
        fair_price = fair_price_range(stock, valuation)
        current_price = technical.get("currentPrice", "-")
        rows.append({
            "ticker": stock["ticker"],
            "name": clean_stock_name(stock["name"]),
            "market": stock["market"],
            "fairPrice": fair_price,
            "fairPriceReason": fair_price_reason,
            "currentPrice": current_price,
            "valuation": valuation_from_price_range(current_price, fair_price),
            "opinion": technical.get("opinion", "관망"),
            "opinionReason": technical.get("opinionReason", "-"),
            "marketEvent": technical.get("marketEvent", "당분간 없음"),
            "strategies": stock_strategies_from_technical(technical),
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
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
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


def http_error_detail(exc: urllib.error.HTTPError) -> str:
    detail = exc.read().decode("utf-8", errors="replace").strip()
    if not detail:
        return f"HTTP {exc.code}"
    return f"HTTP {exc.code}: {detail[:500]}"


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
                "failedReason": f"Groq API 호출 실패: {http_error_detail(exc)}",
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
        "stocks": lambda: build_stocks_cache(universe),
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
        if name == "stocks":
            search_payload = build_stock_search_cache()
            write_cache("stock-search", search_payload)
            print(f"wrote stock-search: {search_payload['meta']['updatedAt']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=["all", "stocks", "valuation", "technical", "market-trends", "market-events"])
    args = parser.parse_args()
    run(args.job)


if __name__ == "__main__":
    main()
