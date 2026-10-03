"""Record private research observations for the US premarket gap-and-go setup.

This script never touches web/public, notifications, recommendations, or trade
state.  It only updates ``data/history/gap-go``.

Schema 2 freezes the previous close to the last daily bar before the New York
session date, stores the regular-session low and the path after 10:00, and
writes one append-only daily bar file per session.  Later sessions are the
forward path: join ``sessions/gap-go-session-*.jsonl`` with a date after the
signal.  The 10:00 price remains the strategy entry; the next session open is
that following file's open.

Yahoo's 1-minute bars leave premarket volume blank.  Those rows store null
instead of a zero.  A later stage keeps a non-null volume captured earlier
the same day.  Each row also stores the stock's 200-day average, the prior
day's high, and the 20-day volume ratio from the daily bars.

A separate ``gap-go-paper-trades.jsonl`` file records a hypothetical trade
when the 5% gap and 10:00 breakout both occur.  It buys the 10:00 price, stops
at the low from 9:30 through 10:00, sells half at twice that risk, and closes
the rest by 11:00.  This file is research data only and is not a trading log.

A delayed job still records the New York session of the slot it was scheduled
for.  Minute bars cover five days, and a later run fills any paper trade whose
11:00 bar was not available yet.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STOCKS_PATH = ROOT / "data" / "cache" / "stocks.json"
TECHNICAL_PATH = ROOT / "data" / "cache" / "technical.json"
HISTORY_DIR = ROOT / "data" / "history" / "gap-go"
NEW_YORK = ZoneInfo("America/New_York")
MAX_TICKERS = 200
SCHEMA_VERSION = 2
OHLCV_FIELDS = ("Open", "High", "Low", "Close", "Volume")
SCHEDULE_STAGE = {
    "20,25,30 13,14 * * 1-5": "premarket",
    "0,5,10 14,15 * * 1-5": "ten_am",
    "5,10,15 20,21 * * 1-5": "close",
}
STAGE_CLOCK = {
    "premarket": (9, 20),
    "ten_am": (10, 0),
    "close": (16, 5),
}
STAGE_RANK = {"ten_am": 2, "close": 1, "premarket": 0}
MINUTE_PERIOD = "5d"
SLOT_GRACE = timedelta(minutes=30)


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


def observation_stage(now: datetime, scheduled_expression: str = "") -> str | None:
    """Use the intended slot when GitHub starts a scheduled job late."""
    return SCHEDULE_STAGE.get(scheduled_expression.strip()) or stage_at(now)


def session_moment(now: datetime, scheduled_expression: str = "") -> datetime | None:
    """New York time of the slot this run belongs to, even if the job starts late."""
    stage = observation_stage(now, scheduled_expression)
    if stage is None:
        return None
    local = now.astimezone(NEW_YORK)
    hour, minute = STAGE_CLOCK[stage]
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate - local > SLOT_GRACE:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def due_stages(now: datetime) -> list[str]:
    """Slots whose New York clock has passed. A manual run uses these to catch up."""
    local = now.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return []
    due = []
    for stage in ("premarket", "ten_am", "close"):
        hour, minute = STAGE_CLOCK[stage]
        slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local >= slot:
            due.append(stage)
    return due


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


def index_dates(index: pd.Index) -> list[date]:
    """Calendar dates in New York for tz-aware stamps; naive stamps keep their date."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert(NEW_YORK)
    return [ts.date() for ts in idx]


