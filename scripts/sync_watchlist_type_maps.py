"""Sync watchlist type maps from the canonical flat ticker list.

The web app treats watchlists.tickers as the canonical cross-device list.
This script repairs stale tickers_by_type values without resetting or changing
the flat list.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


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


def desired_type_map(tickers: list[str]) -> dict[str, list[str]]:
    return {
        "long_term": tickers,
        "swing": tickers,
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
        tickers = normalize_tickers(row.get("tickers"))
        if not row_id or not tickers:
            continue
        desired = desired_type_map(tickers)
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
            f"owner={owner} count={len(tickers)}"
        )

    print(f"[watchlist-sync] updated rows: {updated}")


if __name__ == "__main__":
    main()
