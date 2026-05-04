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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .indicators import add_indicators
from .rules import IndicatorRow, evaluate_buy_condition, strategy_display_name

ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "data" / "cache"
WEB_PUBLIC_API_DIR = ROOT_DIR / "web" / "public" / "api"

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
    return loaded[:50]


def download_ohlcv(ticker: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for live technical batch runs") from exc

    yahoo_ticker = f"{ticker}.KS" if ticker.isdigit() else ticker
    raw = yf.download(yahoo_ticker, period="18mo", auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in raw.columns]
    return raw[cols].copy()


def fmt_number(value: Any, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.{decimals}f}"


def fmt_price(value: Any, market: str) -> str:
    if value is None or pd.isna(value):
        return "-"
    if market == "KR":
        return f"₩{round(float(value)):,.0f}"
    return f"${float(value):,.2f}"


def latest_technical_row(stock: dict[str, str]) -> dict[str, str] | None:
    df = download_ohlcv(stock["ticker"])
    if df.empty or len(df) < 220:
        return None
    enriched = add_indicators(df)
    row = enriched.iloc[-1]
    prev = enriched.iloc[-2] if len(enriched) > 1 else row
    price = float(row["Close"])
    ind = IndicatorRow(
        stock_name=stock["ticker"],
        current_price=price,
        ma200=float(row["MA200"]) if pd.notna(row["MA200"]) else None,
        rsi=float(row["RSI"]) if pd.notna(row["RSI"]) else None,
        cci=float(row["CCI"]) if pd.notna(row["CCI"]) else None,
        macd_hist=float(row["MACD_Hist"]) if pd.notna(row["MACD_Hist"]) else None,
        macd_hist_d1=float(row["MACD_Hist_D1"]) if pd.notna(row["MACD_Hist_D1"]) else None,
        macd_hist_d2=float(row["MACD_Hist_D2"]) if pd.notna(row["MACD_Hist_D2"]) else None,
        pct_b=float(row["PctB"]) if pd.notna(row["PctB"]) else None,
        pct_b_low=float(row["PctB_Low"]) if pd.notna(row["PctB_Low"]) else None,
        bb_width=float(row["BB_Width"]) if pd.notna(row["BB_Width"]) else None,
        bb_width_d1=float(row["BB_Width_D1"]) if pd.notna(row["BB_Width_D1"]) else None,
        bb_width_avg60=float(row["BB_Width60"]) if pd.notna(row["BB_Width60"]) else None,
        vol_ratio=float(row["VolRatio"]) if pd.notna(row["VolRatio"]) else None,
        plus_di=float(row["PlusDI"]) if pd.notna(row["PlusDI"]) else None,
        minus_di=float(row["MinusDI"]) if pd.notna(row["MinusDI"]) else None,
        adx=float(row["ADX"]) if pd.notna(row["ADX"]) else None,
        adx_d1=float(row["ADX_D1"]) if pd.notna(row["ADX_D1"]) else None,
        lr_slope=float(row["LR_Slope"]) if pd.notna(row["LR_Slope"]) else None,
        lr_trendline=float(row["LR_Trendline"]) if pd.notna(row["LR_Trendline"]) else None,
        candle_low=float(row["Low"]) if pd.notna(row["Low"]) else None,
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
        "RSI (D)": fmt_number(row["RSI"]),
        "RSI (D-1)": fmt_number(prev["RSI"]),
        "CCI (D)": fmt_number(row["CCI"]),
        "CCI (D-1)": fmt_number(prev["CCI"]),
        "MACD (12, 26, D)": fmt_number(row["MACD"]),
        "MACD Signal": fmt_number(row["MACD_Signal"]),
        "MACD Histogram (D)": fmt_number(row["MACD_Hist"]),
        "M - H (D-1)": fmt_number(row["MACD_Hist_D1"]),
        "M - H (D-2)": fmt_number(row["MACD_Hist_D2"]),
        "+DI (DMI, 14)": fmt_number(row["PlusDI"]),
        "-DI (DMI, 14)": fmt_number(row["MinusDI"]),
        "ADX (14, D)": fmt_number(row["ADX"]),
        "ADX (14, D-1)": fmt_number(row["ADX_D1"]),
        "Candle Open": fmt_price(row["Open"], stock["market"]),
        "C - High": fmt_price(row["High"], stock["market"]),
        "C - Low": fmt_price(row["Low"], stock["market"]),
        "C - Close": fmt_price(row["Close"], stock["market"]),
        "C - Volume": f"{int(row['Volume']):,}" if pd.notna(row["Volume"]) else "-",
        "볼린저밴드 %B (종가)": fmt_number(row["PctB"]),
        "볼린저밴드 %B (저가)": fmt_number(row["PctB_Low"]),
        "Bollinger Band Width": fmt_number(row["BB_Width"]),
        "Bollinger Band Width D-1": fmt_number(row["BB_Width_D1"]),
        "Bollinger Band Width 60MA": fmt_number(row["BB_Width60"]),
        "MA 200": fmt_price(row["MA200"], stock["market"]),
    }


def build_technical_cache() -> dict[str, Any]:
    rows: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    for stock in read_universe()[:50]:
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
        "marketSnapshot": [
            ["시장 주요 이벤트", "캐시 기준"],
            ["기술분석 갱신 주기", "2시간"],
        ],
        "rows": rows,
        "errors": errors,
    }


def build_valuation_cache() -> dict[str, Any]:
    return {
        "meta": {
            "kind": "valuation",
            "schedule": "0 0 * * *",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        },
        "rows": {},
    }


def build_stocks_cache() -> dict[str, Any]:
    rows = []
    for stock in read_universe()[:50]:
        rows.append({
            "ticker": stock["ticker"],
            "name": stock["name"],
            "market": stock["market"],
            "fairPrice": "-",
            "currentPrice": "-",
            "valuation": "보통",
            "opinion": "관망",
            "strategies": [],
            "updatedAt": now_iso(),
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


def build_market_trends_cache() -> dict[str, Any]:
    return {
        "meta": {
            "kind": "market-trends",
            "schedule": "0 0 * * 1",
            "updatedAt": now_iso(),
            "lastSuccessfulRun": now_iso(),
            "failedReason": None,
        },
        "rows": [],
    }


def build_market_events_cache() -> dict[str, Any]:
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


def run(job: str) -> None:
    jobs = {
        "stocks": build_stocks_cache,
        "valuation": build_valuation_cache,
        "technical": build_technical_cache,
        "market-trends": build_market_trends_cache,
        "market-events": build_market_events_cache,
    }
    selected = jobs.keys() if job == "all" else [job]
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
