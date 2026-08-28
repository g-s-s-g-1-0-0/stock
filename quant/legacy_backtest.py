"""Portfolio replay of the shipped Strategy 1 and Strategy 2 rules.

`quant.engine` closes a position on ATR barriers, which these rules do not
have: Strategy 1 and 2 set no profit target, so a position is held until the
market-level state closes it or the -30% circuit fires. That makes the exit
path sequential and market-driven rather than per-trade geometry, so it gets
its own simulator instead of being forced into the barrier engine.

Execution follows the same convention as `quant.engine`: a condition seen at a
bar's close is acted on at the next open, with the same fee and slippage model,
so the numbers are comparable with the other strategy reports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from calculator.rules import STRATEGY_RULES
from quant import config, engine, legacy_indicators, legacy_strategies

CIRCUIT_PCT = float(STRATEGY_RULES["CIRCUIT_PCT_1"])
REENTRY_DAYS = int(STRATEGY_RULES["REENTRY_DAYS"])
REENTRY_DROP = 0.03
"""`REENTRY_DROP` in the Apps Script constants; not mirrored into rules.py."""

SETTLEMENT_BARS = 2
"""The service waits 48 hours after a sell, which is two daily bars."""


def _reentry_allowed(bars_since_sell: int, price: float, sell_price: float) -> bool:
    if bars_since_sell < SETTLEMENT_BARS:
        return False
    if bars_since_sell > REENTRY_DAYS:
        return True
    return sell_price > 0 and price <= sell_price * (1 - REENTRY_DROP)


def simulate_ticker(
    ticker: str, panel: pd.DataFrame, entries: pd.DataFrame, market: pd.DataFrame
) -> list[dict]:
    """Walk one ticker's bars, opening and closing at most one position at a time."""
    open_, high = panel["Open"].to_numpy(float), panel["High"].to_numpy(float)
    low, close = panel["Low"].to_numpy(float), panel["Close"].to_numpy(float)
    atr_pct = panel["atrPct"].to_numpy(float)
    eligible = panel["eligible"].to_numpy(bool)

    entry1 = entries["entry1"].to_numpy(bool)
    entry2 = entries["entry2"].to_numpy(bool)
    peak = market["peakTriggered"].reindex(panel.index).fillna(False).to_numpy(bool)
    recovery_ended = market["recoveryEnded"].reindex(panel.index).fillna(False).to_numpy(bool)
    blocked = market["blockNewEntries"].reindex(panel.index).fillna(False).to_numpy(bool)

    bars = len(panel)
    trades: list[dict] = []
    sell_index: int | None = None
    sell_price = 0.0

    position: dict | None = None
    index = 0
    while index < bars:
        if position is None:
            signal = entry1[index] or entry2[index]
            if not signal or not eligible[index] or peak[index] or blocked[index]:
                index += 1
                continue
            if sell_index is not None and not _reentry_allowed(
                index - sell_index, close[index], sell_price
            ):
                index += 1
                continue

            entry_index = index + 1
            slip = engine._slippage(atr_pct[index])
            if entry_index >= bars or not np.isfinite(slip) or not np.isfinite(open_[entry_index]):
                index += 1
                continue

            position = {
                "strategy": "1" if entry1[index] else "2",
                "signalIndex": index,
                "entryIndex": entry_index,
                "entryPrice": open_[entry_index] * (1 + slip),
                "slip": slip,
                "atrPct": atr_pct[index],
                "runHigh": -np.inf,
                "runLow": np.inf,
            }
            index = entry_index
            continue

        position["runHigh"] = max(position["runHigh"], high[index])
        position["runLow"] = min(position["runLow"], low[index])

        reason = None
        if recovery_ended[index]:
            reason = "recoveryEnd"
        elif peak[index]:
            reason = "peakAlert"
        elif close[index] / position["entryPrice"] - 1.0 <= -CIRCUIT_PCT:
            reason = "circuit"

        if reason is None:
            index += 1
            continue

        exit_index = index + 1
        if exit_index >= bars:
            break
        exit_price = open_[exit_index] * (1 - position["slip"])
        position["runHigh"] = max(position["runHigh"], high[exit_index])
        position["runLow"] = min(position["runLow"], low[exit_index])
        trades.append(_close(ticker, panel, position, exit_index, exit_price, reason))
        sell_index, sell_price = exit_index, exit_price
        position = None
        index = exit_index

    if position is not None:
        trades.append(_censored(ticker, panel, position))
    return trades