def _ohlcv_frame(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    columns = {field: _series(frame, field, ticker) for field in OHLCV_FIELDS}
    table = pd.DataFrame(columns).dropna(subset=["Close"])
    if table.empty:
        return table
    table = table.copy()
    table["_session"] = index_dates(table.index)
    return table


def _minute_index(index: pd.Index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert(NEW_YORK)


def _volume_sum(volume: pd.Series, mask: pd.Series) -> float | None:
    if not bool(mask.any()):
        return None
    values = volume.loc[mask]
    if values.dropna().empty or bool((values.fillna(0) == 0).all()):
        return None
    return float(values.fillna(0).sum())


def _setup_filters(daily_frame: pd.DataFrame, session: date, day_close: float | None, day_volume: float | None) -> dict[str, Any]:
    """Stock trend, prior high, and 20-day volume ratio used by the gap-and-go check."""
    empty = {
        "previousHigh": None,
        "ma200": None,
        "aboveMa200": None,
        "closeAbovePriorHigh": None,
        "volume20Avg": None,
        "volRatio20": None,
        "elevatedVolume": None,
    }
    if daily_frame.empty:
        return empty
    prior = daily_frame[daily_frame["_session"] < session]
    through = daily_frame[daily_frame["_session"] <= session]
    previous_high = _num(prior["High"].iloc[-1]) if not prior.empty else None
    ma_source = through if not through.empty and through["_session"].iloc[-1] == session else prior
    ma200 = float(ma_source["Close"].tail(200).mean()) if len(ma_source) >= 200 else None
    if not through.empty and through["_session"].iloc[-1] == session and len(through) >= 20:
        volume_window = through["Volume"].tail(20)
        today_volume = _num(through["Volume"].iloc[-1])
    else:
        volume_window = prior["Volume"].tail(20)
        today_volume = day_volume
    volume_avg = float(volume_window.mean()) if len(volume_window) >= 20 and bool(volume_window.notna().all()) else None
    vol_ratio = today_volume / volume_avg if today_volume is not None and volume_avg else None
    return {
        "previousHigh": previous_high,
        "ma200": ma200,
        "aboveMa200": day_close > ma200 if day_close is not None and ma200 else None,
        "closeAbovePriorHigh": day_close > previous_high if day_close is not None and previous_high else None,
        "volume20Avg": volume_avg,
        "volRatio20": vol_ratio,
        "elevatedVolume": vol_ratio >= 1.5 if vol_ratio is not None else None,
    }


def _snapshot(minute: pd.DataFrame, daily: pd.DataFrame, ticker: str, today: datetime) -> dict[str, Any]:
    session = today.date()
    daily_frame = _ohlcv_frame(daily, ticker)
    previous_close, previous_close_date = (None, None)
    if not daily_frame.empty:
        prior = daily_frame[daily_frame["_session"] < session]
        if not prior.empty:
            previous_close = _num(prior["Close"].iloc[-1])
            previous_close_date = prior["_session"].iloc[-1].isoformat()

    intraday = _ohlcv_frame(minute, ticker)
    if intraday.empty:
        return {
            "ticker": ticker,
            "dataAvailable": False,
            "schemaVersion": SCHEMA_VERSION,
            "previousClose": previous_close,
            "previousCloseDate": previous_close_date,
            **_setup_filters(daily_frame, session, None, None),
        }

    index = _minute_index(intraday.index)
    session_start = pd.Timestamp(session, tz=NEW_YORK)
    pre = (index >= session_start + pd.Timedelta(hours=4)) & (index < session_start + pd.Timedelta(hours=9, minutes=30))
    regular = (index >= session_start + pd.Timedelta(hours=9, minutes=30)) & (index <= session_start + pd.Timedelta(hours=16))
    through_ten = regular & (index <= session_start + pd.Timedelta(hours=10))
    after_ten = regular & (index >= session_start + pd.Timedelta(hours=10))
    premarket_volume = _volume_sum(intraday["Volume"], pre)
    pre_last = _num(intraday.loc[pre, "Close"].iloc[-1]) if pre.any() else None
    pre_high = _num(intraday.loc[pre, "High"].max()) if pre.any() else None
    regular_open = _num(intraday.loc[regular, "Open"].dropna().iloc[0]) if regular.any() and intraday.loc[regular, "Open"].notna().any() else None
    ten_price = _num(intraday.loc[through_ten, "Close"].iloc[-1]) if through_ten.any() else None
    gap_pct = (pre_last / previous_close - 1) if pre_last and previous_close else None
    day_close = _num(intraday.loc[regular, "Close"].iloc[-1]) if regular.any() else None
    day_volume = _volume_sum(intraday["Volume"], regular)
    return {
        "ticker": ticker,
        "dataAvailable": True,
        "schemaVersion": SCHEMA_VERSION,
        "priceSource": "yahoo",
        "adjustment": "unadjusted",
        "previousClose": previous_close,
        "previousCloseDate": previous_close_date,
        "premarketLast": pre_last,
        "premarketHigh": pre_high,
        "premarketLow": _num(intraday.loc[pre, "Low"].min()) if pre.any() else None,
        "premarketVolume": premarket_volume,
        "premarketVolumeKnown": premarket_volume is not None,
        "premarketVolumeSource": "yahoo-1m" if premarket_volume is not None else "yahoo-1m-blank",
        "regularOpen": regular_open,
        "tenAmPrice": ten_price,
        "tenAmHigh": _num(intraday.loc[through_ten, "High"].max()) if through_ten.any() else None,
        "tenAmLow": _num(intraday.loc[through_ten, "Low"].min()) if through_ten.any() else None,
        "volumeThroughTen": _volume_sum(intraday["Volume"], through_ten),
        "highAfterTen": _num(intraday.loc[after_ten, "High"].max()) if after_ten.any() else None,
        "lowAfterTen": _num(intraday.loc[after_ten, "Low"].min()) if after_ten.any() else None,
        "dayOpen": regular_open,
        "dayHigh": _num(intraday.loc[regular, "High"].max()) if regular.any() else None,
        "dayLow": _num(intraday.loc[regular, "Low"].min()) if regular.any() else None,
        "dayClose": day_close,
        "dayVolume": day_volume,
        **_setup_filters(daily_frame, session, day_close, day_volume),
        "gapPct": gap_pct,
        "gapScreen": bool(gap_pct is not None and gap_pct >= 0.05 and pre_high is not None),
        "tenAmBreakout": bool(ten_price is not None and pre_high is not None and ten_price > pre_high),
    }


def read_breadth(path: Path = TECHNICAL_PATH) -> dict[str, Any]:
    """NYSE 20-day breadth already stored by the web refresh, with its as-of time."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    breadth = (payload.get("marketSignals") or {}).get("breadth") or {}
    return {
        "breadthPct": _num(breadth.get("value")),
        "breadthCount": breadth.get("count"),
        "breadthStatus": breadth.get("status"),
        "breadthAsOf": (payload.get("meta") or {}).get("updatedAt"),
    }


def market_context(daily: pd.DataFrame, session: date, breadth: dict[str, Any] | None = None) -> dict[str, Any]:
    """QQQ regime, RSI, MACD, and VIX from daily bars on or before the session."""
    from calculator.indicators import add_indicators, rsi
    from calculator.market_regime import build_qqq_market_state, qqq_recent_ma200_min_distance

    context: dict[str, Any] = {
        "marketBarDate": None,
        "qqqClose": None,
        "qqqMa200": None,
        "qqqMa200Dist": None,
        "qqqRegime": None,
        "qqqRsi": None,
        "qqqMacdHist": None,
        "qqqRecent60MinDist": None,
        "vix": None,
        **(breadth or read_breadth()),
    }
    qqq = _ohlcv_frame(daily, "QQQ")
    if qqq.empty:
        return context
    qqq = qqq[qqq["_session"] <= session]
    if qqq.empty:
        return context
    indicators = add_indicators(qqq.loc[:, list(OHLCV_FIELDS)])
    last = indicators.iloc[-1]
    closes = [{"close": float(value)} for value in qqq["Close"] if pd.notna(value)]
    recent_min = qqq_recent_ma200_min_distance(closes)
    weekly = qqq["Close"].copy()
    weekly.index = pd.DatetimeIndex(qqq["_session"])
    weekly_rsi = rsi(weekly.resample("W-FRI").last().dropna())
    state = build_qqq_market_state(
        {
            "close": _num(last["Close"]),
            "ma200": _num(last["MA200"]),
            "rsi": _num(last["RSI"]),
            "rsiD1": _num(last["RSI_D1"]),
            "macdHist": _num(last["MACD_Hist"]),
            "macdHistD1": _num(last["MACD_Hist_D1"]),
            "macdHistD2": _num(last["MACD_Hist_D2"]),
        },
        recent_min_dist=recent_min,
        weekly_rsi=_num(weekly_rsi.iloc[-1]) if not weekly_rsi.dropna().empty else None,
    )
    vix = _ohlcv_frame(daily, "^VIX")
    vix = vix[vix["_session"] <= session] if not vix.empty else vix
    context.update({
        "marketBarDate": qqq["_session"].iloc[-1].isoformat(),
        "qqqClose": state["currentPrice"],
        "qqqMa200": state["ma200"],
        "qqqMa200Dist": state["premiumPercent"],
        "qqqRegime": state["regimeLabel"],
        "qqqRsi": state["dailyRsi"],
        "qqqMacdHist": state["macdHist"],
        "qqqRecent60MinDist": state["recent60MinPremiumPercent"],
        "vix": _num(vix["Close"].iloc[-1]) if not vix.empty else None,
    })
    return context


def _path(date_value: str) -> Path:
    return HISTORY_DIR / f"gap-go-observations-{date_value}.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def carry_forward_premarket_volume(existing: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {
        row["ticker"]: row["premarketVolume"]
        for row in existing
        if row.get("premarketVolume") is not None and row.get("ticker")
    }
    for row in rows:
        if row.get("premarketVolume") is None and row.get("ticker") in known:
            row["premarketVolume"] = known[row["ticker"]]
            row["premarketVolumeKnown"] = True
            row["premarketVolumeSource"] = "earlier-stage"
    return rows


def upsert(path: Path, rows: list[dict[str, Any]]) -> None:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(path):
        if row.get("ticker") and row.get("stage"):
            existing[(row["ticker"], row["stage"])] = row
    for row in rows:
        key = (row["ticker"], row["stage"])
        previous = existing.get(key)
        if previous and previous.get("dataAvailable") and not row.get("dataAvailable"):
            continue
        existing[key] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(existing.values(), key=lambda row: (row["stage"], row["ticker"]))
    _write_jsonl(path, ordered)


def _observation_tickers(path: Path) -> list[str]:
    rows = [row for row in _read_jsonl(path) if row.get("dataAvailable") is not False and row.get("ticker")]
    close_rows = [row for row in rows if row.get("stage") == "close"]
    chosen = close_rows or rows
    return sorted({str(row["ticker"]) for row in chosen})


def _session_bar(daily: pd.DataFrame, ticker: str, session: date) -> dict[str, Any] | None:
    frame = _ohlcv_frame(daily, ticker)
    if frame.empty:
        return None
    matched = frame[frame["_session"] == session]
    if matched.empty:
        return None
    last = matched.iloc[-1]
    return {
        "adjustment": "unadjusted",
        "close": _num(last["Close"]),
        "high": _num(last["High"]),
        "low": _num(last["Low"]),
        "observationDate": session.isoformat(),
        "open": _num(last["Open"]),
        "priceSource": "yahoo",
        "schemaVersion": SCHEMA_VERSION,
        "ticker": ticker,
        "volume": _num(last["Volume"]),
    }


def merge_session_rows(path: Path, rows: list[dict[str, Any]]) -> bool:
    """Add missing tickers. An existing ticker row stays as first written."""
    existing = {row["ticker"]: row for row in _read_jsonl(path) if row.get("ticker")}
    added = False
    for row in rows:
        if row["ticker"] not in existing:
            existing[row["ticker"]] = row
            added = True
    if not added:
        return False
    _write_jsonl(path, [existing[ticker] for ticker in sorted(existing)])
    return True


def ensure_session_files(daily: pd.DataFrame, history_dir: Path = HISTORY_DIR) -> list[Path]:
    """Write official daily bars for observation dates that now have a completed bar."""
    written: list[Path] = []
    for obs_path in sorted(history_dir.glob("gap-go-observations-*.jsonl")):
        session = date.fromisoformat(obs_path.stem.removeprefix("gap-go-observations-"))
        rows = [bar for ticker in _observation_tickers(obs_path) if (bar := _session_bar(daily, ticker, session))]
        if not rows:
            continue
        path = history_dir / "sessions" / f"gap-go-session-{session.isoformat()}.jsonl"
        if merge_session_rows(path, rows):
            written.append(path)
    return written


def paper_trade(minute: pd.DataFrame, row: dict[str, Any]) -> dict[str, Any] | None:
    """Hypothetical same-morning trade. Returns None until the 11:00 bar exists."""
    if not row.get("gapScreen") or not row.get("tenAmBreakout"):
        return None
    entry = _num(row.get("tenAmPrice"))
    stop = _num(row.get("tenAmLow"))
    session = date.fromisoformat(str(row.get("observationDate")))
    ticker = str(row.get("ticker") or "")
    if entry is None or not ticker:
        return None
    base = {
        "observationDate": session.isoformat(),
        "ticker": ticker,
        "entryPrice": entry,
        "stopPrice": stop,
        "schemaVersion": SCHEMA_VERSION,
        "rule": "10시 매수, 10시까지 저점 손절, 손절폭 2배에서 절반 익절, 11시 전량 정리",
    }
    if stop is None or stop >= entry:
        return {**base, "outcome": "무효", "success": False, "rMultiple": None, "returnPct": None}

    intraday = _ohlcv_frame(minute, ticker)
    if intraday.empty:
        return None
    index = _minute_index(intraday.index)
    start = pd.Timestamp(session, tz=NEW_YORK)
    window = (index > start + pd.Timedelta(hours=10)) & (index <= start + pd.Timedelta(hours=11))
    if not bool(window.any()) or index[window].max() < start + pd.Timedelta(hours=11):
        return None

    risk = entry - stop
    target = entry + 2 * risk
    path = intraday.loc[window]
    half_price = None
    rest_price = None
    outcome = "11시 정리"
    for _, bar in path.iterrows():
        low = _num(bar["Low"])
        high = _num(bar["High"])
        if low is None or high is None:
            continue
        if half_price is None:
            if low <= stop:
                outcome = "손절"
                rest_price = stop
                break
            if high >= target:
                half_price = target
                continue
        elif low <= entry:
            outcome = "익절 후 본전"
            rest_price = entry
            break
    else:
        rest_price = _num(path["Close"].iloc[-1])
        outcome = "익절 후 11시 정리" if half_price is not None else "11시 정리"

    if outcome == "손절":
        r_multiple = -1.0
    elif half_price is None:
        r_multiple = (rest_price - entry) / risk
    else:
        r_multiple = 1.0 + 0.5 * ((rest_price - entry) / risk)
    return {
        **base,
        "targetPrice": target,
        "riskPerShare": risk,
        "halfExitPrice": half_price,
        "restExitPrice": rest_price,
        "outcome": outcome,
        "rMultiple": r_multiple,
        "returnPct": r_multiple * risk / entry * 100,
        "success": r_multiple > 0,
    }


def _signal_row(rows: list[dict[str, Any]], session: str) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row.get("gapScreen") and row.get("tenAmBreakout") and row.get("tenAmPrice") is not None and row.get("ticker")
    ]
    if not candidates:
        return None
    chosen = max(candidates, key=lambda row: STAGE_RANK.get(str(row.get("stage")), -1))
    return {**chosen, "observationDate": chosen.get("observationDate") or session}


def resolve_pending_paper_trades(minute: pd.DataFrame, history_dir: Path = HISTORY_DIR) -> int:
    """Fill hypothetical trades once the 10:00–11:00 bars exist. The first result stays."""
    path = history_dir / "gap-go-paper-trades.jsonl"
    existing = {
        (row.get("observationDate"), row.get("ticker"))
        for row in _read_jsonl(path)
        if row.get("observationDate") and row.get("ticker")
    }
    pending: list[dict[str, Any]] = []
    for obs_path in sorted(history_dir.glob("gap-go-observations-*.jsonl")):
        session = obs_path.stem.removeprefix("gap-go-observations-")
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in _read_jsonl(obs_path):
            ticker = str(row.get("ticker") or "")
            if ticker:
                grouped.setdefault(ticker, []).append(row)
        for ticker, group in grouped.items():
            if (session, ticker) in existing:
                continue
            chosen = _signal_row(group, session)
            if chosen is None:
                continue
            trade = paper_trade(minute, chosen)
            if trade:
                pending.append(trade)
    if not pending or not merge_paper_trades(pending, path):
        return 0
    return len(pending)


def merge_paper_trades(rows: list[dict[str, Any]], path: Path | None = None) -> bool:
    """Keep the first resolved result for each date and ticker."""
    target = path or (HISTORY_DIR / "gap-go-paper-trades.jsonl")
    existing = {
        (row.get("observationDate"), row.get("ticker")): row
        for row in _read_jsonl(target)
        if row.get("observationDate") and row.get("ticker")
    }
    added = False
    for row in rows:
        key = (row.get("observationDate"), row.get("ticker"))
        if key not in existing:
            existing[key] = row
            added = True
    if not added:
        return False
    ordered = [existing[key] for key in sorted(existing)]
    _write_jsonl(target, ordered)
    return True


def _stages_for_run(current: datetime, scheduled: str) -> list[tuple[str, datetime]]:
    """One scheduled slot, or every slot whose clock has already passed."""
    if scheduled.strip():
        moment = session_moment(current, scheduled)
        stage = observation_stage(current, scheduled)
        if moment is None or stage is None:
            return []
        return [(stage, moment)]
    local = current.astimezone(NEW_YORK)
    return [
        (stage, local.replace(hour=hour, minute=minute, second=0, microsecond=0))
        for stage in due_stages(current)
        for hour, minute in (STAGE_CLOCK[stage],)
    ]


def record(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    scheduled = os.environ.get("GAP_GO_SCHEDULE", "")
    stages = _stages_for_run(current, scheduled)
    if not stages:
        print("[gap-go] outside observation window; skipped")
        return 0
    tickers = load_us_tickers()
    if not tickers:
        raise RuntimeError("no US tickers found in data/cache/stocks.json")

    import yfinance as yf

    research_enabled = os.environ.get("SWING_RESEARCH_ENABLED") == "true"
    research_tickers = []
    if research_enabled:
        from scripts.record_swing_research import tracked_tickers
        research_tickers = tracked_tickers()
    symbols = list(dict.fromkeys([*tickers, *research_tickers, "QQQ", "^VIX"]))
    minute = yf.download(tickers, period=MINUTE_PERIOD, interval="1m", prepost=True, auto_adjust=False, progress=False, threads=True)
    daily = yf.download(symbols, period="2y", interval="1d", auto_adjust=False, actions=True, progress=False, threads=True)
    local = current.astimezone(NEW_YORK)
    captured_at = current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    written = 0
    for stage, moment in stages:
        date_value = moment.date().isoformat()
        context = market_context(daily, moment.date())
        rows = [{
            **_snapshot(minute, daily, ticker, moment),
            **context,
            "stage": stage,
            "observationDate": date_value,
            "capturedAt": captured_at,
            "capturedAtNewYork": local.isoformat(timespec="seconds"),
        } for ticker in tickers]
        target = _path(date_value)
        carry_forward_premarket_volume(_read_jsonl(target), rows)
        upsert(target, rows)
        written += len(rows)
        print(f"[gap-go] wrote {len(rows)} {stage} observations to {target.relative_to(ROOT)}")
    filled = resolve_pending_paper_trades(minute)
    if filled:
        print(f"[gap-go] recorded {filled} paper trades")
    session_paths = ensure_session_files(daily)
    if session_paths:
        print(f"[gap-go] updated {len(session_paths)} session files")
    if research_enabled:
        from scripts.record_swing_research import collect
        stocks = json.loads(STOCKS_PATH.read_text()).get("rows", [])
        names = {row["ticker"]: row.get("name", "") for row in stocks if row.get("market") == "US"}
        event_path = ROOT / "data/cache/market-events.json"
        events = json.loads(event_path.read_text()) if event_path.exists() else None
        collect(daily, tickers, now=current, event_payload=events, names=names)
    return written


if __name__ == "__main__":
    record()
