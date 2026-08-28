"""Download daily bars for every ticker that was ever an S&P 500 member.

Names that are still listed come back from Yahoo; names that were acquired or
went bankrupt return nothing. Both outcomes are recorded so the size of the
hole is a measured number rather than an assumption.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import pandas as pd
import yfinance as yf

from quant import sp500

STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sp500_cache"
)
MANIFEST = os.path.join(STORE, "_manifest.json")
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _load_manifest() -> dict[str, dict]:
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _save_manifest(manifest: dict[str, dict]) -> None:
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)


def _store_one(ticker: str, frame: pd.DataFrame) -> dict:
    frame = frame.dropna(subset=["Close"])
    if len(frame) == 0:
        return {"status": "empty", "bars": 0}
    frame = frame[OHLCV].copy()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)
    frame.index = frame.index.normalize()
    frame.to_pickle(os.path.join(STORE, f"{ticker}.pkl"))
    return {
        "status": "ok",
        "bars": int(len(frame)),
        "start": str(frame.index[0].date()),
        "end": str(frame.index[-1].date()),
    }


def collect(batch_size: int = 40, pause: float = 1.0) -> dict[str, dict]:
    os.makedirs(STORE, exist_ok=True)
    tickers = sorted(sp500.membership().columns)
    manifest = _load_manifest()
    pending = [t for t in tickers if t not in manifest]
    print(f"{len(tickers)} ever-members, {len(pending)} still to fetch")

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        try:
            raw = yf.download(
                batch, period="max", interval="1d", auto_adjust=True,
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as error:  # noqa: BLE001 - one bad batch must not stop the run
            print(f"  batch {start // batch_size}: {type(error).__name__}, skipping")
            continue

        for ticker in batch:
            try:
                frame = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
                manifest[ticker] = _store_one(ticker, frame)
            except Exception:  # noqa: BLE001 - absent ticker means delisted
                manifest[ticker] = {"status": "empty", "bars": 0}

        ok = sum(1 for t in batch if manifest[t]["status"] == "ok")
        done = start + len(batch)
        print(f"  {done}/{len(pending)}  batch ok={ok}/{len(batch)}")
        _save_manifest(manifest)
        time.sleep(pause)

    _save_manifest(manifest)
    return manifest


def coverage_report(manifest: dict[str, dict] | None = None) -> None:
    manifest = manifest or _load_manifest()
    frame = pd.DataFrame(manifest).T
    have = frame[frame["status"] == "ok"]
    missing = sorted(frame[frame["status"] != "ok"].index)

    print(f"\never-members: {len(frame)}")
    print(f"price data available: {len(have)} ({len(have) / len(frame) * 100:.1f}%)")
    print(f"missing (delisted / acquired): {len(missing)}")

    current, _ = sp500.current_members()
    gone = set(frame.index) - current
    gone_missing = sorted(set(missing) & gone)
    print(f"of the {len(gone)} that left the index, {len(gone_missing)} have no data")

    starts = pd.to_datetime(have["start"])
    print("\n--- tickers with data reaching back to ---")
    for year in (2000, 2005, 2007, 2010, 2015):
        print(f"  {year} or earlier: {(starts <= f'{year}-01-01').sum()}")

    print(f"\nmissing sample: {', '.join(missing[:40])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    manifest = _load_manifest() if args.report_only else collect(args.batch_size, args.pause)
    coverage_report(manifest)


if __name__ == "__main__":
    main()
