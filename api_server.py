"""Small JSON API for the cached web data.

Run locally with:
  python api_server.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from calculator.pipeline import read_search_universe, run

ROOT_DIR = Path(__file__).resolve().parent
CACHE_DIR = ROOT_DIR / "data" / "cache"
WEB_PUBLIC_API_DIR = ROOT_DIR / "web" / "public" / "api"
API_LOG_PATH = CACHE_DIR / "api_logs.json"

ENDPOINTS = {
    "/api/stocks": "stocks.json",
    "/api/valuation": "valuation.json",
    "/api/technical": "technical.json",
    "/api/market-events": "market-events.json",
    "/api/market-trends": "market-trends.json",
}


def cache_path(filename: str) -> Path:
    primary = CACHE_DIR / filename
    if primary.exists():
        return primary
    return WEB_PUBLIC_API_DIR / filename


def append_api_log(trigger_name: str, status: str, message: str, metadata: dict | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=21)
    logs: list[dict] = []
    if API_LOG_PATH.exists():
        try:
            loaded = json.loads(API_LOG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                logs = loaded
        except json.JSONDecodeError:
            logs = []

    logs = [
        log for log in logs
        if datetime.fromisoformat(str(log.get("createdAt", "1970-01-01T00:00:00+00:00"))) >= cutoff
    ]
    logs.insert(0, {
        "id": f"local-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "triggerName": trigger_name,
        "status": status,
        "message": message,
        "metadata": metadata or {},
        "createdAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    })
    API_LOG_PATH.write_text(json.dumps(logs[:200], ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_universe_for_tickers(tickers: list[str]) -> list[dict[str, str]]:
    requested = {ticker.strip().upper() for ticker in tickers if isinstance(ticker, str) and ticker.strip()}
    if not requested:
        return []

    rows = []
    for stock in read_search_universe():
        ticker = stock.get("ticker", "").upper()
        if ticker in requested:
            rows.append({
                key: stock[key]
                for key in ("ticker", "name", "market", "category", "industry", "rawIndustry", "products")
                if key in stock
            })
    return rows[:50]


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        filename = ENDPOINTS.get(path)
        if not filename:
            self._send_json(404, {"error": "not found"})
            return
        source = cache_path(filename)
        if not source.exists():
            self._send_json(200, {"meta": {"failedReason": "cache not generated yet"}})
            return
        self._send_json(200, json.loads(source.read_text(encoding="utf-8")))

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/admin/market-events":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            append_api_log("market-events", "failure", "invalid json")
            self._send_json(400, {"error": "invalid json"})
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
            append_api_log("market-events", "failure", "groups must be an array")
            self._send_json(400, {"error": "groups must be an array"})
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        WEB_PUBLIC_API_DIR.mkdir(parents=True, exist_ok=True)
        for directory in (CACHE_DIR, WEB_PUBLIC_API_DIR):
            (directory / "market-events.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        append_api_log("market-events", "success", "market events saved", {"groups": len(payload.get("groups", []))})
        self._send_json(200, payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/admin/refresh-data":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("content-length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            append_api_log("refresh-data", "failure", "invalid json")
            self._send_json(400, {"error": "invalid json"})
            return

        universe = refresh_universe_for_tickers(payload.get("tickers", []))
        if not universe:
            append_api_log("refresh-data", "failure", "refresh tickers are empty or unknown")
            self._send_json(400, {"error": "refresh tickers are empty or unknown"})
            return

        try:
            run("valuation", universe=universe)
            run("technical", universe=universe)
            run("stocks")
        except Exception as exc:  # noqa: BLE001 - local refresh should report failures to the UI
            append_api_log("refresh-data", "failure", str(exc), {"tickers": [stock["ticker"] for stock in universe]})
            self._send_json(500, {"error": str(exc)})
            return

        refreshed_tickers = [stock["ticker"] for stock in universe]
        append_api_log("refresh-data", "success", "data refreshed", {"tickers": refreshed_tickers})
        self._send_json(200, {
            "ok": True,
            "refreshedTickers": refreshed_tickers,
        })


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("API server listening on http://127.0.0.1:8787")
    server.serve_forever()


if __name__ == "__main__":
    main()
