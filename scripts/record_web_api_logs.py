"""Record stock-level web refresh logs in Supabase api_logs."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "web" / "public" / "api"
PREVIOUS_STOCKS_PATH = ROOT_DIR / "data" / "cache" / "stocks.before-refresh.json"
MAX_LOG_ROWS = 80
VALID_TASKS = {"value-analysis", "technical-analysis", "market-trends"}


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def supabase_request(path: str, method: str = "GET", payload: Any | None = None) -> Any | None:
    url = supabase_url()
    key = service_key()
    if not url or not key:
        print("[api_logs] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing; skipped.")
        return None

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url + path,
        data=body,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    if method == "GET" and raw:
        return json.loads(raw.decode("utf-8"))
    return None


def clean_old_logs() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    supabase_request(f"/rest/v1/api_logs?created_at=lt.{cutoff}", method="DELETE")


def load_watchlist_tickers(stocks: list[dict[str, Any]]) -> list[str]:
    rows = supabase_request("/rest/v1/watchlists?select=tickers")
    tickers: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            values = row.get("tickers") if isinstance(row, dict) else None
            if not isinstance(values, list):
                continue
            for value in values:
                ticker = str(value or "").strip().upper()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
    if tickers:
        return tickers[:MAX_LOG_ROWS]

    tickers = [
        str(stock.get("ticker", "")).strip().upper()
        for stock in stocks
        if str(stock.get("ticker", "")).strip()
    ]
    return tickers[:MAX_LOG_ROWS]


def stocks_by_ticker(stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(stock.get("ticker", "")).strip().upper(): stock
        for stock in stocks
        if str(stock.get("ticker", "")).strip()
    }


def parse_log_tasks(argv: list[str]) -> set[str]:
    aliases = {
        "all": {"value-analysis", "technical-analysis", "market-trends"},
        "valuation": {"value-analysis"},
        "value-analysis": {"value-analysis"},
        "technical": {"technical-analysis"},
        "technical-analysis": {"technical-analysis"},
        "market-trends": {"market-trends"},
    }
    raw_values = argv or [os.environ.get("REFRESH_TASKS", "all")]
    tasks: set[str] = set()
    for raw in raw_values:
        for value in str(raw or "").replace(",", " ").split():
            if not value:
                continue
            matched = aliases.get(value)
            if matched is None:
                # stocks and market-events do not have separate operation-log tabs.
                if value in {"stocks", "market-events"}:
                    continue
                raise SystemExit(f"unknown log task: {value}")
            tasks.update(matched)
    return tasks or set(VALID_TASKS)


def value_log_rows(stocks: list[dict[str, Any]], valuation: dict[str, Any], tickers: set[str]) -> list[dict[str, Any]]:
    rows = []
    for stock in stocks:
        ticker = str(stock.get("ticker", "")).upper()
        if ticker not in tickers:
            continue
        metric = valuation.get(ticker, {}) if isinstance(valuation, dict) else {}
        rows.append({
            "ticker": ticker,
            "name": stock.get("name") or "-",
            "market": stock.get("market") or "-",
            "industry": stock.get("industry") or "-",
            "currentPrice": stock.get("currentPrice") or "-",
            "fairPrice": stock.get("fairPrice") or "-",
            "valuation": stock.get("valuation") or "-",
            "opinion": "-" if stock.get("fairPriceReason") == "loss_making" else stock.get("opinion", "-"),
            "per": metric.get("per", "-"),
            "epsTtm": metric.get("epsTtm", "-"),
            "roe": metric.get("roe", "-"),
            "updatedAt": stock.get("updatedAt") or "-",
        })
    return rows[:MAX_LOG_ROWS]


def tech_value(row: dict[str, Any], *candidates: str) -> Any:
    for candidate in candidates:
        if candidate in row and row[candidate]:
            return row[candidate]
        found = next((value for key, value in row.items() if candidate.lower() in str(key).lower() and value), None)
        if found:
            return found
    return "-"


def technical_log_rows(
    stocks: list[dict[str, Any]],
    previous_stocks: dict[str, dict[str, Any]],
    technical: dict[str, Any],
    tickers: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for stock in stocks:
        ticker = str(stock.get("ticker", "")).upper()
        if ticker not in tickers:
            continue
        row = technical.get(ticker, {}) if isinstance(technical, dict) else {}
        previous_opinion = str(previous_stocks.get(ticker, {}).get("opinion") or "-")
        current_opinion = str(stock.get("opinion") or "-")
        strategies = stock.get("strategies")
        rows.append({
            "ticker": ticker,
            "name": stock.get("name") or row.get("name") or "-",
            "change": "변경" if previous_opinion != current_opinion else "유지",
            "opinion": f"{previous_opinion} -> {current_opinion}",
            "strategy": ", ".join(str(v) for v in strategies) if isinstance(strategies, list) and strategies else tech_value(row, "진입 전략"),
            "decision": row.get("decisionLog") or row.get("conditionSummary") or "-",
            "currentPrice": tech_value(row, "현재가") or stock.get("currentPrice") or "-",
            "rsi": tech_value(row, "RSI"),
            "pctB": tech_value(row, "%B"),
            "ma200": tech_value(row, "MA200", "200일선"),
        })
    return rows[:MAX_LOG_ROWS]


def market_trend_log_rows(market_trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for trend in market_trends[:12]:
        for index, rank_text in enumerate(trend.get("ranks") or [], start=1):
            parts = [part.strip() for part in str(rank_text).split("|")]
            rows.append({
                "date": trend.get("date") or "-",
                "rank": index,
                "sector": parts[0] if parts else "-",
                "keywords": parts[1] if len(parts) > 1 else "",
                "summary": trend.get("summary") or "-",
            })
    return rows


def actions_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def build_logs(enabled_tasks: set[str]) -> list[dict[str, Any]]:
    stocks_payload = load_json(API_DIR / "stocks.json", {"rows": []})
    previous_stocks_payload = load_json(PREVIOUS_STOCKS_PATH, {"rows": []})
    valuation_payload = load_json(API_DIR / "valuation.json", {"rows": {}})
    technical_payload = load_json(API_DIR / "technical.json", {"rows": {}})
    trends_payload = load_json(API_DIR / "market-trends.json", {"rows": []})

    stocks = stocks_payload.get("rows", []) if isinstance(stocks_payload, dict) else []
    previous_stocks_list = previous_stocks_payload.get("rows", []) if isinstance(previous_stocks_payload, dict) else []
    previous_stocks = stocks_by_ticker(previous_stocks_list)
    valuation = valuation_payload.get("rows", {}) if isinstance(valuation_payload, dict) else {}
    technical = technical_payload.get("rows", {}) if isinstance(technical_payload, dict) else {}
    market_trends = trends_payload.get("rows", []) if isinstance(trends_payload, dict) else []
    tickers = set(load_watchlist_tickers(stocks))
    base = {
        "source": "github-actions",
        "actionsUrl": actions_url(),
        "tickers": sorted(tickers),
    }

    value_rows = value_log_rows(stocks, valuation, tickers)
    technical_rows = technical_log_rows(stocks, previous_stocks, technical, tickers)
    trend_rows = market_trend_log_rows(market_trends)

    logs = [
        {
            "trigger_name": "value-analysis",
            "status": "success",
            "message": f"{len(value_rows)}개 종목 가치분석 데이터를 기록했습니다.",
            "metadata": {
                **base,
                "task": "value-analysis",
                "summary": "GitHub Actions 갱신 후 종목별 가치분석 스냅샷입니다.",
                "total": len(value_rows),
                "columns": [
                    {"key": "ticker", "label": "종목"},
                    {"key": "name", "label": "종목명"},
                    {"key": "currentPrice", "label": "현재가"},
                    {"key": "fairPrice", "label": "적정 주가 범위"},
                    {"key": "valuation", "label": "판단"},
                    {"key": "opinion", "label": "투자의견"},
                    {"key": "per", "label": "PER"},
                    {"key": "epsTtm", "label": "EPS(TTM)"},
                    {"key": "roe", "label": "ROE"},
                    {"key": "industry", "label": "산업"},
                ],
                "rows": value_rows,
            },
        },
        {
            "trigger_name": "technical-analysis",
            "status": "success",
            "message": f"{len(technical_rows)}개 종목 기술분석 데이터를 기록했습니다.",
            "metadata": {
                **base,
                "task": "technical-analysis",
                "summary": "GitHub Actions 갱신 후 종목별 기술분석 핵심 지표입니다.",
                "total": len(technical_rows),
                "columns": [
                    {"key": "ticker", "label": "종목"},
                    {"key": "name", "label": "종목명"},
                    {"key": "change", "label": "변경"},
                    {"key": "opinion", "label": "투자의견"},
                    {"key": "strategy", "label": "진입 전략"},
                    {"key": "decision", "label": "판단 로그"},
                    {"key": "currentPrice", "label": "현재가"},
                    {"key": "rsi", "label": "RSI"},
                    {"key": "pctB", "label": "%B"},
                    {"key": "ma200", "label": "MA200"},
                ],
                "rows": technical_rows,
            },
        },
        {
            "trigger_name": "market-trends",
            "status": "success",
            "message": f"{len(trend_rows)}개 시장 트렌드 항목을 기록했습니다.",
            "metadata": {
                **base,
                "task": "market-trends",
                "summary": "GitHub Actions 갱신 후 시장 트렌드 순위 데이터입니다.",
                "total": len(trend_rows),
                "columns": [
                    {"key": "date", "label": "기준일"},
                    {"key": "rank", "label": "순위"},
                    {"key": "sector", "label": "섹터"},
                    {"key": "keywords", "label": "키워드"},
                    {"key": "summary", "label": "요약"},
                ],
                "rows": trend_rows,
            },
        },
    ]
    return [log for log in logs if log["trigger_name"] in enabled_tasks]


def main() -> None:
    if not supabase_url() or not service_key():
        print("[api_logs] Supabase service credentials are missing; skipped.")
        return
    clean_old_logs()
    logs = build_logs(parse_log_tasks(sys.argv[1:]))
    if not logs:
        print("[api_logs] no matching operation-log tasks; skipped.")
        return
    supabase_request("/rest/v1/api_logs", method="POST", payload=logs)
    print(f"[api_logs] recorded {len(logs)} stock-level refresh logs.")


if __name__ == "__main__":
    main()
