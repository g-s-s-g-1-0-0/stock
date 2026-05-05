"""Refresh web caches for tickers currently saved in Supabase watchlists."""

from __future__ import annotations

import json
import os
import urllib.request

from calculator.pipeline import read_search_universe, read_universe, run


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
    rows = supabase_request("/rest/v1/watchlists?select=tickers")
    tickers: list[str] = []
    for row in rows:
        values = row.get("tickers")
        if not isinstance(values, list):
            continue
        for value in values:
            ticker = str(value or "").strip().upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
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

    if universe:
        return universe

    # Fallback keeps local/dev refresh useful before Supabase is configured.
    return read_universe()


def main() -> None:
    tickers = load_watchlist_tickers()
    universe = universe_for_tickers(tickers)
    print(f"refresh universe size: {len(universe)}")
    run("valuation", universe=universe)
    run("technical", universe=universe)
    run("stocks")
    run("market-trends")
    run("market-events")


if __name__ == "__main__":
    main()
