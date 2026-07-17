#!/usr/bin/env python3
"""Smoke-check that the deployed web bundle inlined Supabase client config.

Vite bakes VITE_SUPABASE_* into the JS at build time. If a production deploy
ran without those values, login breaks and the bundle will not contain a
supabase.co host. This script fails (exit 1) in that case so CI can page admins.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request


ASSET_RE = re.compile(r"""['"](/?assets/index-[^'"]+\.js)['"]""")
SUPABASE_HOST_RE = re.compile(r"https://[a-z0-9-]+\.supabase\.co", re.IGNORECASE)


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "gongsu-auth-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def resolve_app_url(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise SystemExit("WEB_APP_URL (or --url) is required.")
    if not value.startswith("http://") and not value.startswith("https://"):
        value = f"https://{value}"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="Deployed web origin (defaults to WEB_APP_URL)")
    args = parser.parse_args()

    import os

    origin = resolve_app_url(args.url or os.environ.get("WEB_APP_URL", ""))
    try:
        html = fetch_text(f"{origin}/")
    except urllib.error.URLError as exc:
        print(f"Failed to fetch {origin}/: {exc}", file=sys.stderr)
        return 1

    match = ASSET_RE.search(html)
    if not match:
        print("Could not find assets/index-*.js in the deployed HTML.", file=sys.stderr)
        return 1

    asset_path = match.group(1)
    asset_url = asset_path if asset_path.startswith("http") else f"{origin}/{asset_path.lstrip('/')}"
    try:
        js = fetch_text(asset_url)
    except urllib.error.URLError as exc:
        print(f"Failed to fetch {asset_url}: {exc}", file=sys.stderr)
        return 1

    if not SUPABASE_HOST_RE.search(js):
        print(
            "Deployed bundle is missing an inlined supabase.co URL. "
            "VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY were likely absent at build time.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: Supabase host found in {asset_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
