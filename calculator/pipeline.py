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
from collections import Counter
from datetime import date, datetime, time, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .industry_classification import CATEGORY_VALUES, classify_stock, summarize_industry
from .market_regime import build_qqq_market_state, qqq_recent_ma200_min_distance
from .rules import STRATEGY_RULES, IndicatorRow, compute_nasdaq_filter_active, evaluate_buy_condition, strategy_display_name
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

MEGA_TREND_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("AI 인프라", ("AI 인프라", "데이터센터", "GPU 클라우드", "GPU 클러스터", "HPC", "액침냉각", "UPS"), ("데이터센터", "전력·냉각", "GPU 클러스터", "HPC", "AI 클라우드")),
    ("AI 반도체", ("AI GPU", "AI칩", "AI 칩", "CUDA", "HBM", "ASIC", "GPU", "파운드리", "반도체", "첨단패키징"), ("AI칩", "GPU", "HBM", "ASIC", "첨단패키징")),
    ("우주항공", ("우주", "위성", "발사체", "항공우주", "항공엔진", "LEO", "D2D", "SpaceX", "Rocket Lab", "AST SpaceMobile", "Planet Labs"), ("위성", "발사체", "위성통신", "지구관측", "SpaceX")),
    ("방산·드론", ("방산", "국방", "드론", "무인기", "무인체계", "유도무기", "레이더", "자율무기"), ("방산", "드론", "무인체계", "유도무기", "레이더")),
    ("전력 인프라", ("전력", "전력망", "전기장비", "가스터빈", "원전", "SMR", "연료전지", "수소", "에너지 저장"), ("전력망", "원전", "SMR", "데이터센터 전력", "에너지 저장")),
    ("광통신·네트워크", ("광통신", "광트랜시버", "트랜시버", "광케이블", "광송수신기", "광인터커넥트", "스위칭", "이더넷"), ("광통신", "트랜시버", "광케이블", "AI 네트워킹", "이더넷 스위치")),
    ("로봇·자동화", ("로봇", "로보틱스", "협동로봇", "자동화", "휴머노이드", "Optimus"), ("로봇", "자동화", "휴머노이드", "협동로봇", "로보틱스")),
    ("양자컴퓨팅", ("양자", "이온트랩", "Quantum", "양자 네트워크"), ("양자컴퓨팅", "이온트랩", "양자 네트워크", "양자칩", "양자보안")),
    ("암호화폐·핀테크", ("가상화폐", "비트코인", "이더리움", "Solana", "스테이블코인", "USDC", "Coinbase", "블록체인"), ("스테이블코인", "비트코인", "블록체인", "이더리움", "디지털 자산")),
    ("전기차·배터리", ("전기차", "배터리", "2차전지", "리튬", "양극재", "자율주행", "로보택시"), ("전기차", "배터리", "리튬", "자율주행", "로보택시")),
    ("바이오·헬스케어", ("바이오", "제약", "헬스케어", "의료", "재생의료", "바이오프린팅", "Therapeutics"), ("바이오", "제약", "의료 AI", "재생의료", "진단장비")),
    ("원자재·희토류", ("희토류", "리튬", "구리", "알루미늄", "광산", "금속", "자석"), ("희토류", "리튬", "구리", "알루미늄", "자석 소재")),
)

GENERIC_TREND_TOKENS = {
    "성장주", "혼합주", "가치주", "스윙주", "기술", "산업", "테마", "상장기업",
    "해외 보통주", "개별 사업영역 추가 확인 필요", "ETF", "서비스",
}

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MARKET_TREND_MODEL = os.environ.get("GROQ_MARKET_TREND_MODEL", "").strip() or "llama-3.3-70b-versatile"
CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FAIR_PRICE_UNAVAILABLE_LABEL = "적자 상태라 판단 불가"
MAX_REFRESH_UNIVERSE = int(os.environ.get("MAX_REFRESH_UNIVERSE", "200"))
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
MARKET_EVENTS_WEEKLY_SCHEDULE = "0 0 * * 1"
FED_FOMC_SCHEDULE_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm"
BLS_RELEASE_SCHEDULE_URLS = {
    "고용보고서 발표": "https://www.bls.gov/schedule/news_release/empsit.htm",
    "CPI 발표": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "PPI 발표": "https://www.bls.gov/schedule/news_release/ppi.htm",
}
BEA_RELEASE_SCHEDULE_URL = "https://www.bea.gov/news/schedule"
US_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


class HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
        if self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
        if self._in_cell and tag == "br":
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_row and self._in_cell:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = []
            self._in_cell = False
        if tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._row = []
            self._in_row = False

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


def parse_market_event_clock(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def is_market_event_active(entry: dict[str, Any], now: datetime) -> bool:
    event_date = parse_market_event_date(entry.get("date"))
    if event_date is None or now.date() != event_date:
        return False

    clock = parse_market_event_clock(entry.get("time"))
    if clock is None:
        return True

    release_at = datetime(event_date.year, event_date.month, event_date.day, clock[0], clock[1], tzinfo=KST)
    return now < release_at


def current_market_event_label(
    payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> str:
    payload = payload if payload is not None else read_cache("market-events")
    groups = payload.get("groups") if isinstance(payload, dict) else []
    if not isinstance(groups, list):
        return "당분간 없음"

    if now is None:
        if today is not None:
            now = datetime.combine(today, time(hour=12), tzinfo=KST)
        else:
            now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    active_titles: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = str(group.get("title") or "").strip()
        entries = group.get("entries")
        if not title or not isinstance(entries, list):
            continue
        if any(isinstance(entry, dict) and is_market_event_active(entry, now) for entry in entries):
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
        ma20=row["ma20"],
        ma20_d1=row["ma20D1"],
        ma20_prev5=row["ma20Prev5"],
        close_d1=row["closeD1"],
        bb_width=row["bbWidth"],
        bb_width_d1=row["bbWidthD1"],
        bb_width_avg60=row["bbWidthAvg60"],
        vol_ratio=row["volRatio"],
        vol_ratio20=row["volRatio20"],
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
        is_recovery_market=bool(qqq_market_state.get("isRecoveryMarket")) if qqq_market_state else False,
        recovery_momentum_exception=bool(STRATEGY_RULES.get("RECOVERY_MOMENTUM_EXCEPTION")),
    )
    event_watch_active = market_event != "당분간 없음"
    opinion = "관망" if event_watch_active else "매수" if buy["entryTriggered"] else "관망"
    opinion_reason = f"이벤트 기간 관망 ({market_event})" if event_watch_active else "-"
    strategy = buy["strategyName"] if buy["entryTriggered"] else "-"
    entry_signal_codes = [
        group
        for group in ("A", "B", "C", "D", "E", "F", "G")
        if all(buy["conditions"].get(group, []))
    ]
    buy_block_label = f"나스닥 상단 차단 아님(≤{float(nasdaq_buy_block_max):.0f}%)" if nasdaq_buy_block_max is not None else "나스닥 상단 차단 아님"
    acd_filter_label = "나스닥 강세 필터(회복장 모멘텀 예외)" if buy.get("recoveryException") else "나스닥 강세 필터"
    strategy_labels = {
        "A": ["현재가 > MA200", "MACD 골든크로스", "종가%B > 80", "RSI > 70", acd_filter_label],
        "B": ["현재가 < MA200", "VIX >= 30", "RSI < 35 또는 CCI < -150", "LR 추세선 상승", "저가 추세선 터치", buy_block_label],
        "C": ["현재가 > MA200", "전일 BB 스퀴즈", "당일 BB 확장", "거래량 폭발", "종가%B > 55", "MACD Hist > 0", acd_filter_label],
        "D": ["현재가 > MA200", "+DI > -DI", "ADX > 30", "ADX 상승", "MACD Hist > 0", "종가%B 30~75", acd_filter_label],
        "E": ["현재가 > MA200", "BB폭 압축", "저가%B <= 50", "나스닥 바닥/정상 필터"],
        "F": ["현재가 > MA200", f"저가%B <= {float(STRATEGY_RULES['BB_PCT_B_LOW_MAX']):.0f}", "나스닥 바닥/정상 필터"],
        "G": [
            "회복장 & QQQ 이격도 8~18",
            "현재가 > MA200",
            "MA20 > MA200",
            "저가 MA20 터치",
            "종가 MA20 회복",
            "전일 종가 > 전일 MA20",
            "MA20 5일 기울기 >= 0.5%",
            "RSI 45~80",
            "거래량 <= 20일평균 2.0x",
            f"MA200 이격 <= {float(STRATEGY_RULES['G_MA200_OVERHEAT_MAX']) * 100:.0f}%",
        ],
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
        *(["회복장 모멘텀 예외 적용: QQQ 상단 차단 초과지만 종목 비과열(이격 ≤60% · RSI ≤82)로 A/C/D 신규 진입 허용"] if buy.get("recoveryException") else []),
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
        "20일 이동평균선 (D-1)": fmt_price(row["ma20D1"], stock["market"]),
        "20일 이동평균선 (D-5)": fmt_price(row["ma20Prev5"], stock["market"]),
        "MA20 5일 기울기": fmt_signed_percent((row["ma20"] / row["ma20Prev5"] - 1) * 100 if row["ma20Prev5"] else None),
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
                existing_row = existing_rows.get(stock["ticker"], {})
                if isinstance(existing_row, dict):
                    exit_reason = str(existing_row.get("exitReason") or "").strip()
                    if exit_reason:
                        row = {
                            **row,
                            "opinion": "매도",
                            "opinionReason": existing_row.get("opinionReason") or exit_reason,
                            "exitReason": exit_reason,
                        }
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
        if code in {"A", "B", "C", "D", "E", "F", "G"} and code not in codes:
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


def normalize_trend_token(value: Any) -> str:
    return re.sub(r"[\s·,|/()&+\-_'\".]+", "", str(value or "").lower())


def split_trend_tokens(value: Any) -> list[str]:
    tokens: list[str] = []
    for raw in re.split(r"[,·|/()\s]+", str(value or "")):
        token = raw.strip()
        if len(token) < 2 or token in GENERIC_TREND_TOKENS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def stock_trend_themes(stock: dict[str, Any]) -> list[str]:
    haystack = " ".join(str(stock.get(key) or "") for key in ("ticker", "name", "category", "industry", "rawIndustry", "products"))
    normalized_haystack = normalize_trend_token(haystack)
    themes: list[str] = []
    for label, keywords, _ in MEGA_TREND_RULES:
        if any(normalize_trend_token(keyword) in normalized_haystack for keyword in keywords):
            themes.append(label)

    if themes:
        return themes[:3]

    fallback_tokens = split_trend_tokens(stock.get("industry"))
    return fallback_tokens[:1]


def parse_metric_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed == parsed else None
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    if "%" in text:
        return parse_percent(text)
    return parse_amount(text)


def technical_trend_score(technical: dict[str, Any]) -> float:
    current_price = parse_metric_number(technical.get("현재가") or technical.get("currentPrice"))
    ma20 = parse_metric_number(technical.get("20일 이동평균선"))
    ma200 = parse_metric_number(technical.get("200일 이동평균선"))
    ma20_slope = parse_metric_number(technical.get("MA20 5일 기울기"))
    pct_b = parse_metric_number(technical.get("볼린저밴드 %B (종가)"))
    rsi = parse_metric_number(technical.get("RSI (D)"))
    adx = parse_metric_number(technical.get("ADX (14, D)"))
    plus_di = parse_metric_number(technical.get("+DI (DMI, 14)"))
    minus_di = parse_metric_number(technical.get("-DI (DMI, 14)"))
    macd_hist = parse_metric_number(technical.get("MACD Histogram (D)"))
    vol_ratio20 = parse_metric_number(technical.get("20일 평균 대비 거래량 (D)"))

    score = 0.0
    if current_price is not None and ma200 is not None and current_price > ma200:
        score += 1.5
    if current_price is not None and ma20 is not None and current_price > ma20:
        score += 1.0
    if ma20_slope is not None and ma20_slope > 0:
        score += min(ma20_slope, 12.0) / 2.0
    if pct_b is not None:
        if pct_b >= 100:
            score += 2.5
        elif pct_b >= 80:
            score += 2.0
        elif pct_b >= 55:
            score += 1.0
    if rsi is not None:
        if 55 <= rsi <= 80:
            score += min((rsi - 50) / 10, 3.0)
        elif rsi > 80:
            score += 2.0
    if adx is not None and adx >= 30:
        score += 1.5
    if plus_di is not None and minus_di is not None and plus_di > minus_di:
        score += 1.0
    if macd_hist is not None and macd_hist > 0:
        score += 1.0
    if vol_ratio20 is not None:
        if vol_ratio20 >= 120:
            score += min((vol_ratio20 - 100) / 25, 2.0)
        elif vol_ratio20 >= 100:
            score += 0.5
    if str(technical.get("opinion") or "") == "매수":
        score += 3.0
    if strategy_codes_from_technical(technical):
        score += 2.0
    return score


def default_theme_keywords(theme: str) -> list[str]:
    for label, _, keywords in MEGA_TREND_RULES:
        if label == theme:
            return list(keywords)
    return []


def build_market_trend_signal_rows(
    stocks: list[Any] | None = None,
    technical_rows: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    stock_rows = stocks
    if stock_rows is None:
        loaded_stocks = read_cache("stocks").get("rows", [])
        stock_rows = loaded_stocks if isinstance(loaded_stocks, list) else []
    if technical_rows is None:
        loaded_technical = read_cache("technical").get("rows", {})
        technical_rows = loaded_technical if isinstance(loaded_technical, dict) else {}

    aggregates: dict[str, dict[str, Any]] = {}
    for stock in stock_rows:
        if not isinstance(stock, dict):
            continue
        ticker = str(stock.get("ticker") or "").strip().upper()
        technical = technical_rows.get(ticker) if ticker else {}
        if not isinstance(technical, dict):
            technical = {}
        score = technical_trend_score(technical)
        if score < 3.5:
            continue
        themes = stock_trend_themes(stock)
        if not themes:
            continue
        tokens = split_trend_tokens(stock.get("industry"))
        for theme in themes:
            aggregate = aggregates.setdefault(theme, {"score": 0.0, "stocks": [], "keywords": Counter()})
            aggregate["score"] += score
            aggregate["stocks"].append({
                "ticker": ticker,
                "name": clean_stock_name(stock.get("name")),
                "score": score,
            })
            for token in tokens:
                aggregate["keywords"][token] += 1

    rows: list[dict[str, Any]] = []
    for theme, aggregate in aggregates.items():
        stocks_for_theme = sorted(aggregate["stocks"], key=lambda item: item["score"], reverse=True)
        stock_count = len(stocks_for_theme)
        final_score = float(aggregate["score"]) + min(stock_count, 5) * 0.75
        if final_score < 5 and stock_count < 2:
            continue

        keywords: list[str] = []
        for keyword in default_theme_keywords(theme):
            if keyword not in keywords:
                keywords.append(keyword)
        for keyword, _ in aggregate["keywords"].most_common(5):
            if keyword not in keywords and keyword not in GENERIC_TREND_TOKENS:
                keywords.append(keyword)
            if len(keywords) >= 5:
                break

        rows.append({
            "rankText": f"{theme} | {', '.join(keywords[:5])}",
            "score": round(final_score, 2),
            "stockCount": stock_count,
            "tickers": [stock["ticker"] for stock in stocks_for_theme[:5] if stock["ticker"]],
            "stockNames": [stock["name"] for stock in stocks_for_theme[:5] if stock["name"] and stock["name"] != "-"],
        })

    return sorted(rows, key=lambda row: (row["score"], row["stockCount"]), reverse=True)


def market_trend_sector_key(rank_text: str) -> str:
    return normalize_trend_token(str(rank_text).split("|", 1)[0])


def merge_market_trend_ranks(ranks: list[str], signal_rows: list[dict[str, Any]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    def add(rank_text: Any) -> None:
        text = sanitize_market_trend_text(str(rank_text or ""))
        if not isinstance(text, str) or not text:
            return
        key = market_trend_sector_key(text)
        if key in seen:
            return
        seen.add(key)
        merged.append(text)

    for row in signal_rows[:5]:
        add(row.get("rankText"))
    for rank in ranks:
        add(rank)
    return merged[:10]


def market_trend_signal_evidence_text(signal_rows: list[dict[str, Any]]) -> str:
    if not signal_rows:
        return "관심종목 기반 가격·기술 모멘텀 신호 없음"
    return "\n".join(
        f"- {row['rankText']} (점수 {row['score']}, 강세 종목 {row['stockCount']}개: {', '.join(row.get('stockNames', []))})"
        for row in signal_rows[:10]
    )


def market_trend_row_from_signals(signal_rows: list[dict[str, Any]], failed_reason: str | None = None) -> dict[str, Any]:
    summary = "관심종목의 가격·기술 모멘텀에서 강하게 확인된 메가트렌드를 우선 반영했습니다."
    if failed_reason:
        summary += f" RSS/LLM 분석은 실패해 내부 신호 기준으로 대체했습니다: {failed_reason}"
    return {
        "date": datetime.now().astimezone().strftime("%Y.%m.%d"),
        "ranks": [str(row["rankText"]) for row in signal_rows[:10]],
        "summary": summary,
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
        (r"받고 있다\.$", "받고 있습니다."),
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


def analyze_market_trends_with_groq(news_text: str, api_key: str, signal_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    signal_rows = signal_rows or []
    signal_evidence = market_trend_signal_evidence_text(signal_rows)
    prompt = f"""다음은 이번 주 미국 금융·기술 뉴스 헤드라인입니다.
주식 시장에서 현재 가장 주목받는 섹터/테마를 1위부터 10위까지 순위를 매겨주세요.

[분석 기준]
- 단순 언급 빈도가 아닌, 실제 자금이 몰리고 있는 테마 중심
- 아래 "관심종목 가격·기술 모멘텀 신호"는 실제 가격·기술 데이터 기반이므로 뉴스 헤드라인보다 우선 반영
- 여러 종목이 같은 산업에서 동시에 강한 추세를 보이면 그 산업을 메가트렌드로 승격
- 특정 기업명이 다른 섹터에 잘못 묶이지 않도록 실제 사업 테마로 정규화
- "AI 인프라" 같은 넓은 개념도 이번 주 특히 주목받는 세부 요소로 구체화
  예) "AI인프라 | 광통신, 트랜시버" / "AI인프라 | 전력인프라, 데이터센터냉각"
- 각 순위마다 섹터명과 핵심 키워드 3~5개

[출력 형식 — 반드시 이 형식으로만 출력, 다른 설명 없이]
1위: 섹터명 | 키워드1, 키워드2, 키워드3
2위: 섹터명 | 키워드1, 키워드2, 키워드3
...
10위: 섹터명 | 키워드1, 키워드2, 키워드3
요약: 이번 주 전체 시장 분위기 한 줄

[관심종목 가격·기술 모멘텀 신호]
{signal_evidence}

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
    parsed["ranks"] = merge_market_trend_ranks(parsed["ranks"], signal_rows)
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
    signal_rows = build_market_trend_signal_rows()

    if not api_key:
        if signal_rows:
            new_row = market_trend_row_from_signals(signal_rows, "GROQ_API_KEY 환경변수가 설정되어 있지 않습니다.")
            rows = upsert_market_trend_row(rows, new_row)
            return {
                "meta": {
                    **existing.get("meta", {}),
                    "kind": "market-trends",
                    "schedule": "0 0 * * 1",
                    "updatedAt": now_iso(),
                    "lastSuccessfulRun": now_iso(),
                    "failedReason": "GROQ_API_KEY 환경변수가 없어 LLM 분석 없이 내부 가격·기술 모멘텀 신호로 시장 트렌드를 갱신했습니다.",
                },
                "rows": rows,
            }
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
        new_row = analyze_market_trends_with_groq(news_text, api_key, signal_rows)
        rows = upsert_market_trend_row(rows, new_row)
    except urllib.error.HTTPError as exc:
        if signal_rows:
            new_row = market_trend_row_from_signals(signal_rows, http_error_detail(exc))
            rows = upsert_market_trend_row(rows, new_row)
            return {
                "meta": {
                    **existing.get("meta", {}),
                    "kind": "market-trends",
                    "schedule": "0 0 * * 1",
                    "updatedAt": now_iso(),
                    "lastSuccessfulRun": now_iso(),
                    "failedReason": f"Groq API 호출 실패 후 내부 가격·기술 모멘텀 신호로 대체했습니다: {http_error_detail(exc)}",
                },
                "rows": rows,
            }
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
        if signal_rows:
            new_row = market_trend_row_from_signals(signal_rows, str(exc))
            rows = upsert_market_trend_row(rows, new_row)
            return {
                "meta": {
                    **existing.get("meta", {}),
                    "kind": "market-trends",
                    "schedule": "0 0 * * 1",
                    "updatedAt": now_iso(),
                    "lastSuccessfulRun": now_iso(),
                    "failedReason": f"RSS/Groq 분석 실패 후 내부 가격·기술 모멘텀 신호로 대체했습니다: {exc}",
                },
                "rows": rows,
            }
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


def html_table_rows(html_text: str) -> list[list[str]]:
    parser = HtmlTableParser()
    parser.feed(html_text)
    return parser.rows


def parse_us_month(value: str) -> int | None:
    key = re.sub(r"[^A-Za-z]", "", value).lower()
    return US_MONTHS.get(key)


def parse_release_month(entry: dict[str, Any]) -> int | None:
    match = re.match(r"^(\d{1,2})월$", str(entry.get("month") or "").strip())
    if not match:
        return None
    month = int(match.group(1))
    return month if 1 <= month <= 12 else None


def market_event_year(payload: dict[str, Any], today: date | None = None) -> int:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    match = re.search(r"\d{4}", str(meta.get("yearLabel") or ""))
    if match:
        return int(match.group(0))

    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    years: list[int] = []
    for group in groups:
        entries = group.get("entries") if isinstance(group, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            parsed = parse_market_event_date(entry.get("date")) if isinstance(entry, dict) else None
            if parsed:
                years.append(parsed.year)
    if years:
        return Counter(years).most_common(1)[0][0]
    return (today or datetime.now(KST).date()).year


def format_market_event_date(value: date) -> str:
    return f"{value.year}. {value.month}. {value.day}"


def format_market_event_time(value: datetime) -> str:
    return f"{value.hour}:{value.minute:02d}"


def format_market_event_d_day(value: Any, today: date | None = None) -> str:
    parsed = parse_market_event_date(value)
    if not parsed:
        return "-"
    today = today or datetime.now(KST).date()
    return str((parsed - today).days)


def parse_us_date_text(value: str, default_year: int | None = None) -> date | None:
    text = " ".join(value.replace(".", "").replace(",", " ").split())
    match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:\s+(\d{4}))?$", text)
    if not match:
        return None
    month = parse_us_month(match.group(1))
    year = int(match.group(3)) if match.group(3) else default_year
    if month is None or year is None:
        return None
    try:
        return date(year, month, int(match.group(2)))
    except ValueError:
        return None


def parse_us_time_text(value: str) -> tuple[int, int] | None:
    text = " ".join(value.strip().upper().split())
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3)
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return hour, minute


def market_event_source_value(release_date: date, release_time: str) -> dict[str, str] | None:
    parsed_time = parse_us_time_text(release_time)
    if parsed_time is None:
        return None
    released_at = datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        parsed_time[0],
        parsed_time[1],
        tzinfo=ET,
    ).astimezone(KST)
    return {
        "date": format_market_event_date(released_at.date()),
        "time": format_market_event_time(released_at),
    }


def add_unique_market_event_source(
    target: dict[int, dict[str, str]],
    issues: list[str],
    title: str,
    month: int,
    value: dict[str, str] | None,
) -> None:
    if month < 1 or month > 12 or value is None:
        issues.append(f"{title} 공식 일정의 날짜/시간을 해석하지 못했습니다.")
        return
    previous = target.get(month)
    if previous and previous != value:
        issues.append(
            f"{title} {month}월 공식 일정이 복수 값으로 충돌합니다: "
            f"{previous['date']} {previous['time']} / {value['date']} {value['time']}"
        )
        return
    target[month] = value


def fetch_fomc_market_events(year: int, issues: list[str]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    try:
        html_text = fetch_text(FED_FOMC_SCHEDULE_URL)
    except Exception as exc:  # noqa: BLE001 - external source should not block cache generation
        issues.append(f"Federal Reserve FOMC 일정 조회 실패: {exc}")
        return result

    plain = re.sub(r"<[^>]+>", " ", html_text)
    plain = " ".join(unescape(plain).split())
    marker = f"For {year}:"
    start = plain.find(marker)
    if start < 0:
        issues.append(f"Federal Reserve FOMC {year}년 공식 일정 구간을 찾지 못했습니다.")
        return result
    section = plain[start + len(marker):]
    end = section.find("The Committee releases")
    if end >= 0:
        section = section[:end]

    for match in re.finditer(
        r"and\s+[A-Za-z]+,\s+([A-Za-z]+)\s+(\d{1,2})(?:,\s+(\d{4}))?",
        section,
    ):
        event_year = int(match.group(3) or year)
        if event_year != year:
            continue
        month = parse_us_month(match.group(1))
        if month is None:
            issues.append(f"Federal Reserve FOMC 날짜의 월을 해석하지 못했습니다: {match.group(0)}")
            continue
        try:
            second_day = date(event_year, month, int(match.group(2)))
        except ValueError:
            issues.append(f"Federal Reserve FOMC 날짜를 해석하지 못했습니다: {match.group(0)}")
            continue
        value = market_event_source_value(second_day, "2:00 PM")
        value_date = parse_market_event_date(value.get("date") if value else None)
        add_unique_market_event_source(result, issues, "금리 발표", value_date.month if value_date else 0, value)

    if not result:
        issues.append(f"Federal Reserve FOMC {year}년 공식 일정에서 검증 가능한 발표일을 찾지 못했습니다.")
    return result


def fetch_bls_market_events(title: str, url: str, year: int, issues: list[str]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    try:
        rows = html_table_rows(fetch_text(url))
    except Exception as exc:  # noqa: BLE001 - ambiguous by design when the official page cannot be read
        issues.append(f"BLS {title} 공식 일정 조회 실패: {exc}")
        return result

    for row in rows:
        if len(row) < 3 or row[0].lower().startswith("reference"):
            continue
        release_date = parse_us_date_text(row[1], year)
        if release_date is None or release_date.year != year:
            continue
        value = market_event_source_value(release_date, row[2])
        add_unique_market_event_source(result, issues, title, release_date.month, value)

    if not result:
        issues.append(f"BLS {title} {year}년 공식 일정에서 검증 가능한 발표일을 찾지 못했습니다.")
    return result


def fetch_pce_market_events(year: int, issues: list[str]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    try:
        rows = html_table_rows(fetch_text(BEA_RELEASE_SCHEDULE_URL))
    except Exception as exc:  # noqa: BLE001
        issues.append(f"BEA PCE 공식 일정 조회 실패: {exc}")
        return result

    for row in rows:
        if len(row) < 3 or "Personal Income and Outlays" not in row[2]:
            continue
        title_match = re.search(r"Personal Income and Outlays,\s+([A-Za-z]+)\s+(\d{4})", row[2])
        date_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]M)$", row[0], flags=re.IGNORECASE)
        if not title_match or not date_match:
            issues.append(f"BEA PCE 공식 일정 행을 해석하지 못했습니다: {' | '.join(row)}")
            continue
        reference_month = parse_us_month(title_match.group(1))
        reference_year = int(title_match.group(2))
        release_month = parse_us_month(date_match.group(1))
        if reference_month is None or release_month is None:
            continue
        release_year = reference_year
        if release_month < reference_month:
            release_year += 1
        if release_year != year:
            continue
        release_date = date(release_year, release_month, int(date_match.group(2)))
        value = market_event_source_value(release_date, date_match.group(3))
        add_unique_market_event_source(result, issues, "PCE 발표", release_date.month, value)

    if not result:
        issues.append(f"BEA PCE {year}년 공식 일정에서 검증 가능한 발표일을 찾지 못했습니다.")
    return result


def official_market_event_sources(year: int) -> tuple[dict[str, dict[int, dict[str, str]]], list[str]]:
    issues: list[str] = []
    sources: dict[str, dict[int, dict[str, str]]] = {
        "금리 발표": fetch_fomc_market_events(year, issues),
    }
    for title, url in BLS_RELEASE_SCHEDULE_URLS.items():
        sources[title] = fetch_bls_market_events(title, url, year, issues)
    sources["PCE 발표"] = fetch_pce_market_events(year, issues)
    return sources, issues


def apply_market_event_verification(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    year = market_event_year(payload)
    today = datetime.now(KST).date()
    sources, issues = official_market_event_sources(year)
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    changes: list[str] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        title = str(group.get("title") or "").strip()
        entries = group.get("entries")
        if not isinstance(entries, list):
            continue
        group_sources = sources.get(title, {})
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry["dday"] = format_market_event_d_day(entry.get("date"), today)
            month = parse_release_month(entry)
            if month is None or title not in sources:
                continue
            source_value = group_sources.get(month)
            if not source_value:
                cached_date = parse_market_event_date(entry.get("date"))
                if group_sources and cached_date and cached_date >= today:
                    issues.append(f"{title} {month}월 공식 일정 확인값이 없어 자동 수정하지 않았습니다.")
                continue

            cached_date = parse_market_event_date(entry.get("date"))
            if cached_date and cached_date < today:
                continue
            old_date = str(entry.get("date") or "-").strip() or "-"
            old_time = str(entry.get("time") or "-").strip() or "-"
            if old_date != source_value["date"] or old_time != source_value["time"]:
                entry["date"] = source_value["date"]
                entry["time"] = source_value["time"]
                entry["dday"] = format_market_event_d_day(entry.get("date"), today)
                changes.append(
                    f"{title} {month}월: {old_date} {old_time} -> "
                    f"{source_value['date']} {source_value['time']}"
                )

    return payload, changes, issues


def market_event_failed_reason(changes: list[str], issues: list[str]) -> str | None:
    if not issues:
        return None
    issue_text = "; ".join(issues[:8])
    if len(issues) > 8:
        issue_text += f"; 외 {len(issues) - 8}건"
    prefix = "일부 확실한 일정은 자동 수정했지만, " if changes else ""
    return prefix + "시장 주요 이벤트 검증에 수동 확인이 필요한 항목이 있습니다: " + issue_text


def build_market_events_cache() -> dict[str, Any]:
    existing = read_cache("market-events")
    if isinstance(existing.get("groups"), list) and existing["groups"]:
        existing, changes, issues = apply_market_event_verification(existing)
        failed_reason = market_event_failed_reason(changes, issues)
        checked_at = now_iso()
        existing["meta"] = {
            **existing.get("meta", {}),
            "kind": "market-events",
            "schedule": MARKET_EVENTS_WEEKLY_SCHEDULE,
            "updatedAt": checked_at,
            "lastSuccessfulRun": checked_at if failed_reason is None else existing.get("meta", {}).get("lastSuccessfulRun"),
            "failedReason": failed_reason,
            "verification": {
                "checkedAt": checked_at,
                "sourcePolicy": "official-only-auto-update",
                "autoUpdated": changes,
                "needsManualReview": issues,
                "sources": {
                    "fomc": FED_FOMC_SCHEDULE_URL,
                    "bls": list(BLS_RELEASE_SCHEDULE_URLS.values()),
                    "beaPce": BEA_RELEASE_SCHEDULE_URL,
                },
            },
        }
        return existing

    return {
        "meta": {
            "kind": "market-events",
            "schedule": MARKET_EVENTS_WEEKLY_SCHEDULE,
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
