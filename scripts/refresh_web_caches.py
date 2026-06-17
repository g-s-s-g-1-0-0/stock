"""Refresh web caches for tickers currently saved in Supabase watchlists."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from calculator import build_stock_universe
from calculator.pipeline import build_stock_search_cache, read_search_universe, run, write_cache
from scripts.record_signal_snapshots import record_daily_signal_snapshots

VALID_TASKS = {"stock-universe", "valuation", "technical", "stocks", "market-trends", "market-events"}
TRADE_LOG_PATHS = [
    ROOT_DIR / "web" / "public" / "api" / "trade-logs.json",
    ROOT_DIR / "data" / "cache" / "trade-logs.json",
]


def supabase_request(path: str) -> list[dict]:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        return []

    request = urllib.request.Request(
        supabase_url + path,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def load_watchlist_tickers() -> list[str]:
    rows = supabase_request("/rest/v1/watchlists?select=tickers,tickers_by_type&scope=eq.operator&owner_id=is.null")
    tickers: list[str] = []
    for row in rows:
        append_watchlist_values(tickers, row.get("tickers"))
        by_type = row.get("tickers_by_type")
        if isinstance(by_type, dict):
            for values in by_type.values():
                append_watchlist_values(tickers, values)
    return tickers


def append_unique(tickers: list[str], value: object) -> None:
    ticker = str(value or "").strip().upper()
    if ticker and ticker not in tickers:
        tickers.append(ticker)


def append_watchlist_values(tickers: list[str], values: object) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        append_unique(tickers, value)


def load_open_trade_tickers() -> list[str]:
    for path in TRADE_LOG_PATHS:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("rows") if isinstance(payload, dict) else []
        tickers: list[str] = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("status") or "") == "보유 중":
                append_unique(tickers, row.get("ticker"))
        return tickers
    return []


def refresh_tickers() -> list[str]:
    tickers = load_watchlist_tickers()
    for ticker in load_open_trade_tickers():
        append_unique(tickers, ticker)
    return tickers


def universe_for_tickers(tickers: list[str]) -> list[dict[str, str]]:
    requested = set(tickers)
    rows_by_ticker = {
        str(row.get("ticker", "")).strip().upper(): row
        for row in read_search_universe()
        if isinstance(row, dict)
    }
    universe = []
    for ticker in tickers:
        row = rows_by_ticker.get(ticker)
        if not row:
            continue
        universe.append({
            key: row[key]
            for key in ("ticker", "name", "market", "category", "industry", "rawIndustry", "products")
            if key in row
        })

    return universe


def refresh_search_universe() -> dict:
    payload = build_stock_universe.build()
    build_stock_universe.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    build_stock_universe.OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    search_payload = build_stock_search_cache()
    write_cache("stock-search", search_payload)
    return payload


def parse_tasks(argv: list[str]) -> list[str]:
    raw_values = argv or [os.environ.get("REFRESH_TASKS", "all")]
    tasks: list[str] = []
    for raw in raw_values:
        for value in str(raw or "").replace(",", " ").split():
            task = value.strip()
            if not task:
                continue
            if task == "all":
                return ["stock-universe", "valuation", "technical", "stocks", "market-trends", "market-events"]
            if task not in VALID_TASKS:
                raise SystemExit(f"unknown refresh task: {task}")
            if task not in tasks:
                tasks.append(task)

    if not tasks:
        return ["valuation", "technical", "stocks", "market-trends", "market-events"]
    if ("valuation" in tasks or "technical" in tasks) and "stocks" not in tasks:
        tasks.append("stocks")
    return tasks


def main() -> None:
    tasks = parse_tasks(sys.argv[1:])
    if "stock-universe" in tasks:
        payload = refresh_search_universe()
        print(f"wrote search-universe: {payload['meta']['updatedAt']} ({payload['meta']['count']} stocks)")
    tickers = refresh_tickers()
    universe = universe_for_tickers(tickers)
    print(f"refresh universe size: {len(universe)}")
    print(f"refresh tasks: {', '.join(tasks)}")
    if "valuation" in tasks:
        run("valuation", universe=universe)
    if "technical" in tasks:
        run("technical", universe=universe)
        record_daily_signal_snapshots()
    if "stocks" in tasks:
        run("stocks", universe=universe)
    if "market-trends" in tasks:
        run("market-trends")
    if "market-events" in tasks:
        run("market-events")


if __name__ == "__main__":
    main()
