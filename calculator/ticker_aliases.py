"""Canonical ticker remaps for temporary / when-issued symbols."""

from __future__ import annotations

from typing import Any

# when-issued → regular-way (Nasdaq ETA 2026-40: SKHYV → SKHY effective 2026-07-13)
CANONICAL_TICKERS: dict[str, str] = {
    "SKHYV": "SKHY",
}


def canonical_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if not ticker:
        return ""
    return CANONICAL_TICKERS.get(ticker, ticker)
