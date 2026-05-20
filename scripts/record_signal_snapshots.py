"""Append daily technical signal snapshots for later strategy research."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
TECHNICAL_CACHE_PATH = ROOT_DIR / "data" / "cache" / "technical.json"
VALUATION_CACHE_PATH = ROOT_DIR / "data" / "cache" / "valuation.json"
STOCKS_CACHE_PATH = ROOT_DIR / "data" / "cache" / "stocks.json"
HISTORY_DIR = Path(os.environ.get("SIGNAL_HISTORY_DIR", str(ROOT_DIR / "data" / "history")))
KST = ZoneInfo("Asia/Seoul")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def snapshot_date(now: datetime | None = None) -> str:
    override = os.environ.get("SIGNAL_SNAPSHOT_DATE", "").strip()
    if override:
        return override
    current = now or datetime.now(timezone.utc)
    return current.astimezone(KST).strftime("%Y-%m-%d")


def captured_at(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def history_path(date_value: str) -> Path:
    return HISTORY_DIR / f"daily-signal-snapshots-{date_value[:7]}.jsonl"


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.+-]", "", str(value))
    if cleaned in {"", "+", "-", ".", "+.", "-."}:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if parsed == parsed else None


def parse_percent_ratio(value: Any) -> float | None:
    parsed = parse_number(value)
    if parsed is None:
        return None
    return parsed / 100 if "%" in str(value) else parsed


def normalize_entry_codes(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else str(value or "").replace("/", ",").split(",")
    codes: list[str] = []
    for raw in raw_values:
        code = str(raw or "").split(".", 1)[0].strip().upper()
        if code and code not in codes:
            codes.append(code)
    return codes


def stocks_by_ticker(stocks_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = stocks_payload.get("rows", []) if isinstance(stocks_payload, dict) else []
    return {
        str(row.get("ticker") or "").strip().upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("ticker") or "").strip()
    }


def build_snapshot_row(
    ticker: str,
    row: dict[str, Any],
    *,
    stock: dict[str, Any] | None,
    valuation: dict[str, Any] | None,
    qqq_state: dict[str, Any],
    date_value: str,
    captured_value: str,
) -> dict[str, Any]:
    current_price = parse_number(row.get("현재가") or row.get("currentPrice"))
    ma200 = parse_number(row.get("200일 이동평균선"))
    pct_b = parse_number(row.get("볼린저밴드 %B (종가)"))
    pct_b_low = parse_number(row.get("볼린저밴드 %B (저가)"))
    rsi = parse_number(row.get("RSI (D)"))
    macd_hist = parse_number(row.get("MACD Histogram (D)"))
    macd_hist_d1 = parse_number(row.get("M - H (D-1)"))
    macd_hist_d2 = parse_number(row.get("M - H (D-2)"))
    plus_di = parse_number(row.get("+DI (DMI, 14)"))
    minus_di = parse_number(row.get("-DI (DMI, 14)"))
    adx = parse_number(row.get("ADX (14, D)"))
    adx_d1 = parse_number(row.get("ADX (14, D-1)"))
    volume_ratio = parse_percent_ratio(row.get("거래량 (D)"))
    volume_ratio20 = parse_percent_ratio(row.get("20일 평균 대비 거래량 (D)"))
    qqq_premium = parse_number(qqq_state.get("premiumPercent"))
    qqq_buy_block_max = parse_number(qqq_state.get("buyBlockMax"))

    h_candidate = all(
        condition is True
        for condition in (
            qqq_premium is not None and qqq_buy_block_max is not None and qqq_premium <= qqq_buy_block_max,
            current_price is not None and ma200 is not None and current_price > ma200,
            pct_b is not None and pct_b >= 90,
            macd_hist is not None and macd_hist > 0,
            macd_hist is not None and macd_hist_d1 is not None and macd_hist > macd_hist_d1,
            volume_ratio20 is not None and volume_ratio20 >= 1.5,
            plus_di is not None and minus_di is not None and plus_di > minus_di,
            adx is not None and adx_d1 is not None and (adx > adx_d1 or adx >= 30),
        )
    )

    return {
        "snapshotDate": date_value,
        "capturedAt": captured_value,
        "ticker": ticker,
        "name": row.get("name") or (stock or {}).get("name") or "-",
        "market": row.get("market") or (stock or {}).get("market") or "-",
        "opinion": row.get("opinion") or "-",
        "entrySignalCodes": normalize_entry_codes(row.get("entrySignalCodes")),
        "entryStrategy": row.get("entryStrategy") or row.get("진입 전략") or "-",
        "currentPrice": current_price,
        "ma200": ma200,
        "pctB": pct_b,
        "pctBLow": pct_b_low,
        "rsi": rsi,
        "macdHist": macd_hist,
        "macdHistD1": macd_hist_d1,
        "macdHistD2": macd_hist_d2,
        "plusDI": plus_di,
        "minusDI": minus_di,
        "adx": adx,
        "adxD1": adx_d1,
        "bbWidth": parse_number(row.get("볼린저밴드 폭 (D)")),
        "bbWidthD1": parse_number(row.get("볼린저밴드 폭 (D-1)")),
        "bbWidthAvg60": parse_number(row.get("지난 60일 볼린저밴드 폭 평균")),
        "volumeRatio": volume_ratio,
        "volumeRatio20": volume_ratio20,
        "qqqPremium": qqq_premium,
        "qqqRegime": qqq_state.get("regimeLabel") or "-",
        "qqqBuyBlockMax": qqq_buy_block_max,
        "qqqPeakTriggered": bool(qqq_state.get("peakTriggered")),
        "hBreakoutCandidate": h_candidate,
        "conditionSummary": row.get("conditionSummary") or "",
        "technicalIndicators": row.copy(),
        "valuationIndicators": valuation.copy() if isinstance(valuation, dict) else {},
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def record_daily_signal_snapshots(now: datetime | None = None) -> int:
    technical = load_json(TECHNICAL_CACHE_PATH, {})
    technical_rows = technical.get("rows", {}) if isinstance(technical, dict) else {}
    if not isinstance(technical_rows, dict) or not technical_rows:
        print("[signal_snapshots] technical cache has no rows; skipped.")
        return 0

    valuation = load_json(VALUATION_CACHE_PATH, {})
    valuation_rows = valuation.get("rows", {}) if isinstance(valuation, dict) else {}
    if not isinstance(valuation_rows, dict):
        valuation_rows = {}
    stocks = stocks_by_ticker(load_json(STOCKS_CACHE_PATH, {}))
    qqq_state = technical.get("qqqMarketState", {}) if isinstance(technical.get("qqqMarketState"), dict) else {}
    date_value = snapshot_date(now)
    captured_value = captured_at(now)
    new_rows = [
        build_snapshot_row(
            ticker,
            row,
            stock=stocks.get(ticker),
            valuation=valuation_rows.get(ticker),
            qqq_state=qqq_state,
            date_value=date_value,
            captured_value=captured_value,
        )
        for ticker, row in sorted(technical_rows.items())
        if isinstance(row, dict)
    ]

    path = history_path(date_value)
    existing_rows = [
        row
        for row in read_jsonl(path)
        if str(row.get("snapshotDate") or "") != date_value
    ]
    write_jsonl(path, [*existing_rows, *new_rows])
    print(f"[signal_snapshots] wrote {len(new_rows)} rows to {display_path(path)}")
    return len(new_rows)


def main() -> None:
    count = record_daily_signal_snapshots()
    if count == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
