"""Per-ticker indicator panels and market-regime features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import data


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(frame: pd.DataFrame, window: int = 20) -> pd.Series:
    high, low, close = frame["High"], frame["Low"], frame["Close"]
    prev = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def _adx(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = frame["High"], frame["Low"], frame["Close"]
    up = high.diff()
    down = -low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    prev = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    smoothed = true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_di = 100 * plus.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / smoothed.replace(0, np.nan)
    minus_di = 100 * minus.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / smoothed.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator the strategies need, using only past bars."""
    out = frame.copy()
    close, high, low = out["Close"], out["High"], out["Low"]

    out["atr20"] = _atr(out, 20)
    out["atrPct"] = out["atr20"] / close

    for window in (5, 20, 60, 200):
        out[f"ma{window}"] = close.rolling(window).mean()
    out["ma200Slope"] = out["ma200"].diff(20)

    out["rsi14"] = _rsi(close, 14)
    out["rsi2"] = _rsi(close, 2)
    out["adx14"] = _adx(out, 14)

    ma20 = out["ma20"]
    std20 = close.rolling(20).std()
    width = (4 * std20) / ma20.replace(0, np.nan)
    out["bbWidth"] = width
    out["bbWidthPct"] = width.rolling(252).rank(pct=True)

    out["high52"] = high.rolling(252).max()
    out["distHigh52"] = close / out["high52"] - 1.0

    out["priorLow20"] = low.rolling(20).min().shift(1)
    out["isLow20"] = low.le(out["priorLow20"])
    out["priorHigh20"] = high.rolling(20).max().shift(1)
    out["breakout20"] = close.gt(out["priorHigh20"])

    span = (high - low).replace(0, np.nan)
    out["lowerTail"] = (close - low) / span
    out["volRatio20"] = out["Volume"] / out["Volume"].rolling(20).mean().replace(0, np.nan)
    out["dollarVolume20"] = (close * out["Volume"]).rolling(20).mean()

    out["mom126"] = close / close.shift(126) - 1.0
    out["dd60"] = close / close.rolling(60).max() - 1.0
    out["gap"] = out["Open"] / close.shift(1) - 1.0
    out["down3"] = (close.diff() < 0).rolling(3).sum().eq(3)

    out["eligible"] = data.liquidity_gate(out)
    return out


def build_panels(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {ticker: add_features(frame) for ticker, frame in bars.items()}


def market_features() -> pd.DataFrame:
    """QQQ regime and VIX level on the shared trading calendar."""
    qqq = data.load_market("QQQ")
    if qqq is None:
        raise RuntimeError("QQQ daily bars are missing from .bt_cache")
    close = qqq["Close"]
    ma200 = close.rolling(200).mean()
    out = pd.DataFrame(index=qqq.index)
    out["qqqClose"] = close
    out["qqqMa200"] = ma200
    out["qqqPremium"] = close / ma200 - 1.0
    out["qqqMa200Rising"] = ma200.diff(20) > 0
    out["qqqRsi14"] = _rsi(close, 14)

    vix = data.load_market("_VIX")
    out["vix"] = (
        vix["Close"].reindex(out.index).ffill(limit=5) if vix is not None else np.nan
    )
    return out


def build_breadth(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Cross-sectional breadth computed on exact dates, never forward-filled."""
    below, oversold = [], []
    for frame in panels.values():
        below.append((frame["Close"] < frame["ma200"]).where(frame["ma200"].notna()))
        oversold.append((frame["rsi14"] < 30).where(frame["rsi14"].notna()))
    out = pd.DataFrame(
        {
            "breadthBelow200": pd.concat(below, axis=1).mean(axis=1, skipna=True),
            "breadthRsi30": pd.concat(oversold, axis=1).mean(axis=1, skipna=True),
        }
    )
    return out.sort_index()
