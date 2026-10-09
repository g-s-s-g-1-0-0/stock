"""Map a 2x/3x product to the unlevered chart that should be read first.

The daily 2x/3x chart exaggerates the same move, so the trend view leads with
the 1x reference. Index products use the liquid 1x ETF for that industry
(semiconductors → SOXX, Nasdaq-100 → QQQ). A single-name product uses the
stock named in its industry label.
"""

from __future__ import annotations

import re
from typing import Any

# Known products whose name does not spell the multiple or the index.
CURATED: dict[str, dict[str, Any]] = {
    "SOXL": {"ticker": "SOXX", "multiple": 3, "kind": "etf", "label": "반도체"},
    "SOXS": {"ticker": "SOXX", "multiple": -3, "kind": "etf", "label": "반도체"},
    "USD": {"ticker": "SOXX", "multiple": 2, "kind": "etf", "label": "반도체"},
    "QLD": {"ticker": "QQQ", "multiple": 2, "kind": "etf", "label": "나스닥100"},
    "TQQQ": {"ticker": "QQQ", "multiple": 3, "kind": "etf", "label": "나스닥100"},
    "SQQQ": {"ticker": "QQQ", "multiple": -3, "kind": "etf", "label": "나스닥100"},
    "QID": {"ticker": "QQQ", "multiple": -2, "kind": "etf", "label": "나스닥100"},
    "TECL": {"ticker": "XLK", "multiple": 3, "kind": "etf", "label": "기술"},
    "TECS": {"ticker": "XLK", "multiple": -3, "kind": "etf", "label": "기술"},
    "SPXL": {"ticker": "SPY", "multiple": 3, "kind": "etf", "label": "S&P500"},
    "UPRO": {"ticker": "SPY", "multiple": 3, "kind": "etf", "label": "S&P500"},
    "SPXS": {"ticker": "SPY", "multiple": -3, "kind": "etf", "label": "S&P500"},
    "SSO": {"ticker": "SPY", "multiple": 2, "kind": "etf", "label": "S&P500"},
    "SDS": {"ticker": "SPY", "multiple": -2, "kind": "etf", "label": "S&P500"},
    "TNA": {"ticker": "IWM", "multiple": 3, "kind": "etf", "label": "러셀2000"},
    "TZA": {"ticker": "IWM", "multiple": -3, "kind": "etf", "label": "러셀2000"},
    "UDOW": {"ticker": "DIA", "multiple": 3, "kind": "etf", "label": "다우"},
    "SDOW": {"ticker": "DIA", "multiple": -3, "kind": "etf", "label": "다우"},
    "FAS": {"ticker": "XLF", "multiple": 3, "kind": "etf", "label": "금융"},
    "FAZ": {"ticker": "XLF", "multiple": -3, "kind": "etf", "label": "금융"},
    "LABU": {"ticker": "XBI", "multiple": 3, "kind": "etf", "label": "바이오"},
    "LABD": {"ticker": "XBI", "multiple": -3, "kind": "etf", "label": "바이오"},
    "TSLL": {"ticker": "TSLA", "multiple": 2, "kind": "stock", "label": "테슬라"},
    "CONL": {"ticker": "COIN", "multiple": 2, "kind": "stock", "label": "코인베이스"},
    "HOOG": {"ticker": "HOOD", "multiple": 2, "kind": "stock", "label": "로빈후드"},
}

# More specific industries come first. Semiconductor wins over "다우존스".
INDEX_REFERENCES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("반도체", "semiconductor"), "SOXX", "반도체"),
    (("나스닥100", "nasdaq-100", "nasdaq 100"), "QQQ", "나스닥100"),
    (("러셀2000", "russell 2000"), "IWM", "러셀2000"),
    (("s&p500", "s&p 500", "sp500"), "SPY", "S&P500"),
    (("기술주", "technology select"), "XLK", "기술"),
    (("금융", "financial select"), "XLF", "금융"),
    (("바이오", "biotech"), "XBI", "바이오"),
    (("에너지", "energy select"), "XLE", "에너지"),
    (("비트코인", "bitcoin"), "IBIT", "비트코인"),
    (("이더리움", "ethereum"), "ETHA", "이더리움"),
    (("다우존스", "dow jones"), "DIA", "다우"),
)

_NOT_A_TICKER = {
    "ETF", "ETN", "USA", "NYSE", "USD", "AI", "US", "THE", "AND", "DAILY",
    "BULL", "BEAR", "LONG", "SHORT", "PRO", "ULTRA",
}


def _text(stock: dict[str, Any]) -> str:
    return " ".join(
        str(stock.get(key) or "")
        for key in ("ticker", "name", "industry")
    )


def _multiple(text: str) -> int | None:
    match = re.search(r"([23])\s*배", text) or re.search(r"\b([23])\s*x\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    inverse = bool(re.search(r"인버스|곱버스", text)) or bool(
        re.search(r"\b(bear|inverse|ultrashort)\b", text, flags=re.IGNORECASE)
    ) or bool(
        re.search(r"\bshort\b", text, flags=re.IGNORECASE)
        and not re.search(r"short[-\s]?term", text, flags=re.IGNORECASE)
    )
    return -value if inverse else value


def _single_name(text: str, product: str) -> str | None:
    patterns = (
        r"\(([A-Z]{1,5})\)",
        r"\b(?:Long|Short)\s+([A-Z]{1,5})\b",
        r"\b([A-Z]{2,5})\s+2x\b",
        r"\b([A-Z]{2,5})\s+3x\b",
    )
    for pattern in patterns:
        for found in re.findall(pattern, text, flags=re.IGNORECASE):
            ticker = str(found).upper()
            if ticker in _NOT_A_TICKER or ticker == product:
                continue
            return ticker
    return None


def resolve_leveraged_reference(stock: dict[str, Any]) -> dict[str, Any] | None:
    """Return the 1x reference for a 2x/3x product, or None for everything else."""

    product = str(stock.get("ticker") or "").strip().upper()
    if not product:
        return None
    curated = CURATED.get(product)
    if curated and curated["ticker"] != product:
        return {"product": product, **curated}

    text = _text(stock)
    multiple = _multiple(text)
    if multiple is None:
        return None
    lowered = text.lower()
    for tokens, ticker, label in INDEX_REFERENCES:
        if any(token in lowered for token in tokens) and ticker != product:
            return {
                "product": product,
                "ticker": ticker,
                "multiple": multiple,
                "kind": "etf",
                "label": label,
            }
    underlying = _single_name(text, product)
    if not underlying:
        return None
    return {
        "product": product,
        "ticker": underlying,
        "multiple": multiple,
        "kind": "stock",
        "label": underlying,
    }
