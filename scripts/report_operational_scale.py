"""Report lightweight scale metrics for the web service.

This runs inside GitHub Actions after cache refreshes. It is intentionally
read-only and best-effort: missing Supabase secrets should not fail the refresh.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_API_DIR = ROOT_DIR / "web" / "public" / "api"
MAX_REFRESH_UNIVERSE = int(os.environ.get("MAX_REFRESH_UNIVERSE", "200"))
WARN_JSON_BYTES = 5 * 1024 * 1024
PAGE_SIZE = 1000


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def rows_count(payload: Any) -> int:
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        return len(rows)
    if isinstance(rows, dict):
        return len(rows)
    return 0


def print_cache_metrics() -> None:
    for name in ["stocks", "stock-search", "valuation", "technical", "market-trends", "market-events"]:
        path = PUBLIC_API_DIR / f"{name}.json"
        size = path.stat().st_size if path.exists() else 0
        payload = read_json(path)
        warning = " WARN large-json" if size > WARN_JSON_BYTES else ""
        print(f"[scale] cache.{name}.bytes={size} rows={rows_count(payload)}{warning}")


def supabase_request(path: str, *, headers: dict[str, str] | None = None) -> tuple[Any, dict[str, str]]:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        return [], {}

    request = urllib.request.Request(
        supabase_url + path,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else []
            return payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase request failed: {exc.code} {detail}") from exc


def supabase_count(table: str) -> int | None:
    encoded_table = urllib.parse.quote(table, safe="")
    payload, headers = supabase_request(
        f"/rest/v1/{encoded_table}?select=id",
        headers={"Prefer": "count=exact", "Range": "0-0"},
    )
    if not headers and payload == []:
        return None

    content_range = headers.get("Content-Range", "")
    if "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else None


def load_watchlists() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "select": "scope,tickers",
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            },
            safe=",",
        )
        payload, _ = supabase_request(f"/rest/v1/watchlists?{query}")
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(row for row in payload if isinstance(row, dict))
        if len(payload) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def print_supabase_metrics() -> None:
    try:
        profiles = supabase_count("profiles")
    except Exception as exc:  # noqa: BLE001 - reporting should stay best-effort
        profiles = f"error:{exc}"
    try:
        user_settings = supabase_count("user_settings")
    except Exception as exc:  # noqa: BLE001 - reporting should stay best-effort
        user_settings = f"error:{exc}"
    try:
        watchlists = load_watchlists()
    except Exception as exc:  # noqa: BLE001 - reporting should stay best-effort
        print(f"[scale] watchlists.report_error={exc}")
        watchlists = []

    unique_tickers: set[str] = set()
    max_watchlist_size = 0
    personal_watchlists = 0
    for row in watchlists:
        tickers = [
            str(ticker or "").strip().upper()
            for ticker in row.get("tickers") or []
            if str(ticker or "").strip()
        ]
        unique_tickers.update(tickers)
        max_watchlist_size = max(max_watchlist_size, len(tickers))
        if row.get("scope") == "personal":
            personal_watchlists += 1

    unique_warning = " WARN exceeds-refresh-universe" if len(unique_tickers) > MAX_REFRESH_UNIVERSE else ""
    print(f"[scale] supabase.profiles={profiles if profiles is not None else 'unknown'}")
    print(f"[scale] supabase.user_settings={user_settings if user_settings is not None else 'unknown'}")
    print(f"[scale] watchlists.total={len(watchlists)} personal={personal_watchlists}")
    print(f"[scale] watchlists.unique_tickers={len(unique_tickers)} max_size={max_watchlist_size}{unique_warning}")


def main() -> int:
    print_cache_metrics()
    try:
        print_supabase_metrics()
    except Exception as exc:  # noqa: BLE001 - report should not block refresh
        print(f"[scale] supabase.report_error={exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