def _close(
    ticker: str,
    panel: pd.DataFrame,
    position: dict,
    exit_index: int,
    exit_price: float,
    reason: str,
) -> dict:
    entry_price = position["entryPrice"]
    return {
        "strategy": position["strategy"],
        "ticker": ticker,
        "signalDate": panel.index[position["signalIndex"]],
        "entryDate": panel.index[position["entryIndex"]],
        "entryPrice": entry_price,
        "exitDate": panel.index[exit_index],
        "exitPrice": exit_price,
        "exitReason": reason,
        "censored": False,
        "daysHeld": exit_index - position["entryIndex"] + 1,
        "retGross": exit_price / entry_price - 1.0,
        "retNet": engine._net(entry_price, exit_price),
        "mfeToExit": position["runHigh"] / entry_price - 1.0,
        "maeToExit": position["runLow"] / entry_price - 1.0,
        "atrPctAtEntry": position["atrPct"],
    }


def _censored(ticker: str, panel: pd.DataFrame, position: dict) -> dict:
    """Still open when the data ends. Kept visible instead of silently dropped."""
    return {
        "strategy": position["strategy"],
        "ticker": ticker,
        "signalDate": panel.index[position["signalIndex"]],
        "entryDate": panel.index[position["entryIndex"]],
        "entryPrice": position["entryPrice"],
        "exitDate": pd.NaT,
        "exitPrice": np.nan,
        "exitReason": "censored",
        "censored": True,
        "daysHeld": len(panel) - position["entryIndex"],
        "retGross": np.nan,
        "retNet": np.nan,
        "mfeToExit": position["runHigh"] / position["entryPrice"] - 1.0,
        "maeToExit": position["runLow"] / position["entryPrice"] - 1.0,
        "atrPctAtEntry": position["atrPct"],
    }


def _market_frame(state: pd.DataFrame, signal_days: pd.Series) -> pd.DataFrame:
    timeline = legacy_strategies.season_timeline(state, signal_days)
    return pd.DataFrame(
        {
            "peakTriggered": state["peakTriggered"].astype(bool),
            "recoveryEnded": timeline["recoveryEnded"],
            "seasonOpen": timeline["seasonOpen"],
            "blockNewEntries": state["premiumPercent"].gt(state["buyBlockMax"]).fillna(False),
        },
        index=state.index,
    )


def build_ledger(
    panels: dict[str, pd.DataFrame], state: pd.DataFrame, universe_growth=None
) -> pd.DataFrame:
    """Replay every ticker and return one row per trade.

    Two passes are needed because the buy season is a market-level latch: the
    first pass finds the Strategy 1 signals that could open it, the second
    trades with the resulting timeline.
    """
    conditions = {}
    for ticker, panel in panels.items():
        legacy_indicators.add_legacy(panel)
        conditions[ticker] = legacy_strategies.entry_conditions(panel, state)

    openers = pd.DataFrame(
        {
            ticker: (frame["entry1"] & panels[ticker]["eligible"].astype(bool)).reindex(
                state.index, fill_value=False
            )
            for ticker, frame in conditions.items()
        }
    )
    tradeable = openers.any(axis=1) & ~state["peakTriggered"].astype(bool)
    market = _market_frame(state, tradeable)

    rows: list[dict] = []
    for ticker, frame in conditions.items():
        season = market["seasonOpen"].reindex(frame.index).fillna(False)
        entries = pd.DataFrame(
            {
                "entry1": frame["entry1"],
                "entry2": legacy_strategies.strategy2_entry(frame, season),
            },
            index=frame.index,
        )
        if not entries.to_numpy().any():
            continue
        rows.extend(simulate_ticker(ticker, panels[ticker], entries, market))

    ledger = pd.DataFrame(rows)
    if ledger.empty:
        return ledger

    ledger = ledger.sort_values(["signalDate", "ticker"]).reset_index(drop=True)
    ledger["year"] = pd.to_datetime(ledger["signalDate"]).dt.year
    if universe_growth is not None:
        closed = ~ledger["censored"]
        ledger["universeRet"] = np.nan
        ledger.loc[closed, "universeRet"] = [
            universe_growth.between(row.entryDate, row.exitDate)
            for row in ledger[closed].itertuples()
        ]
        ledger["excessRet"] = ledger["retNet"] - ledger["universeRet"]
    return ledger


def eras(ledger: pd.DataFrame) -> pd.DataFrame:
    """Summary per era, on closed trades only."""
    closed = ledger[~ledger["censored"]]
    rows = []
    for label, start, end in config.ERAS:
        window = closed[
            (closed["signalDate"] >= start) & (closed["signalDate"] <= end)
        ]
        if window.empty:
            continue
        rows.append(
            {
                "era": label,
                "trades": len(window),
                "meanRet%": window["retNet"].mean() * 100,
                "medianRet%": window["retNet"].median() * 100,
                "winRate%": window["retNet"].gt(0).mean() * 100,
                "meanHold": window["daysHeld"].mean(),
                "mfe%": window["mfeToExit"].mean() * 100,
                "mae%": window["maeToExit"].mean() * 100,
                "universe%": window["universeRet"].mean() * 100
                if "universeRet" in window
                else np.nan,
                "excess%": window["excessRet"].mean() * 100
                if "excessRet" in window
                else np.nan,
            }
        )
    return pd.DataFrame(rows)
