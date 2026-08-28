"""Measure the rules that actually shipped, on the point-in-time universe.

Every earlier report in this package measured candidate strategies. This one
measures Strategy 1 and Strategy 2 themselves -- the rules the live service has
been trading -- so their real cost is on the same yardstick as the candidates
they were going to be replaced by.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, data, legacy_backtest, legacy_market, sp500_data

LABELS = {"1": "시장 공포 저점 진입", "2": "상승 추세 이평선 눌림목"}


def build_state() -> pd.DataFrame:
    qqq = data.load_market("QQQ")
    vix = data.load_market("_VIX")
    if qqq is None or vix is None:
        raise RuntimeError("QQQ or _VIX daily bars are missing from .bt_cache")
    return legacy_market.build_state(qqq, vix["Close"])


def _headline(trades: pd.DataFrame, title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    if trades.empty:
        print("no trades")
        return
    print(f"trades: {len(trades)}  tickers: {trades['ticker'].nunique()}")
    print(f"realized mean:  {trades['retNet'].mean() * 100:6.2f}%")
    print(f"realized median:{trades['retNet'].median() * 100:6.2f}%")
    print(f"win rate:       {trades['retNet'].gt(0).mean() * 100:6.2f}%")
    print(f"mean hold:      {trades['daysHeld'].mean():6.1f} sessions")
    print(f"MFE mean:       {trades['mfeToExit'].mean() * 100:6.2f}%")
    print(f"MAE mean:       {trades['maeToExit'].mean() * 100:6.2f}%")
    print(f"worst trade:    {trades['retNet'].min() * 100:6.2f}%")
    if "excessRet" in trades:
        print(f"universe mean:  {trades['universeRet'].mean() * 100:6.2f}%")
        print(f"EXCESS mean:    {trades['excessRet'].mean() * 100:6.2f}%")


def _exit_mix(trades: pd.DataFrame) -> None:
    if trades.empty:
        return
    print("\n--- exit reasons ---")
    counts = trades["exitReason"].value_counts()
    for reason, count in counts.items():
        window = trades[trades["exitReason"] == reason]
        print(
            f"  {reason:<12} {count:>5} ({count / len(trades) * 100:4.1f}%)  "
            f"mean {window['retNet'].mean() * 100:6.2f}%  "
            f"hold {window['daysHeld'].mean():5.1f}"
        )


def _yearly(trades: pd.DataFrame) -> pd.DataFrame:
    table = trades.groupby("year").agg(
        trades=("retNet", "size"),
        realized=("retNet", "mean"),
        excess=("excessRet", "mean"),
    )
    table["realized"] *= 100
    table["excess"] *= 100
    return table


def report(ledger: pd.DataFrame) -> None:
    closed = ledger[~ledger["censored"]]
    censored = int(ledger["censored"].sum())

    for code in ("1", "2"):
        trades = closed[closed["strategy"] == code]
        _headline(trades, f"Strategy {code}. {LABELS[code]} / point-in-time S&P 500")
        if trades.empty:
            continue
        _exit_mix(trades)
        print("\n--- by era ---")
        print(legacy_backtest.eras(trades).round(2).to_string(index=False))
        print("\n--- by year ---")
        print(_yearly(trades).round(2).to_string())

    _headline(closed, "Strategy 1 + 2 combined")
    if censored:
        print(f"\nstill open at the end of data: {censored} trade(s)")


def main() -> None:
    panels, growth = sp500_data.build()
    state = build_state()
    print(f"market state: {state.index[0].date()} .. {state.index[-1].date()}")
    print(
        f"recovery-market days: {int(state['isRecoveryMarket'].sum())}, "
        f"peak-alert days: {int(state['peakTriggered'].sum())}"
    )

    ledger = legacy_backtest.build_ledger(panels, state, growth)
    if ledger.empty:
        print("\nno trades: the shipped rules never fired on this universe")
        return

    path = f"{config.__file__.rsplit('/', 1)[0]}/out/ledger_legacy_sp500.csv"
    ledger.to_csv(path, index=False)
    report(ledger)
    print(f"\nledger: {path}")


if __name__ == "__main__":
    main()
