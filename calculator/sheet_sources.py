"""Data fetchers and calculations ported from the Apps Script files.

This intentionally mirrors the GAS sources:
- KR prices: Naver fchart XML API
- US prices: Yahoo Finance chart API
- KR valuation: Naver Finance page parsing
- US valuation: Finviz page parsing
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_text(url: str, *, encoding: str = "utf-8") -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode(encoding, errors="ignore")


def resolve_market(ticker: str) -> str:
    return "KR" if re.fullmatch(r"\d{6}", ticker) else "US"


def fetch_kr_ohlcv(code: str, count: int = 320) -> list[dict[str, float]]:
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
    xml = fetch_text(url, encoding="euc-kr")
    rows = []
    for match in re.finditer(r'item data="([^"]+)"', xml):
        parts = match.group(1).split("|")
        if len(parts) < 6:
            continue
        try:
            rows.append({
                "date": parts[0],
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5]),
            })
        except ValueError:
            continue
    return rows


def fetch_us_ohlcv(symbol: str, range_value: str = "1y") -> list[dict[str, float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={range_value}&interval=1d"
    data = json.loads(fetch_text(url))
    result = data.get("chart", {}).get("result", [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    rows = []
    for index, close in enumerate(quote.get("close") or []):
        high = (quote.get("high") or [None])[index]
        low = (quote.get("low") or [None])[index]
        open_ = (quote.get("open") or [None])[index]
        volume = (quote.get("volume") or [None])[index]
        if close is None or high is None or low is None or open_ is None:
            continue
        rows.append({
            "date": str(timestamps[index]) if index < len(timestamps) else "",
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume or 0),
        })
    return rows


def fetch_ohlcv(ticker: str, count: int = 320) -> list[dict[str, float]]:
    if resolve_market(ticker) == "KR":
        return fetch_kr_ohlcv(ticker, count=count)
    # GAS files request 200d/1y depending on the indicator. 1y covers the table.
    return fetch_us_ohlcv(ticker, range_value="1y")


def ema_latest(values: list[float], period: int) -> float:
    if len(values) < period:
        return 0
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def historical_ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return []
    result: list[float | None] = [None] * (period - 1)
    current = sum(values[:period]) / period
    result.append(current)
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        current = (value - current) * multiplier + current
        result.append(current)
    return result


def calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    values = []
    for i in range(period, len(closes)):
        gains = 0.0
        losses = 0.0
        for j in range(i - period + 1, i + 1):
            change = closes[j] - closes[j - 1]
            if change > 0:
                gains += change
            if change < 0:
                losses -= change
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            values.append(100 - (100 / (1 + rs)))
    return values


def calc_cci(rows: list[dict[str, float]], period: int = 20) -> list[float]:
    typical = [(row["high"] + row["low"] + row["close"]) / 3 for row in rows]
    values = []
    for i in range(period - 1, len(typical)):
        window = typical[i - period + 1 : i + 1]
        sma = sum(window) / period
        mean_deviation = sum(abs(value - sma) for value in window) / period
        values.append(0.0 if mean_deviation == 0 else (typical[i] - sma) / (0.015 * mean_deviation))
    return values


def calc_macd(closes: list[float]) -> dict[str, float]:
    short_emas = historical_ema(closes, 12)
    long_emas = historical_ema(closes, 26)
    macd_values = []
    for i in range(max(12, 26) - 1, len(closes)):
        short = short_emas[i] if i < len(short_emas) else None
        long = long_emas[i] if i < len(long_emas) else None
        if short is not None and long is not None:
            macd_values.append(short - long)
    macd_line = ema_latest(closes, 12) - ema_latest(closes, 26)
    signal = ema_latest(macd_values, 9)
    hist = macd_line - signal
    prev_signal_1 = ema_latest(macd_values[:-1], 9)
    prev_signal_2 = ema_latest(macd_values[:-2], 9)
    return {
        "macd": round(macd_line, 2),
        "macdD1": round(ema_latest(closes[:-1], 12) - ema_latest(closes[:-1], 26), 2),
        "macdSignal": round(signal, 2),
        "macdHist": round(hist, 2),
        "macdHistD1": round(macd_values[-2] - prev_signal_1, 2) if len(macd_values) >= 2 else math.nan,
        "macdHistD2": round(macd_values[-3] - prev_signal_2, 2) if len(macd_values) >= 3 else math.nan,
    }


def calc_bollinger(rows: list[dict[str, float]]) -> dict[str, float]:
    period = 20
    widths = []

    def band(slice_rows: list[dict[str, float]]) -> tuple[float, float, float]:
        closes = [row["close"] for row in slice_rows]
        sma = sum(closes) / period
        std = math.sqrt(sum((price - sma) ** 2 for price in closes) / period)
        return sma, sma + 2 * std, sma - 2 * std

    def pct_b(price: float, lower: float, upper: float) -> float:
        if upper - lower == 0:
            return 100 if price > upper else 0 if price < lower else 50
        return (price - lower) / (upper - lower) * 100

    latest = rows[-1]
    _, upper, lower = band(rows[-period:])
    prev = rows[-2]
    _, prev_upper, prev_lower = band(rows[-period - 1 : -1])
    for i in range(len(rows) - 60, len(rows)):
        if i - (period - 1) >= 0:
            sma, upper_i, lower_i = band(rows[i - (period - 1) : i + 1])
            widths.append((upper_i - lower_i) / sma * 100 if sma else math.nan)
    width = (upper - lower) / (sum(row["close"] for row in rows[-period:]) / period) * 100
    prev_width = (prev_upper - prev_lower) / (sum(row["close"] for row in rows[-period - 1 : -1]) / period) * 100
    return {
        "pctB": round(pct_b(latest["close"], lower, upper), 2),
        "pctBLow": round(pct_b(latest["low"], lower, upper), 2),
        "pctBPeak": round(pct_b(latest["high"], lower, upper), 2),
        "pctBPeakD1": round(pct_b(prev["high"], prev_lower, prev_upper), 2),
        "bbWidth": round(width, 2),
        "bbWidthD1": round(prev_width, 2),
        "bbWidthAvg60": round(sum(widths) / len(widths), 2) if widths else math.nan,
    }


def calc_adx(rows: list[dict[str, float]], period: int = 14) -> dict[str, float]:
    tr_values = []
    plus_dm_values = []
    minus_dm_values = []
    for i in range(1, len(rows)):
        current = rows[i]
        prev = rows[i - 1]
        tr_values.append(max(
            current["high"] - current["low"],
            abs(current["high"] - prev["close"]),
            abs(current["low"] - prev["close"]),
        ))
        plus_raw = current["high"] - prev["high"]
        minus_raw = prev["low"] - current["low"]
        plus_dm_values.append(plus_raw if plus_raw > minus_raw and plus_raw > 0 else 0)
        minus_dm_values.append(minus_raw if minus_raw > plus_raw and minus_raw > 0 else 0)
    smoothed_tr = historical_ema(tr_values, period)
    smoothed_plus = historical_ema(plus_dm_values, period)
    smoothed_minus = historical_ema(minus_dm_values, period)
    plus_di = []
    minus_di = []
    dx = []
    for i in range(period - 1, len(smoothed_tr)):
        tr = smoothed_tr[i]
        plus = smoothed_plus[i]
        minus = smoothed_minus[i]
        if tr is None or plus is None or minus is None:
            continue
        pdi = plus / tr * 100 if tr > 0 else 0
        mdi = minus / tr * 100 if tr > 0 else 0
        plus_di.append(pdi)
        minus_di.append(mdi)
        dx.append(abs(pdi - mdi) / (pdi + mdi) * 100 if pdi + mdi > 0 else 0)
    adx_values = [v for v in historical_ema(dx, period) if v is not None]
    return {
        "plusDI": round(plus_di[-1], 2),
        "minusDI": round(minus_di[-1], 2),
        "adx": round(adx_values[-1], 2),
        "adxD1": round(adx_values[-2], 2),
        "adxD2": round(adx_values[-3], 2),
        "adxSlope": round(adx_values[-1] - adx_values[-2], 2),
    }


def calc_lr(rows: list[dict[str, float]], period: int = 120) -> dict[str, float]:
    lows = [row["low"] for row in rows[-155:]]
    y = lows[-period:]
    x_mean = (period - 1) / 2
    y_mean = sum(y) / period
    den = sum((x - x_mean) ** 2 for x in range(period))
    slope = sum((x - x_mean) * (value - y_mean) for x, value in enumerate(y)) / den
    intercept = y_mean - slope * x_mean
    value = intercept + slope * (period - 1)
    return {"lrTrendline": round(value, 2), "lrSlope": round(slope, 6)}


def calc_technical_row(ticker: str) -> dict[str, float]:
    rows = fetch_ohlcv(ticker)
    closes = [row["close"] for row in rows]
    rsi_values = calc_rsi(closes)
    cci_values = calc_cci(rows)
    macd = calc_macd(closes)
    bb = calc_bollinger(rows)
    adx = calc_adx(rows)
    lr = calc_lr(rows)
    latest = rows[-1]
    prev = rows[-2]
    open_ = latest["open"]
    high = latest["high"]
    low = latest["low"]
    close = latest["close"]
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": latest["volume"],
        "prevVolume": prev["volume"],
        "ma5": sum(closes[-5:]) / 5,
        "ma20": sum(closes[-20:]) / 20,
        "ma60": sum(closes[-60:]) / 60,
        "ma144": sum(closes[-144:]) / 144,
        "ma200": sum(closes[-200:]) / 200,
        "lowerTail": min(open_, close) - low,
        "upperTail": high - max(open_, close),
        "bodyLength": abs(close - open_),
        "volRatio20": round(latest["volume"] / (sum(row["volume"] for row in rows[-20:]) / 20), 2),
        "tradeValue": latest["volume"] * close,
        "rsi": round(rsi_values[-1], 2),
        "rsiD1": round(rsi_values[-2], 2),
        "rsiSignal": round(ema_latest(rsi_values, 9), 2),
        "rsiSlope": round(rsi_values[-1] - rsi_values[-2], 2),
        "cci": round(cci_values[-1], 2),
        "cciD1": round(cci_values[-2], 2),
        "cciSignal": round(ema_latest(cci_values, 9), 2),
        "cciSlope": round(cci_values[-1] - cci_values[-2], 2),
        "volRatio": round(latest["volume"] / (sum(row["volume"] for row in rows[-5:]) / 5), 2),
        **macd,
        **bb,
        **adx,
        **lr,
    }


def clean_html(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", value)).strip().replace(",", "")


def extract_row_values(table_html: str, row_label: str) -> list[float | None]:
    match = re.search(
        rf"<th[^>]*>(?:(?!</th>)[\s\S])*?{row_label}(?:(?!</th>)[\s\S])*?</th>([\s\S]*?)(?=<th|</tbody)",
        table_html,
    )
    if not match:
        return []
    values = []
    for td in re.finditer(r"<td[^>]*>([\s\S]*?)</td>", match.group(1)):
        clean = clean_html(td.group(1))
        values.append(float(clean) if re.fullmatch(r"-?\d+\.?\d*", clean) else None)
    return values


def pct_no_plus(curr: float, prev: float) -> str:
    return f"{((curr - prev) / abs(prev) * 100):.2f}%"


def format_billion_won(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "-"
    rounded = round(value)
    if rounded >= 10000:
        jo = rounded // 10000
        eok = rounded % 10000
        return f"{jo:,}조 {eok:,}억" if eok else f"{jo:,}조"
    return f"{rounded:,}억"


def fetch_korean_valuation(code: str) -> list[str]:
    html = fetch_text(f"https://finance.naver.com/item/main.naver?code={code}", encoding="utf-8")
    table_match = re.search(r"기업실적분석([\s\S]*?)동종업종비교", html)
    if not table_match:
        raise RuntimeError("기업실적분석 없음")
    table = table_match.group(1)
    sales = extract_row_values(table, "매출액")
    oper = extract_row_values(table, "영업이익")
    eps = extract_row_values(table, r"EPS\(원\)")
    roe_data = extract_row_values(table, r"ROE\(지배주주\)")
    debt = extract_row_values(table, "부채비율")
    quick = extract_row_values(table, "당좌비율")

    nums = lambda values: [v for v in values if isinstance(v, float)]
    qt_sales = nums(sales[4:9])
    ann_sales = nums(sales[0:3])
    qt_oper = nums(oper[4:9])
    qt_eps = nums(eps[4:9])
    ann_eps = nums(eps[0:3])
    qt_roe = nums(roe_data[4:9])
    ann_roe = nums(roe_data[0:3])
    qt_debt = nums(debt[4:9])
    qt_quick = nums(quick[4:9])
    eps_next_raw = eps[3] if len(eps) > 3 and isinstance(eps[3], float) else None

    per = "-"
    pbr = "-"
    per_match = re.search(r'<em id="_per">([\d,.]+)</em>', html)
    pbr_match = re.search(r'<em id="_pbr">([\d,.]+)</em>', html)
    if per_match:
        per_val = float(per_match.group(1).replace(",", ""))
        per = "-" if per_val < 0 else f"{per_val:.2f}"
    if pbr_match:
        pbr_val = float(pbr_match.group(1).replace(",", ""))
        pbr = "-" if pbr_val < 0 else f"{pbr_val:.2f}"

    market_cap = "-"
    mc_billion = 0.0
    mc_match = re.search(r'<em id="_market_sum">([\s\S]*?)</em>억원', html)
    if mc_match:
        raw = re.sub(r"\s", "", re.sub(r"<[^>]+>", "", mc_match.group(1)))
        jo_match = re.search(r"([\d,]+)조([\d,]+)?", raw)
        eok_match = re.fullmatch(r"([\d,]+)", raw)
        if jo_match:
            mc_billion = float(jo_match.group(1).replace(",", "")) * 10000 + (float(jo_match.group(2).replace(",", "")) if jo_match.group(2) else 0)
        elif eok_match:
            mc_billion = float(eok_match.group(1).replace(",", ""))
        market_cap = format_billion_won(mc_billion)

    shares_match = re.search(r"상장주식수</th>\s*<td[^>]*><em>([\d,]+)</em></td>", html)
    shares = shares_match.group(1) if shares_match else "-"
    sales_ttm_billion = sum(qt_sales[-4:]) if len(qt_sales) >= 4 else (ann_sales[-1] if ann_sales else 0)
    sales_ttm = format_billion_won(sales_ttm_billion) if sales_ttm_billion else "-"
    sales_qq = pct_no_plus(qt_sales[-1], qt_sales[-2]) if len(qt_sales) >= 2 and qt_sales[-2] else "-"
    sales_yy = pct_no_plus(qt_sales[-1], qt_sales[-5]) if len(qt_sales) >= 5 and qt_sales[-5] else "-"
    sales_past = pct_no_plus(ann_sales[-1], ann_sales[-2]) + " / -" if len(ann_sales) >= 2 and ann_sales[-2] else "-"
    current_ratio = f"{qt_quick[-1]:.2f}%" if qt_quick else "-"
    de = f"{qt_debt[-1]:.2f}%" if qt_debt else "-"
    ps = f"{mc_billion / sales_ttm_billion:.2f}" if mc_billion > 0 and sales_ttm_billion > 0 else "-"
    roe = f"{(qt_roe[-1] if qt_roe else ann_roe[-1]):.2f}%" if (qt_roe or ann_roe) else "-"
    eps_ttm_value = sum(qt_eps[-4:]) if len(qt_eps) >= 4 else (ann_eps[-1] if ann_eps else None)
    eps_ttm = f"₩{round(eps_ttm_value):,}" if eps_ttm_value is not None else "-"
    eps_next = f"₩{round(eps_next_raw):,}" if eps_next_raw is not None else "-"
    eps_qq = pct_no_plus(qt_eps[-1], qt_eps[-2]) if len(qt_eps) >= 2 and qt_eps[-2] else "-"
    peg = "-"
    if per != "-" and len(qt_eps) >= 5 and qt_eps[-5]:
        eps_yoy = (qt_eps[-1] - qt_eps[-5]) / abs(qt_eps[-5]) * 100
        if eps_yoy > 0:
            peg = f"{float(per) / eps_yoy:.2f}"
    oper_margin = f"{(sum(qt_oper[-4:]) / sales_ttm_billion * 100):.2f}%" if len(qt_oper) >= 4 and sales_ttm_billion > 0 else "-"
    return [market_cap, sales_ttm, sales_qq, sales_yy, sales_past, current_ratio, de, "-", ps, per, pbr, roe, peg, shares, "-", oper_margin, eps_ttm, eps_next, eps_qq, "-"]


def fetch_us_valuation(symbol: str) -> list[str]:
    html = fetch_text(f"https://finviz.com/quote.ashx?t={urllib.parse.quote(symbol)}&p=d")
    labels = [
        "Market Cap", "Sales", "Sales Q/Q", "Sales Y/Y TTM", "Sales past 3/5Y",
        "Current Ratio", "Debt/Eq", "P/FCF", "P/S", "P/E", "P/B", "ROE", "PEG",
        "Shs Outstand", "Gross Margin", "Oper. Margin", "EPS (ttm)", "EPS next Y", "EPS Q/Q",
    ]
    values = []
    for label in labels:
        pattern = re.escape(label) + r"</div></td><td[^>]*><div[^>]*><b>([\s\S]*?)</b>"
        match = re.search(pattern, html)
        values.append(re.sub(r"<.*?>", "", match.group(1)).strip() if match else "-")
    sector_match = re.search(r'href="screener\?v=111&f=sec_[^"]+"[^>]*>([\s\S]*?)</a>', html)
    industry_match = re.search(r'href="screener\?v=111&f=ind_[^"]+"[^>]*>([\s\S]*?)</a>', html)
    sector = re.sub(r"<.*?>", "", sector_match.group(1)).strip() if sector_match else "-"
    industry = re.sub(r"<.*?>", "", industry_match.group(1)).strip() if industry_match else "-"
    values.append(" | ".join(value for value in (sector, industry) if value != "-") or "-")
    return values


def fetch_valuation(ticker: str) -> list[str]:
    return fetch_korean_valuation(ticker) if resolve_market(ticker) == "KR" else fetch_us_valuation(ticker)
