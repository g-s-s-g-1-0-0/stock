"""Vectorized copies of the live service's technical indicators.

The web service computes one row at a time in `calculator/sheet_sources.py`,
which is fine for a daily refresh but far too slow to replay 27 years across
hundreds of tickers. These are pandas equivalents of the same formulas, so a
backtest of strategies A-H and 1/2/3 measures the rules that actually shipped.

Deliberate deviations, both numerically irrelevant after the 200-bar warmup the
strategies already require:
- EMAs seed from the first observation rather than a 14-bar SMA.
- MACD's signal line runs over the whole MACD series instead of starting at
  bar 26.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

RSI_PERIOD = 14
CCI_PERIOD = 14
BB_PERIOD = 20
BB_WIDTH_AVG_PERIOD = 60
ADX_PERIOD = 14
LR_PERIOD = 120


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=2.0 / (period + 1), adjust=False).mean()


def _rolling_mad(values: np.ndarray, period: int) -> np.ndarray:
    """Mean absolute deviation from the window mean, as CCI defines it."""
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    windows = sliding_window_view(values, period)
    out[period - 1 :] = np.abs(windows - windows.mean(axis=1, keepdims=True)).mean(axis=1)
    return out


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Cutler's RSI: simple averages of gains and losses, not Wilder smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    value = 100.0 - 100.0 / (1.0 + gain / loss.replace(0.0, np.nan))
    return value.where(loss > 0, 100.0).where(gain.notna())


def cci(frame: pd.DataFrame, period: int = CCI_PERIOD) -> pd.Series:
    typical = (frame["High"] + frame["Low"] + frame["Close"]) / 3.0
    sma = typical.rolling(period).mean()
    mad = pd.Series(_rolling_mad(typical.to_numpy(float), period), index=frame.index)
    return ((typical - sma) / (0.015 * mad.replace(0.0, np.nan))).fillna(0.0).where(sma.notna())


def _linear_regression_on_lows(low: pd.Series, period: int = LR_PERIOD) -> tuple[pd.Series, pd.Series]:
    """Slope and end-point value of a least-squares line fit to the lows."""
    values = low.to_numpy(float)
    slope = np.full(len(values), np.nan)
    trendline = np.full(len(values), np.nan)
    if len(values) >= period:
        x = np.arange(period, dtype=float)
        x_mean = (period - 1) / 2.0
        weights = (x - x_mean) / ((x - x_mean) ** 2).sum()
        windows = sliding_window_view(values, period)
        fitted = windows @ weights
        slope[period - 1 :] = fitted
        trendline[period - 1 :] = windows.mean(axis=1) + fitted * (period - 1 - x_mean)
    return (
        pd.Series(slope, index=low.index),
        pd.Series(trendline, index=low.index),
    )


def add_legacy(panel: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator strategies A-H and 1/2/3 read."""
    out = panel
    close, high, low = out["Close"], out["High"], out["Low"]
    volume = out["Volume"]

    out["legMa5"] = close.rolling(5).mean()
    out["legMa20"] = close.rolling(20).mean()
    out["legMa60"] = close.rolling(60).mean()
    out["legMa144"] = close.rolling(144).mean()
    out["legMa200"] = close.rolling(200).mean()
    out["legMa20D1"] = out["legMa20"].shift(1)
    out["legMa20Prev5"] = out["legMa20"].shift(5)
    out["legCloseD1"] = close.shift(1)

    out["legRsi"] = rsi(close)
    out["legCci"] = cci(out)

    macd = _ema(close, 12) - _ema(close, 26)
    hist = macd - _ema(macd, 9)
    out["legMacdHist"] = hist
    out["legMacdHistD1"] = hist.shift(1)
    out["legMacdHistD2"] = hist.shift(2)

    sma = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std(ddof=0)
    upper, lower = sma + 2 * std, sma - 2 * std
    span = (upper - lower).replace(0.0, np.nan)
    out["legPctB"] = (close - lower) / span * 100.0
    out["legPctBLow"] = (low - lower) / span * 100.0
    width = (upper - lower) / sma * 100.0
    out["legBbWidth"] = width
    out["legBbWidthD1"] = width.shift(1)
    out["legBbWidthAvg60"] = width.rolling(BB_WIDTH_AVG_PERIOD).mean()

    prior_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prior_close).abs(), (low - prior_close).abs()], axis=1
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_range = _ema(true_range, ADX_PERIOD).replace(0.0, np.nan)
    plus_di = _ema(plus_dm, ADX_PERIOD) / smoothed_range * 100.0
    minus_di = _ema(minus_dm, ADX_PERIOD) / smoothed_range * 100.0
    directional = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan) * 100.0
    out["legPlusDi"] = plus_di
    out["legMinusDi"] = minus_di
    out["legAdx"] = _ema(directional.fillna(0.0), ADX_PERIOD)
    out["legAdxD1"] = out["legAdx"].shift(1)

    out["legVolRatio"] = volume / volume.rolling(5).mean().replace(0.0, np.nan)
    out["legVolRatio20"] = volume / volume.rolling(20).mean().replace(0.0, np.nan)

    slope, trendline = _linear_regression_on_lows(low)
    out["legLrSlope"] = slope
    out["legLrTrendline"] = trendline

    out["legMa200Dist"] = (close / out["legMa200"] - 1.0) * 100.0
    return out
