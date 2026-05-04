"""Small JSON API for the cached web data.

Run locally with:
  python api_server.py
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
CACHE_DIR = ROOT_DIR / "data" / "cache"
WEB_PUBLIC_API_DIR = ROOT_DIR / "web" / "public" / "api"

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


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
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
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
            self._send_json(400, {"error": "groups must be an array"})
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        WEB_PUBLIC_API_DIR.mkdir(parents=True, exist_ok=True)
        for directory in (CACHE_DIR, WEB_PUBLIC_API_DIR):
            (directory / "market-events.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self._send_json(200, payload)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("API server listening on http://127.0.0.1:8787")
    server.serve_forever()


if __name__ == "__main__":
    main()
