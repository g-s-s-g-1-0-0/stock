"""Build the searchable KR/US stock universe for the web app."""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from datetime import datetime, timezone
from io import StringIO
from html import unescape
from pathlib import Path
from typing import Any

from .industry_classification import classify_stock

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_PATH = DATA_DIR / "search_universe.json"

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
KRX_KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def clean_us_name(name: str) -> str:
    name = name.strip()
    for suffix in [
        " - Common Stock",
        " Common Stock",
        " Ordinary Shares",
        " Class A",
        " Class B",
        " Class C",
    ]:
        name = name.replace(suffix, "")
    return " ".join(name.split())


def load_us_stocks() -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}

    nasdaq_text = fetch_text(NASDAQ_LISTED_URL)
    for row in csv.DictReader(StringIO(nasdaq_text), delimiter="|"):
        ticker = (row.get("Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        if not ticker or ticker == "File Creation Time":
            continue
        if row.get("Test Issue") == "Y":
            continue
        if "$" in ticker or ticker.endswith((".W", ".R", ".U")):
            continue
        rows[ticker] = {"ticker": ticker, "name": clean_us_name(name), "market": "US"}

    other_text = fetch_text(OTHER_LISTED_URL)
    for row in csv.DictReader(StringIO(other_text), delimiter="|"):
        ticker = (row.get("ACT Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        if not ticker or ticker == "File Creation Time":
            continue
        if row.get("Test Issue") == "Y":
            continue
        if "$" in ticker or ticker.endswith((".W", ".R", ".U")):
            continue
        rows.setdefault(ticker, {"ticker": ticker, "name": clean_us_name(name), "market": "US"})

    return sorted(rows.values(), key=lambda item: item["ticker"])


def load_kr_stocks() -> list[dict[str, str]]:
    rows = load_kr_stocks_from_kind()
    if rows:
        return rows

    try:
        from pykrx import stock
    except ImportError as exc:
        raise RuntimeError("pykrx is required to build the KR search universe") from exc

    rows: dict[str, dict[str, str]] = {}
    today = datetime.now().strftime("%Y%m%d")
    for market in ("KOSPI", "KOSDAQ", "KONEX"):
        for ticker in stock.get_market_ticker_list(today, market=market):
            name = stock.get_market_ticker_name(ticker)
            if name:
                rows[ticker] = {"ticker": ticker, "name": name, "market": "KR"}
    return sorted(rows.values(), key=lambda item: item["ticker"])


def load_kr_stocks_from_kind() -> list[dict[str, str]]:
    html = fetch_bytes(KRX_KIND_URL).decode("euc-kr", errors="ignore")
    table_rows: dict[str, dict[str, str]] = {}
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
        cells = [
            " ".join(unescape(re.sub(r"<[^>]+>", "", cell)).split())
            for cell in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr)
        ]
        if len(cells) < 3 or cells[0] == "회사명":
            continue
        name, market_name, ticker = cells[0], cells[1], cells[2]
        if not name or not ticker:
            continue
        table_rows[ticker] = {
            "ticker": ticker,
            "name": name,
            "market": "KR",
            "exchange": market_name,
            "rawIndustry": cells[3] if len(cells) > 3 and cells[3] else "-",
            "products": cells[4] if len(cells) > 4 and cells[4] else "-",
        }
    return sorted(table_rows.values(), key=lambda item: item["ticker"])


def stock_shell(row: dict[str, str], updated_at: str) -> dict[str, Any]:
    classification = classify_stock(row)
    return {
        "ticker": row["ticker"],
        "name": row["name"],
        "market": row["market"],
        "fairPrice": "-",
        "currentPrice": "-",
        "valuation": "보통",
        "opinion": "관망",
        "strategies": [],
        "category": classification["category"],
        "industry": classification["industry"],
        "rawIndustry": row.get("rawIndustry", "-"),
        "products": row.get("products", "-"),
        "updatedAt": updated_at,
    }


def build() -> dict[str, Any]:
    updated_at = now_iso()
    rows = [stock_shell(row, updated_at) for row in [*load_kr_stocks(), *load_us_stocks()]]
    return {
        "meta": {
            "kind": "search-universe",
            "updatedAt": updated_at,
            "markets": ["KR", "US"],
            "count": len(rows),
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    payload = build()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output}: {payload['meta']['count']} stocks")


if __name__ == "__main__":
    main()
