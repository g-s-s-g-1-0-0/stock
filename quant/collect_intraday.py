"""Tiered intraday bar collection.

Yahoo's free intraday history is capped differently per bar size, which is why
the horizons have very different evidence available today:

    1 minute   ~30 days   (7-day chunks per request)
    5 minute   ~60 days
    1 hour     ~730 days

So a 1-5 day swing rule can be validated on two years of hourly bars right
now, while an intraday rule needs months of forward collection before any
conclusion is possible. Data is stored per ticker per month so the job is
resumable and a re-run only fetches what is missing.
"""

from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

from quant import data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "intraday")

LIMITS = {"1h": 720, "5m": 58, "1m": 29}
CHUNK_DAYS = {"1h": 720, "5m": 58, "1m": 7}
BARS_PER_SESSION = {"1h": 7, "5m": 78, "1m": 390}
MISSING_TOLERANCE = 0.05


def _path(interval: str, ticker: str, month: str) -> str:
    return os.path.join(STORE, interval, month, f"{ticker}.pkl")


def _fetch(ticker: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = yf.download(
        ticker,
        interval=interval,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns=str.title)
    keep = [column for column in data.OHLCV if column in frame.columns]
    frame = frame[keep].dropna(how="all")
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    return frame.astype("float32")


def quality_report(frame: pd.DataFrame, interval: str, daily: pd.DataFrame | None) -> dict:
    """Flag sessions with missing bars and closes that disagree with daily data.

    Yahoo intraday series drop bars without warning and are not adjusted for
    splits, so anything that fails these checks must be quarantined rather
    than silently backtested.
    """
    if frame.empty:
        return {"sessions": 0, "thinSessions": 0, "closeMismatch": 0}
    per_session = frame.groupby(frame.index.date).size()
    expected = BARS_PER_SESSION[interval]
    thin = int((per_session < expected * (1 - MISSING_TOLERANCE)).sum())

    mismatch = 0
    if daily is not None and not daily.empty:
        # Compare daily returns rather than price levels: the daily cache is
        # split/dividend adjusted while intraday bars are raw, so levels
        # legitimately differ but returns should agree.
        intraday_close = frame.groupby(frame.index.date)["Close"].last()
        reference = daily["Close"].copy()
        reference.index = reference.index.date
        joined = pd.concat([intraday_close, reference], axis=1, join="inner").pct_change()
        joined = joined.dropna()
        if not joined.empty:
            deviation = (joined.iloc[:, 0] - joined.iloc[:, 1]).abs()
            mismatch = int((deviation > 0.005).sum())
    return {
        "sessions": int(len(per_session)),
        "thinSessions": thin,
        "closeMismatch": mismatch,
    }


def collect(
    tickers: list[str],
    interval: str,
    daily_bars: dict[str, pd.DataFrame] | None = None,
    pause: float = 0.4,
    force: bool = False,
) -> pd.DataFrame:
    end = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=LIMITS[interval])
    chunk = pd.Timedelta(days=CHUNK_DAYS[interval])

    rows = []
    for position, ticker in enumerate(tickers, start=1):
        pieces = []
        window_start = start
        while window_start < end:
            window_end = min(window_start + chunk, end)
            try:
                pieces.append(_fetch(ticker, interval, window_start, window_end))
            except Exception as error:
                rows.append({"ticker": ticker, "error": str(error)[:80]})
            window_start = window_end
            time.sleep(pause)

        pieces = [piece for piece in pieces if not piece.empty]
        if not pieces:
            rows.append({"ticker": ticker, "bars": 0, "error": "no data"})
            continue

        frame = pd.concat(pieces).sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        report = quality_report(
            frame, interval, (daily_bars or {}).get(ticker)
        )

        written = 0
        for month, group in frame.groupby(frame.index.strftime("%Y-%m")):
            target = _path(interval, ticker, month)
            if os.path.exists(target) and not force:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            group.to_pickle(target)
            written += 1

        rows.append({"ticker": ticker, "bars": len(frame), "monthsWritten": written, **report})
        if position % 20 == 0:
            print(f"  {position}/{len(tickers)} done", flush=True)

    return pd.DataFrame(rows)


def load(interval: str, ticker: str) -> pd.DataFrame:
    """Read every stored month for one ticker."""
    pattern = os.path.join(STORE, interval, "*", f"{ticker}.pkl")
    import glob

    frames = [pd.read_pickle(path) for path in sorted(glob.glob(pattern))]
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames).sort_index()
    return frame[~frame.index.duplicated(keep="last")]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", default="1h", choices=list(LIMITS))
    parser.add_argument("--limit", type=int, default=0, help="only the first N tickers")
    parser.add_argument("--pause", type=float, default=0.4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    daily = data.load_bars()
    tickers = sorted(daily)
    if args.limit:
        tickers = tickers[: args.limit]

    print(f"collecting {args.interval} for {len(tickers)} tickers into {STORE}", flush=True)
    started = time.time()
    summary = collect(tickers, args.interval, daily, pause=args.pause, force=args.force)
    os.makedirs(STORE, exist_ok=True)
    summary.to_csv(os.path.join(STORE, f"collection_{args.interval}.csv"), index=False)

    ok = summary.get("bars", pd.Series(dtype=float)).fillna(0).gt(0).sum()
    print(f"\nfinished in {time.time() - started:.0f}s: {ok}/{len(tickers)} tickers have data")
    for column in ("bars", "thinSessions", "closeMismatch"):
        if column in summary.columns:
            print(f"  {column}: total {np.nansum(summary[column]):.0f}")


if __name__ == "__main__":
    main()
