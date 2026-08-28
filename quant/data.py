"""Daily bar loading and point-in-time universe construction."""

from __future__ import annotations

import glob
import os
from functools import lru_cache

import numpy as np
import pandas as pd

from quant import config

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".bt_cache")
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _read(path: str) -> pd.DataFrame | None:
    try:
        frame = pd.read_pickle(path)
    except Exception:
        return None
    if not isinstance(frame, pd.DataFrame) or not set(OHLCV).issubset(frame.columns):
        return None
    if not isinstance(frame.index, pd.DatetimeIndex):
        return None
    frame = frame[OHLCV].astype(float).sort_index()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)
    frame.index = frame.index.normalize()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame[frame["Close"] > 0]
    return frame if len(frame) >= config.MIN_BARS else None


EXCLUDED = {
    # Leveraged and volatility ETFs: their path statistics are not comparable
    # to single stocks and they dominate any excursion-based metric.
    "SOXL", "SOXS", "TQQQ", "SQQQ", "UVXY", "TNA", "TZA", "SPXL", "SPXS",
    "LABU", "LABD", "NUGT", "DUST", "FAS", "FAZ", "UPRO", "SDOW", "UDOW",
    # Broad-market ETFs. They are legitimate market context (see load_market)
    # but inside the stock universe they both flatten the cross-sectional
    # benchmark and can be picked as trades.
    "QQQ", "SPY", "DIA", "IWM", "VTI", "VOO",
    # Not a resolvable US listing.
    "HOOG",
}


def _is_us(name: str) -> bool:
    if ".KS" in name or ".KQ" in name or "bnc" in name:
        return False
    if name.startswith("intra_") or name in EXCLUDED:
        return False
    return True


def load_bars(prefix: str = "s4_") -> dict[str, pd.DataFrame]:
    """Load US daily bars from the existing backtest cache.

    The ``s4_`` prefix holds the deepest history (many series start in 1999),
    which is what the era-split validation needs.
    """
    bars: dict[str, pd.DataFrame] = {}
    for path in sorted(glob.glob(os.path.join(CACHE_DIR, f"{prefix}*.pkl"))):
        name = os.path.basename(path)[len(prefix) : -4]
        if not _is_us(name) or name.startswith("_"):
            continue
        frame = _read(path)
        if frame is not None:
            bars[name] = frame
    return bars


@lru_cache(maxsize=8)
def load_market(symbol: str) -> pd.DataFrame | None:
    """Load an index series such as QQQ or _VIX."""
    for prefix in ("s4_", "v2_", "dr_", ""):
        frame = _read(os.path.join(CACHE_DIR, f"{prefix}{symbol}.pkl"))
        if frame is not None:
            return frame
    return None


def liquidity_gate(frame: pd.DataFrame) -> pd.Series:
    """Monthly liquidity gate evaluated on prior-month data only.

    The gate decision for month M uses data available at the end of month
    M-1, so a name that only became liquid because of the move we are trying
    to trade cannot enter the universe on that same move.
    """
    dollar_volume = (frame["Close"] * frame["Volume"]).rolling(20).mean()
    eligible = (
        dollar_volume.ge(config.MIN_DOLLAR_VOLUME) & frame["Close"].ge(config.MIN_PRICE)
    ).astype(float)
    month_end = eligible.resample("ME").last()
    applied = month_end.shift(1).reindex(frame.index, method="ffill")
    return applied.fillna(0.0).gt(0.5)


def universe_mean_return(bars: dict[str, pd.DataFrame]) -> pd.Series:
    """Equal-weight cross-sectional daily return of the whole universe.

    Used as the same-date benchmark so that absolute and excess returns are
    reported side by side instead of being confused for each other.
    """
    frames = []
    for frame in bars.values():
        frames.append(frame["Close"].pct_change().rename("r"))
    stacked = pd.concat(frames, axis=1)
    return stacked.mean(axis=1, skipna=True).rename("universeRet")


class UniverseGrowth:
    """Fast as-of lookup of the universe's cumulative growth factor."""

    def __init__(self, daily_returns: pd.Series) -> None:
        series = (1.0 + daily_returns.fillna(0.0)).cumprod()
        series = series[~series.index.duplicated(keep="last")].sort_index()
        self._dates = series.index.to_numpy()
        self._values = series.to_numpy(float)

    def factor(self, timestamp) -> float:
        position = int(np.searchsorted(self._dates, np.datetime64(timestamp), side="right")) - 1
        return float(self._values[position]) if position >= 0 else np.nan

    def between(self, start, end) -> float:
        first, last = self.factor(start), self.factor(end)
        if not np.isfinite(first) or first == 0 or not np.isfinite(last):
            return np.nan
        return last / first - 1.0
