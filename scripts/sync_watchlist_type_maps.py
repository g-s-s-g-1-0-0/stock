"""Backfill watchlist type maps without merging personal investment types.

Operator watchlists still use the flat ticker list as the shared canonical
list. Personal watchlists do not: each investment type owns its own list, so
the flat ``tickers`` column only represents the currently active type.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


INVESTMENT_TYPES = ("long_term", "swing")


def supabase_config() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return url, key


def request_json(url: str, key: str, path: str, *, method: str = "GET", payload: Any = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={
            "apikey": key,
            "authorization": f"Bearer {key}",
            "accept": "application/json",
            "content-type": "application/json",
            "prefer": "return=minimal",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None


def normalize_tickers(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [ticker for ticker in value if isinstance(ticker, str) and ticker.strip()]


def canonical_type_map(tickers: list[str]) -> dict[str, list[str]]:
    return {
        "long_term": tickers,
        "swing": tickers,
    }


def normalize_type_map(value: Any) -> dict[str, list[str]] | None:
    if not isinstance(value, dict):
        return None

    normalized: dict[str, list[str]] = {}
    for investment_type in INVESTMENT_TYPES:
        if investment_type in value:
            normalized[investment_type] = normalize_tickers(value[investment_type])
    return normalized or None


def desired_type_map(row: dict[str, Any]) -> dict[str, list[str]]:
    tickers = normalize_tickers(row.get("tickers"))
    if row.get("scope") == "operator":
        return canonical_type_map(tickers)

    existing = normalize_type_map(row.get("tickers_by_type"))
    if not existing:
        return canonical_type_map(tickers)

    return {
        investment_type: existing[investment_type] if investment_type in existing else tickers
        for investment_type in INVESTMENT_TYPES
    }


def main() -> None:
    url, key = supabase_config()
    if not url or not key:
        print("[watchlist-sync] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing; skipped.")
        return

    rows = request_json(
        url,
        key,
        "/rest/v1/watchlists?select=id,scope,owner_id,tickers,tickers_by_type",
    )
    if not isinstance(rows, list):
        print("[watchlist-sync] no watchlist rows returned.")
        return

    updated = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        desired = desired_type_map(row)
        if row.get("tickers_by_type") == desired:
            continue
        request_json(
            url,
            key,
            f"/rest/v1/watchlists?id=eq.{urllib.parse.quote(row_id)}",
            method="PATCH",
            payload={"tickers_by_type": desired},
        )
        updated += 1
        owner = row.get("owner_id") or "operator"
        print(
            f"[watchlist-sync] synced scope={row.get('scope') or '-'} "
            f"owner={owner}"
        )

    print(f"[watchlist-sync] updated rows: {updated}")


if __name__ == "__main__":
    main()
