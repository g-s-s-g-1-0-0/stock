"""Record private research observations for the US premarket gap-and-go setup.

This script never touches web/public, notifications, recommendations, or trade
state.  It only updates ``data/history/gap-go`` so the rule can be tested after
enough forward observations have accumulated.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STOCKS_PATH = ROOT / "data" / "cache" / "stocks.json"
HISTORY_DIR = ROOT / "data" / "history" / "gap-go"
NEW_YORK = ZoneInfo("America/New_York")
MAX_TICKERS = 200


def stage_at(now: datetime) -> str | None:
    """Choose the observation window in New York time, independent of DST."""
    local = now.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return None
    minute = local.hour * 60 + local.minute
    if 9 * 60 + 20 <= minute <= 9 * 60 + 35:
        return "premarket"
    if 10 * 60 <= minute <= 10 * 60 + 15:
        return "ten_am"
    if 16 * 60 + 5 <= minute <= 16 * 60 + 20:
        return "close"
    return None


def load_us_tickers(path: Path = STOCKS_PATH) -> list[str]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    tickers = {
        str(row.get("ticker") or "").strip().upper()
        for row in rows
        if isinstance(row, dict) and str(row.get("market") or "").upper() == "US"
    }
    return sorted(ticker for ticker in tickers if ticker and "." not in ticker)[:MAX_TICKERS]


def _series(frame: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    if isinstance(frame.columns, pd.MultiIndex):
        for key in ((field, ticker), (ticker, field)):
            if key in frame.columns:
                return frame[key].dropna()
        return pd.Series(dtype=float)
    return frame[field].dropna() if field in frame.columns else pd.Series(dtype=float)


def _num(value: Any) -> float | None:
    return float(value) if value is not None and pd.notna(value) else None


def _snapshot(minute: pd.DataFrame, daily: pd.DataFrame, ticker: str, today: datetime) -> dict[str, Any]:
    close = _series(minute, "Close", ticker)
    high = _series(minute, "High", ticker)
    low = _series(minute, "Low", ticker)
    volume = _series(minute, "Volume", ticker)
    if close.empty:
        return {"ticker": ticker, "dataAvailable": False}

    index = pd.DatetimeIndex(close.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    index = index.tz_convert(NEW_YORK)
    session = pd.Timestamp(today.date(), tz=NEW_YORK)
    pre = (index >= session + pd.Timedelta(hours=4)) & (index < session + pd.Timedelta(hours=9, minutes=30))
    regular = (index >= session + pd.Timedelta(hours=9, minutes=30)) & (index <= session + pd.Timedelta(hours=16))
    through_ten = regular & (index <= session + pd.Timedelta(hours=10))

    previous_close = _series(daily, "Close", ticker)
    previous_close = _num(previous_close.iloc[-2]) if len(previous_close) >= 2 else None
    pre_last = _num(close.iloc[pre.nonzero()[0][-1]]) if pre.any() else None
    regular_open = _num(close.iloc[regular.nonzero()[0][0]]) if regular.any() else None
    ten_price = _num(close.iloc[through_ten.nonzero()[0][-1]]) if through_ten.any() else None
    pre_high = _num(high.iloc[pre].max()) if pre.any() else None
    ten_high = _num(high.iloc[through_ten].max()) if through_ten.any() else None
    gap_pct = (pre_last / previous_close - 1) if pre_last and previous_close else None
    return {
        "ticker": ticker,
        "dataAvailable": True,
        "previousClose": previous_close,
        "premarketLast": pre_last,
        "premarketHigh": pre_high,
        "premarketLow": _num(low.iloc[pre].min()) if pre.any() else None,
        "premarketVolume": _num(volume.iloc[pre].sum()) if pre.any() else None,
        "regularOpen": regular_open,
        "tenAmPrice": ten_price,
        "tenAmHigh": ten_high,
        "volumeThroughTen": _num(volume.iloc[through_ten].sum()) if through_ten.any() else None,
        "dayHigh": _num(high.iloc[regular].max()) if regular.any() else None,
        "dayClose": _num(close.iloc[regular].iloc[-1]) if regular.any() else None,
        "dayVolume": _num(volume.iloc[regular].sum()) if regular.any() else None,
        "gapPct": gap_pct,
        "gapScreen": bool(gap_pct is not None and gap_pct >= 0.05 and pre_high is not None),
        "tenAmBreakout": bool(ten_price is not None and pre_high is not None and ten_price > pre_high),
    }


def _path(date_value: str) -> Path:
    return HISTORY_DIR / f"gap-go-observations-{date_value}.jsonl"


def upsert(path: Path, rows: list[dict[str, Any]]) -> None:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                existing[(row["ticker"], row["stage"])] = row
            except (json.JSONDecodeError, KeyError):
                continue
    for row in rows:
        existing[(row["ticker"], row["stage"])] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(existing.values(), key=lambda row: (row["stage"], row["ticker"]))
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered), encoding="utf-8")


def record(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    stage = stage_at(current)
    if stage is None:
        print("[gap-go] outside observation window; skipped")
        return 0
    tickers = load_us_tickers()
    if not tickers:
        raise RuntimeError("no US tickers found in data/cache/stocks.json")

    import yfinance as yf

    minute = yf.download(tickers, period="1d", interval="1m", prepost=True, auto_adjust=False, progress=False, threads=True)
    daily = yf.download(tickers, period="5d", interval="1d", auto_adjust=False, progress=False, threads=True)
    date_value = current.astimezone(NEW_YORK).date().isoformat()
    captured_at = current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    rows = [{
        **_snapshot(minute, daily, ticker, current.astimezone(NEW_YORK)),
        "stage": stage,
        "observationDate": date_value,
        "capturedAt": captured_at,
    } for ticker in tickers]
    target = _path(date_value)
    upsert(target, rows)
    print(f"[gap-go] wrote {len(rows)} {stage} observations to {target.relative_to(ROOT)}")
    return len(rows)


if __name__ == "__main__":
    record()
