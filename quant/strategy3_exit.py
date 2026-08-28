"""Strategy 3 with its own +12/-12 exit versus the Strategy 1/2 market exit.

Strategy 3 (정상장 볼린저 워시아웃) ships with per-trade geometry: +12% target,
-12% stop, 20-session cap, and a 횡보장 고점 regime close. Strategies 1 and 2
have no target at all -- a position lives until the buy season ends, the Nasdaq
peak alert fires, or the -30% circuit trips. This module runs the same Strategy
3 entries through both exit policies so the swap can be priced.

Entries, execution, fees, and re-entry are identical across policies; only the
exit path changes. Signals are read at a bar's close and acted on at the next
open, the same convention as `quant.engine` and `quant.legacy_backtest`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from calculator.rules import STRATEGY_RULES
from quant import config, engine, legacy_backtest, legacy_indicators, legacy_strategies
from quant.legacy_backtest import _reentry_allowed

TARGET_PCT_3 = float(STRATEGY_RULES["TARGET_PCT_3"])
CIRCUIT_PCT_3 = float(STRATEGY_RULES["CIRCUIT_PCT_3"])
MAX_HOLD_DAYS_3 = int(STRATEGY_RULES["MAX_HOLD_DAYS_3"])
CIRCUIT_PCT_12 = float(STRATEGY_RULES["CIRCUIT_PCT_1"])
PCT_B_LOW_MAX = float(STRATEGY_RULES["S3_PCT_B_LOW_MAX"])
S3_RSI_MAX = float(STRATEGY_RULES["S3_RSI_MAX"])
NASDAQ_DIST_UPPER = float(STRATEGY_RULES["NASDAQ_DIST_UPPER"])


def regime_labels(state: pd.DataFrame) -> pd.Series:
    """`calculator.market_regime.qqq_regime_label`, one label per trading day."""
    premium = state["premiumPercent"]
    label = pd.Series("판단 불가", index=state.index, dtype=object)
    known = premium.notna()
    label[known & premium.lt(NASDAQ_DIST_UPPER)] = "하락장"
    label[known & premium.ge(NASDAQ_DIST_UPPER) & premium.le(state["buyBlockMax"])] = "정상장"
    label[known & premium.gt(state["buyBlockMax"])] = "횡보장 고점"
    label[state["isRecoveryMarket"].astype(bool)] = "회복장"
    return label


def entry3(panel: pd.DataFrame, conditions: pd.DataFrame, normal: pd.Series) -> pd.Series:
    """Close above MA200 and a low that washed out to the Bollinger floor.

    The live rule also requires Strategy 1 and 2 to be unmet that day, so the
    three never fire on the same name on the same bar.
    """
    market = normal.reindex(panel.index).fillna(False)
    return (
        market
        & panel["Close"].gt(panel["legMa200"]).fillna(False)
        & panel["legPctBLow"].round(2).le(PCT_B_LOW_MAX).fillna(False)
        & panel["legRsi"].round(2).le(S3_RSI_MAX).fillna(False)
        & ~conditions["entry1"].to_numpy(bool)
        & ~conditions["entry3blocker2"].to_numpy(bool)
    )


def _exit_reason(
    policy: str,
    ret: float,
    bars_held: int,
    sideways_top: bool,
    recovery_ended: bool,
    peak: bool,
    confirmed: bool = False,
) -> str | None:
    if policy.startswith("recover:"):
        # The entry is a bet that the washout bounces. Give it a fixed window to
        # get back to the entry price; if it cannot, the bet was wrong and the
        # re-entry gate decides when to try again. Once it does reclaim the
        # entry, no target -- ride until the market closes it, as in 1 and 2.
        parts = policy.split(":")
        window = int(parts[1])
        kind = parts[2] if len(parts) > 2 else "regime"
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        if not confirmed and bars_held >= window:
            return "noBounce"
        if kind in ("regime", "regimestop") and confirmed and sideways_top:
            return "sidewaysTop"
        if kind == "regimestop" and ret <= -CIRCUIT_PCT_3:
            return "stop12"
        if ret <= -CIRCUIT_PCT_12:
            return "circuit30"
        return None

    if policy == "native":
        if ret <= -CIRCUIT_PCT_3:
            return "stop12"
        if ret >= TARGET_PCT_3:
            return "target12"
        if sideways_top:
            return "sidewaysTop"
        if bars_held >= MAX_HOLD_DAYS_3:
            return "timeCap"
        return None

    if policy.startswith("tight:") or policy.startswith("tightreg:"):
        # Bought expecting tomorrow's bounce: if it keeps falling, cut immediately
        # and wait for the re-entry gate. If it does bounce, hold until the market
        # closes the trade the way Strategy 1 and 2 do.
        kind, level = policy.split(":", 1)
        if ret <= -float(level):
            return "tightStop"
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        if kind == "tightreg" and sideways_top:
            return "sidewaysTop"
        return None

    if policy.startswith("stop:"):
        # Target and time cap dropped, regime exits kept, stop swept.
        if ret <= -float(policy.split(":", 1)[1]):
            return "stop"
        if sideways_top:
            return "sidewaysTop"
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        return None

    if policy == "no_target":
        # Only the +12% target is removed; the -12% stop, cap, and regime exit stay.
        if ret <= -CIRCUIT_PCT_3:
            return "stop12"
        if sideways_top:
            return "sidewaysTop"
        if bars_held >= MAX_HOLD_DAYS_3:
            return "timeCap"
        return None

    if policy == "no_target_no_cap":
        if ret <= -CIRCUIT_PCT_3:
            return "stop12"
        if sideways_top:
            return "sidewaysTop"
        if recovery_ended:
            return "recoveryEnd"
        return None

    if policy == "market":
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        if ret <= -CIRCUIT_PCT_12:
            return "circuit30"
        return None

    if policy == "market_keep_stop":
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        if ret <= -CIRCUIT_PCT_3:
            return "stop12"
        return None

    if policy == "market_regime":
        if recovery_ended:
            return "recoveryEnd"
        if peak:
            return "peakAlert"
        if sideways_top:
            return "sidewaysTop"
        if ret <= -CIRCUIT_PCT_12:
            return "circuit30"
        return None

    raise ValueError(f"unknown exit policy: {policy}")


def simulate_ticker(
    ticker: str,
    panel: pd.DataFrame,
    entries: pd.Series,
    market: pd.DataFrame,
    policy: str,
) -> list[dict]:
    """One ticker, one position at a time, under a single exit policy."""
    open_, high = panel["Open"].to_numpy(float), panel["High"].to_numpy(float)
    low, close = panel["Low"].to_numpy(float), panel["Close"].to_numpy(float)
    atr_pct = panel["atrPct"].to_numpy(float)
    eligible = panel["eligible"].to_numpy(bool)

    signal = entries.to_numpy(bool)
    peak = market["peakTriggered"].reindex(panel.index).fillna(False).to_numpy(bool)
    recovery_ended = market["recoveryEnded"].reindex(panel.index).fillna(False).to_numpy(bool)
    sideways = market["sidewaysTop"].reindex(panel.index).fillna(False).to_numpy(bool)

    bars = len(panel)
    trades: list[dict] = []
    sell_index: int | None = None
    sell_price = 0.0

    position: dict | None = None
    index = 0
    while index < bars:
        if position is None:
            if not signal[index] or not eligible[index] or peak[index]:
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
                "strategy": "3",
                "signalIndex": index,
                "entryIndex": entry_index,
                "entryPrice": open_[entry_index] * (1 + slip),
                "slip": slip,
                "atrPct": atr_pct[index],
                "runHigh": -np.inf,
                "runLow": np.inf,
                "confirmed": False,
            }
            index = entry_index
            continue

        position["runHigh"] = max(position["runHigh"], high[index])
        position["runLow"] = min(position["runLow"], low[index])
        if close[index] >= position["entryPrice"]:
            position["confirmed"] = True

        reason = _exit_reason(
            policy,
            close[index] / position["entryPrice"] - 1.0,
            index - position["entryIndex"] + 1,
            bool(sideways[index]),
            bool(recovery_ended[index]),
            bool(peak[index]),
            confirmed=position["confirmed"],
        )
        if reason is None:
            index += 1
            continue

        exit_index = index + 1
        if exit_index >= bars:
            break
        exit_price = open_[exit_index] * (1 - position["slip"])
        position["runHigh"] = max(position["runHigh"], high[exit_index])
        position["runLow"] = min(position["runLow"], low[exit_index])
        trades.append(
            legacy_backtest._close(ticker, panel, position, exit_index, exit_price, reason)
        )
        sell_index, sell_price = exit_index, exit_price
        position = None
        index = exit_index

    if position is not None:
        trades.append(legacy_backtest._censored(ticker, panel, position))
    return trades


def build_signals(
    panels: dict[str, pd.DataFrame], state: pd.DataFrame
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """Strategy 3 entries per ticker plus the market frame every policy reads.

    Strategy 2's season latch has to be replayed first: an entry that Strategy 2
    would have taken is not a Strategy 3 entry, and the same latch drives the
    recovery-end exit used by the market policies.
    """
    labels = regime_labels(state)
    normal = labels.eq("정상장")

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
    market = legacy_backtest._market_frame(state, tradeable)
    market["sidewaysTop"] = labels.eq("횡보장 고점")

    entries = {}
    for ticker, frame in conditions.items():
        season = market["seasonOpen"].reindex(frame.index).fillna(False)
        frame["entry3blocker2"] = legacy_strategies.strategy2_entry(frame, season)
        entries[ticker] = entry3(panels[ticker], frame, normal)
    return entries, market


def apply_entry_filter(
    signals: tuple[dict[str, pd.Series], pd.DataFrame], panels: dict[str, pd.DataFrame],
    key: str, threshold: float, upper: float | None = None,
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """Narrow the entry set by a panel column, leaving the exit path untouched."""
    entries, market = signals
    kept = {}
    for ticker, entry in entries.items():
        band = panels[ticker][key].ge(threshold)
        if upper is not None:
            band &= panels[ticker][key].le(upper)
        kept[ticker] = entry & band.fillna(False)
    return kept, market


def build_ledger(
    panels: dict[str, pd.DataFrame],
    state: pd.DataFrame,
    policy: str,
    universe_growth=None,
    signals: tuple[dict[str, pd.Series], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    entries, market = signals if signals is not None else build_signals(panels, state)

    rows: list[dict] = []
    for ticker, entry in entries.items():
        if not entry.to_numpy().any():
            continue
        rows.extend(simulate_ticker(ticker, panels[ticker], entry, market, policy))

    ledger = pd.DataFrame(rows)
    if ledger.empty:
        return ledger

    ledger = ledger.sort_values(["signalDate", "ticker"]).reset_index(drop=True)
    ledger["policy"] = policy
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


def summarize(ledger: pd.DataFrame, label: str) -> dict:
    closed = ledger[~ledger["censored"]]
    row = {
        "policy": label,
        "trades": len(closed),
        "censored": int(ledger["censored"].sum()),
        "mean%": closed["retNet"].mean() * 100,
        "median%": closed["retNet"].median() * 100,
        "win%": closed["retNet"].gt(0).mean() * 100,
        "hold": closed["daysHeld"].mean(),
        "worst%": closed["retNet"].min() * 100,
        "mfe%": closed["mfeToExit"].mean() * 100,
        "mae%": closed["maeToExit"].mean() * 100,
    }
    if "excessRet" in closed:
        row["universe%"] = closed["universeRet"].mean() * 100
        row["excess%"] = closed["excessRet"].mean() * 100
        row["excessWin%"] = closed["excessRet"].gt(0).mean() * 100
    return row


def portfolio(ledger: pd.DataFrame, slots: int = 5) -> dict:
    """Replay the ledger through a fixed number of slots to get compounded terms.

    Per-trade means ignore capacity: a policy holding 159 sessions per trade
    cannot take the next signal, and that opportunity cost only shows up once
    the money is finite. Slots are filled first-come by signal date, each takes
    an equal share of the cash free at that moment, and equity is stamped at
    exits, so the drawdown is a realized-trade drawdown, not a daily one.
    """
    closed = ledger[~ledger["censored"]].sort_values("entryDate")
    if closed.empty:
        return {}

    free_at = [pd.Timestamp.min] * slots
    taken, skipped = [], 0
    for row in closed.itertuples():
        slot = min(range(slots), key=lambda i: free_at[i])
        if free_at[slot] > row.entryDate:
            skipped += 1
            continue
        free_at[slot] = row.exitDate
        taken.append((row.exitDate, row.retNet))

    equity = 1.0
    curve = pd.Series(dtype=float)
    for exit_date, ret in sorted(taken):
        equity += (equity / slots) * ret
        curve[exit_date] = equity
    peak = curve.cummax()
    years = (closed["exitDate"].max() - closed["entryDate"].min()).days / 365.25
    return {
        "slots": slots,
        "taken": len(taken),
        "skipped(no slot)": skipped,
        "total%": (equity - 1.0) * 100,
        "CAGR%": ((equity ** (1 / years) - 1.0) * 100) if years > 0 and equity > 0 else np.nan,
        "MDD%": ((curve / peak - 1.0).min() * 100) if len(curve) else np.nan,
    }


def annualized(ledger: pd.DataFrame) -> dict:
    """Per-trade returns say nothing about capital speed; holding period does.

    A trade that makes 5% in 12 sessions and one that makes 5% in 400 are not
    the same trade, so both are put on a per-session basis.
    """
    closed = ledger[~ledger["censored"]]
    if closed.empty:
        return {}
    per_session = closed["retNet"] / closed["daysHeld"]
    excess_per_session = (
        closed["excessRet"] / closed["daysHeld"] if "excessRet" in closed else None
    )
    return {
        "ret/session bps": per_session.mean() * 10_000,
        "excess/session bps": excess_per_session.mean() * 10_000
        if excess_per_session is not None
        else np.nan,
        "sessions used": closed["daysHeld"].sum(),
    }
