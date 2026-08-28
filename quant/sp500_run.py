"""Re-test the surviving strategy candidates on the point-in-time universe.

The watchlist run put SW-1's excess return at +1.16% per 40 sessions, but most
of that came from names added to the watchlist because they won after 2023.
This rerun asks the same question of a universe that could have been known in
advance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, engine, sp500_data, strategies

HOLD = 40
STRATEGIES = ("SW1_momentum", "SW3_washout")


def _trades(ledger: pd.DataFrame) -> pd.DataFrame:
    keep = (
        ledger["filled"].astype("boolean").fillna(False)
        & ~ledger["censored"].astype("boolean").fillna(False)
        & ledger["dedupKept"].astype("boolean").fillna(False)
    )
    return ledger[keep].copy()


def run(name: str, panels, growth, exit_policy: str = "time") -> pd.DataFrame:
    bar = config.Barriers(4.0, 2.0, HOLD, "swing")
    signals = strategies.REGISTRY[name](panels)
    ledger = engine.build_ledger(
        panels, signals, bar, name,
        entry_mode="nextOpen", exit_policy=exit_policy, universe_growth=growth,
    )
    return _trades(ledger)


def era_table(trades: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(trades["signalDate"])
    rows = {}
    for label, start, end in config.ERAS:
        window = trades[(dates >= start) & (dates <= end)]
        rows[label] = {
            "trades": len(window),
            "realized%": window["retNet"].mean() * 100 if len(window) else np.nan,
            "universe%": window["universeRet"].mean() * 100 if len(window) else np.nan,
            "excess%": window["excessRet"].mean() * 100 if len(window) else np.nan,
            "win%": (window["retNet"] > 0).mean() * 100 if len(window) else np.nan,
        }
    return pd.DataFrame(rows).T


def yearly(trades: pd.DataFrame) -> pd.DataFrame:
    table = trades.groupby("year")["excessRet"].agg(["size", "mean"])
    table["mean"] *= 100
    table.columns = ["trades", "excess%"]
    return table


def concentration(trades: pd.DataFrame, since: str) -> None:
    window = trades[pd.to_datetime(trades["signalDate"]) >= since]
    if not len(window):
        return
    gross = window["excessRet"].clip(lower=0)
    by_ticker = gross.groupby(window["ticker"]).sum().sort_values(ascending=False)
    total = by_ticker.sum()
    if total <= 0:
        return
    top = by_ticker.head(5)
    print(f"\n{since}+ : {len(window)} trades, {window['ticker'].nunique()} distinct tickers")
    print(f"  top 5 tickers hold {top.sum() / total * 100:.0f}% of gross positive excess")
    print("  " + ", ".join(f"{k} {v / total * 100:.0f}%" for k, v in top.items()))


def main() -> None:
    panels, growth = sp500_data.build()

    for name in STRATEGIES:
        trades = run(name, panels, growth)
        print(f"\n{'=' * 78}\n{name} / time exit / {HOLD} sessions / point-in-time S&P 500")
        print(f"{'=' * 78}")
        print(f"trades: {len(trades)}  tickers: {trades['ticker'].nunique()}")
        print(f"realized mean: {trades['retNet'].mean() * 100:.2f}%")
        print(f"universe mean: {trades['universeRet'].mean() * 100:.2f}%")
        print(f"EXCESS mean:   {trades['excessRet'].mean() * 100:.2f}%")
        print("\n--- by era ---")
        print(era_table(trades).round(2).to_string())
        print("\n--- excess by year ---")
        print(yearly(trades).round(2).to_string())
        table = yearly(trades)
        recent = table[table.index >= 2013]
        print(f"positive years since 2013: {(recent['excess%'] > 0).mean() * 100:.0f}%")
        concentration(trades, "2023-01-01")


if __name__ == "__main__":
    main()
