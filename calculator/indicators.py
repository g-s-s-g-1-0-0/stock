"""Technical indicator helpers shared by batch jobs and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

BB_WINDOW = 20
BB_STD = 2
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_WINDOW = 14
CCI_WINDOW = 20
ADX_WINDOW = 14
LR_PERIOD = 120


def rsi(close: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def cci(df: pd.DataFrame, window: int = CCI_WINDOW) -> pd.Series:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    ma = typical.rolling(window).mean()
    mad = typical.rolling(window).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (typical - ma) / (0.015 * mad.replace(0, np.nan))


def add_adx(df: pd.DataFrame) -> pd.DataFrame:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / ADX_WINDOW, adjust=False, min_periods=ADX_WINDOW).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / ADX_WINDOW, adjust=False, min_periods=ADX_WINDOW
    ).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / ADX_WINDOW, adjust=False, min_periods=ADX_WINDOW
    ).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)

    df["PlusDI"] = plus_di
    df["MinusDI"] = minus_di
    df["ADX"] = dx.ewm(alpha=1 / ADX_WINDOW, adjust=False, min_periods=ADX_WINDOW).mean()
    df["ADX_D1"] = df["ADX"].shift(1)
    return df


def add_lr(df: pd.DataFrame) -> pd.DataFrame:
    lows = df["Low"].to_numpy(dtype=float)
    values = np.full(len(df), np.nan)
    slopes = np.full(len(df), np.nan)
    x = np.arange(LR_PERIOD, dtype=float)
    x_mean = (LR_PERIOD - 1) / 2
    den = np.sum((x - x_mean) ** 2)

    for i in range(LR_PERIOD - 1, len(df)):
        y = lows[i - LR_PERIOD + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = np.mean(y)
        slope = np.sum((x - x_mean) * (y - y_mean)) / den
        intercept = y_mean - slope * x_mean
        values[i] = intercept + slope * (LR_PERIOD - 1)
        slopes[i] = slope

    df["LR_Trendline"] = values
    df["LR_Slope"] = slopes
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    lo = df["Low"]
    df["MA200"] = c.rolling(200).mean()

    ma20 = c.rolling(BB_WINDOW).mean()
    std20 = c.rolling(BB_WINDOW).std()
    upper = ma20 + BB_STD * std20
    lower = ma20 - BB_STD * std20
    width = upper - lower
    denom = width.replace(0, np.nan)
    df["BB_Width"] = width
    df["BB_Width_D1"] = width.shift(1)
    df["BB_Width60"] = width.rolling(60).mean()
    df["PctB"] = (c - lower) / denom * 100
    df["PctB_Low"] = (lo - lower) / denom * 100

    ema_fast = c.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = c.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["MACD"] = macd_line
    df["MACD_Signal"] = signal_line
    df["MACD_Hist"] = macd_line - signal_line
    df["MACD_Hist_D1"] = df["MACD_Hist"].shift(1)
    df["MACD_Hist_D2"] = df["MACD_Hist"].shift(2)
    df["RSI"] = rsi(c)
    df["RSI_D1"] = df["RSI"].shift(1)
    df["CCI"] = cci(df)
    df["CCI_D1"] = df["CCI"].shift(1)
    df["VolRatio"] = df["Volume"] / df["Volume"].rolling(5).mean().replace(0, np.nan)
    df = add_adx(df)
    df = add_lr(df)
    return df
