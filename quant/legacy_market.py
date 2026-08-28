"""Daily replay of the live service's QQQ market state.

`calculator/market_regime.py` builds one state dict from one day's fetch. The
backtest needs the same dict for every day since 1999, so these are pandas
equivalents of the same formulas.

Two details are copied deliberately rather than cleaned up, because the shipped
rules compare exactly these numbers:
- the service rounds every indicator to two decimals before comparing them, so
  `macdHistSlowing` is decided on rounded values and so is this;
- weekly RSI is read from a partial current week, so the newest weekly close is
  today's close rather than the coming Friday's.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from calculator import market_regime as live
from quant import legacy_indicators as vec

MA_PERIOD = 200
RSI_PERIOD = 14


def _weekly_rsi(close: pd.Series) -> pd.Series:
    """RSI of weekly closes where the newest week is still open.

    The service reads `range=2y&interval=1wk`, whose last bar is the current
    partial week. So on any given day the series is the completed weeks'
    closes followed by that day's close.
    """
    weeks = close.index.to_period("W-FRI")
    last_of_week = close.groupby(weeks).last()
    week_position = pd.Series(
        np.searchsorted(last_of_week.index.asi8, weeks.asi8), index=close.index
    )

    values = last_of_week.to_numpy(float)
    out = np.full(len(close), np.nan)
    if len(values) > RSI_PERIOD:
        windows = sliding_window_view(values, RSI_PERIOD)
        positions = week_position.to_numpy()
        usable = positions >= RSI_PERIOD
        window = windows[positions[usable] - RSI_PERIOD]
        deltas = np.diff(window, axis=1)
        final = close.to_numpy(float)[usable] - window[:, -1]
        deltas = np.concatenate([deltas, final[:, None]], axis=1)

        gain = np.clip(deltas, 0.0, None).sum(axis=1) / RSI_PERIOD
        loss = -np.clip(deltas, None, 0.0).sum(axis=1) / RSI_PERIOD
        with np.errstate(divide="ignore", invalid="ignore"):
            rsi = 100.0 - 100.0 / (1.0 + gain / loss)
        out[usable] = np.where(loss == 0, 100.0, rsi)
    return pd.Series(out, index=close.index).round(2)


def build_state(qqq: pd.DataFrame, vix: pd.Series | None = None) -> pd.DataFrame:
    """One row per trading day holding the whole live market-state dict."""
    close = qqq["Close"]
    ma200 = close.rolling(MA_PERIOD).mean()
    premium = (close / ma200.where(ma200 > 0) - 1.0) * 100.0

    out = pd.DataFrame(index=qqq.index)
    out["qqqClose"] = close
    out["ma200"] = ma200
    out["premiumPercent"] = premium
    out["recent60MinPremiumPercent"] = premium.rolling(
        live.QQQ_RECOVERY_LOOKBACK_DAYS, min_periods=1
    ).min()

    recovery = out["recent60MinPremiumPercent"].le(live.QQQ_RECOVERY_MIN_DIST) & premium.ge(0)
    out["isRecoveryMarket"] = recovery.fillna(False)
    out["buyBlockMax"] = np.where(
        out["isRecoveryMarket"], live.QQQ_RECOVERY_BUY_BLOCK_MAX, live.QQQ_NORMAL_BUY_BLOCK_MAX
    )

    daily_rsi = vec.rsi(close).round(2)
    out["dailyRsi"] = daily_rsi
    out["dailyRsiPrev"] = daily_rsi.shift(1)
    out["weeklyRsi"] = _weekly_rsi(close)

    macd = vec._ema(close, 12) - vec._ema(close, 26)
    hist = (macd - vec._ema(macd, 9)).round(2)
    out["macdHist"] = hist
    out["macdHistD1"] = hist.shift(1)
    out["macdHistD2"] = hist.shift(2)

    out["rsiHotAndFalling"] = (
        out["weeklyRsi"].ge(live.QQQ_PEAK_RSI_THRESHOLD)
        & out["dailyRsi"].ge(live.QQQ_PEAK_RSI_THRESHOLD)
        & out["dailyRsi"].lt(out["dailyRsiPrev"])
    ).fillna(False)
    out["macdHistSlowing"] = (
        out["macdHist"].lt(out["macdHistD1"]) & out["macdHistD1"].lt(out["macdHistD2"])
    ).fillna(False)

    direct = np.where(
        out["isRecoveryMarket"],
        live.QQQ_RECOVERY_PEAK_DIRECT_DIST,
        live.QQQ_NORMAL_PEAK_DIRECT_DIST,
    )
    confirm = np.where(
        out["isRecoveryMarket"],
        live.QQQ_RECOVERY_PEAK_CONFIRM_DIST,
        live.QQQ_NORMAL_PEAK_CONFIRM_DIST,
    )
    out["peakDirectDist"] = direct
    out["peakConfirmDist"] = confirm

    above_direct = premium.gt(direct).fillna(False)
    above_confirm = premium.gt(confirm).fillna(False)
    out["peakTriggered"] = np.where(
        out["isRecoveryMarket"],
        above_direct,
        out["rsiHotAndFalling"] & (above_direct | (above_confirm & out["macdHistSlowing"])),
    )

    warn_dist = direct - live.QQQ_PEAK_WARN_MARGIN
    out["peakWarnDist"] = warn_dist
    out["warnTriggered"] = premium.ge(warn_dist - 1e-9).fillna(False) & ~out["peakTriggered"]

    out["vix"] = np.nan if vix is None else vix.reindex(out.index).ffill(limit=5)
    return out
