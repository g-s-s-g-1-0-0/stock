"""Vectorized replay of the shipped Strategy 1 and Strategy 2 entry rules.

`calculator.rules.evaluate_buy_condition` decides one ticker on one day. These
are the same ten conditions evaluated for every ticker across every day, so the
rules that actually trade can be measured on 27 years instead of on the last
refresh.

The service rounds indicators to two decimals (six for the regression slope)
before comparing them to thresholds, so the same rounding is applied here.
Without it a value sitting on a threshold would flip, which is exactly where
a threshold rule decides.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from calculator.rules import STRATEGY_RULES

RSI_MAX = float(STRATEGY_RULES["RSI_MAX"])
CCI_MIN = float(STRATEGY_RULES["CCI_MIN"])
VIX_MIN = float(STRATEGY_RULES["VIX_MIN"])
LR_TOUCH_RATIO = float(STRATEGY_RULES["LR_TOUCH_RATIO"])
MA_TOUCH_RATIO = float(STRATEGY_RULES["MA_TOUCH_RATIO"])
MA_RECLAIM_RATIO = float(STRATEGY_RULES["MA_RECLAIM_RATIO"])
NASDAQ_DIST_UPPER = float(STRATEGY_RULES["NASDAQ_DIST_UPPER"])
RECOVERY_EXIT_CONFIRM_DAYS = int(STRATEGY_RULES["RECOVERY_EXIT_CONFIRM_DAYS"])

MA_TOUCH_WINDOWS = (20, 60, 144, 200)


def _align(state: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """Broadcast market state onto a ticker's calendar, as the service does."""
    out = pd.DataFrame(index=index)
    for column in ("vix", "premiumPercent", "buyBlockMax"):
        out[column] = state[column].astype(float).reindex(index).ffill(limit=5)
    out["isRecoveryMarket"] = (
        state["isRecoveryMarket"].astype(float).reindex(index).ffill(limit=5).fillna(0.0).gt(0.5)
    )
    return out


def _ma_touch(low: pd.Series, close: pd.Series, ma: pd.Series) -> pd.Series:
    """Pierced the average intraday but closed back near or above it."""
    valid = ma.gt(0)
    return (low.le(ma * MA_TOUCH_RATIO) & close.ge(ma * MA_RECLAIM_RATIO) & valid).fillna(False)


def entry_conditions(panel: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    """Every Strategy 1 and Strategy 2 condition, one row per trading day.

    ``panel`` must already carry the ``leg*`` columns from
    :mod:`quant.legacy_indicators`. Strategy 2's season condition is left out
    because it is a portfolio-level latch, not a per-ticker fact; combine it
    with :func:`strategy2_entry`.
    """
    market = _align(state, panel.index)
    close, low = panel["Close"], panel["Low"]

    rsi = panel["legRsi"].round(2)
    cci = panel["legCci"].round(2)
    slope = panel["legLrSlope"].round(6)
    trendline = panel["legLrTrendline"].round(2)

    out = pd.DataFrame(index=panel.index)
    out["s1cond1"] = close.lt(panel["legMa200"]).fillna(False)
    out["s1cond2"] = market["vix"].ge(VIX_MIN).fillna(False)
    out["s1cond3"] = (rsi.lt(RSI_MAX) | cci.lt(CCI_MIN)).fillna(False)
    out["s1cond4"] = slope.gt(0).fillna(False)
    out["s1cond5"] = (trendline.gt(0) & low.le(trendline * LR_TOUCH_RATIO)).fillna(False)
    out["s1cond6"] = market["premiumPercent"].lt(NASDAQ_DIST_UPPER).fillna(False)
    out["entry1"] = np.logical_and.reduce([out[f"s1cond{n}"] for n in range(1, 7)])

    touches = []
    for window in MA_TOUCH_WINDOWS:
        touch = _ma_touch(low, close, panel[f"legMa{window}"])
        out[f"touch{window}"] = touch
        touches.append(touch)

    # s2cond1 is the season latch and is supplied by the caller.
    out["s2cond2"] = market["isRecoveryMarket"]
    out["s2cond3"] = market["premiumPercent"].le(market["buyBlockMax"]).fillna(False)
    out["s2cond4"] = np.logical_or.reduce(touches)
    return out


def strategy2_entry(conditions, season_open):
    """Strategy 2 fires only inside an open season and never over Strategy 1.

    Accepts either one row or a whole frame, so the same rule serves the
    parity test and the simulation.
    """
    return (
        np.asarray(season_open)
        & np.asarray(conditions["s2cond2"])
        & np.asarray(conditions["s2cond3"])
        & np.asarray(conditions["s2cond4"])
        & ~np.asarray(conditions["entry1"])
    )


def season_timeline(state: pd.DataFrame, opened_by_entry: pd.Series) -> pd.DataFrame:
    """Replay the buy-season latch day by day.

    The season opens on the first Strategy 1 entry anywhere in the universe and
    closes only after the market has left recovery for two confirmed days. It
    is a market-level latch, so it must be walked in order rather than derived
    per ticker.

    Deviation from the service: there, a Strategy 1 entry opens the season for
    tickers processed later in the *same* sheet pass, which makes the result
    depend on row order. Here the season opens at the day's close, so Strategy
    2 can first fire the next day.
    """
    recovery = state["isRecoveryMarket"].to_numpy(bool)
    triggers = opened_by_entry.reindex(state.index).fillna(False).to_numpy(bool)

    length = len(state)
    open_flags = np.zeros(length, dtype=bool)
    ended_flags = np.zeros(length, dtype=bool)
    saw_flags = np.zeros(length, dtype=bool)
    streaks = np.zeros(length, dtype=int)

    is_open = saw_recovery = False
    streak = 0
    for i in range(length):
        if recovery[i]:
            if is_open:
                saw_recovery = True
            streak = 0
        elif saw_recovery:
            streak += 1
        else:
            streak = 0

        ended = is_open and saw_recovery and streak >= RECOVERY_EXIT_CONFIRM_DAYS
        open_flags[i] = is_open
        ended_flags[i] = ended
        saw_flags[i] = saw_recovery
        streaks[i] = streak

        if ended:
            is_open = saw_recovery = False
            streak = 0
        elif triggers[i] and not is_open:
            is_open = True

    return pd.DataFrame(
        {
            "seasonOpen": open_flags,
            "sawRecovery": saw_flags,
            "nonRecoveryStreak": streaks,
            "recoveryEnded": ended_flags,
        },
        index=state.index,
    )
