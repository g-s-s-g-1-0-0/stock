"""Does the daily-bar exit simulation agree with hourly bars?

A daily bar only reveals four prices, so the order in which a target and a
stop were reached has to be assumed. Hourly bars make that order visible for
the last two years. If the two disagree, the daily result is path-dependent
and must be discarded rather than trusted.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from quant import collect_intraday, config, engine, run, strategies


def _replay_hourly(
    hourly: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_price: float,
    target_pct: float,
    stop_pct: float,
    max_hold: int,
) -> dict[str, object] | None:
    """Re-run the same barriers over hourly bars from the same entry."""
    window = hourly.loc[hourly.index >= entry_date]
    if window.empty:
        return None
    sessions = pd.Index(sorted({stamp.date() for stamp in window.index}))
    if len(sessions) < max_hold:
        return None
    allowed = set(sessions[:max_hold])
    window = window[[stamp.date() in allowed for stamp in window.index]]

    target_price = entry_price * (1 + target_pct)
    stop_price = entry_price * (1 - stop_pct)
    fee = config.FEE_BPS / 10_000.0

    for stamp, row in window.iterrows():
        hit_stop = row["Low"] <= stop_price
        hit_target = row["High"] >= target_price
        if hit_stop and hit_target:
            return {"reason": "ambiguousHour", "retNet": np.nan, "exitAt": stamp}
        if hit_stop or hit_target:
            price = stop_price if hit_stop else target_price
            return {
                "reason": "stop" if hit_stop else "target",
                "retNet": (price * (1 - fee)) / (entry_price * (1 + fee)) - 1.0,
                "exitAt": stamp,
            }
    final = window["Close"].iloc[-1]
    return {
        "reason": "time",
        "retNet": (final * (1 - fee)) / (entry_price * (1 + fee)) - 1.0,
        "exitAt": window.index[-1],
    }


def compare(strategy: str = "DT1_oversold") -> pd.DataFrame:
    panels, growth = run.prepare()
    signals = strategies.REGISTRY[strategy](panels)
    bar = run.BARRIERS[strategy]
    ledger = engine.build_ledger(
        panels, signals, bar, strategy,
        entry_mode="nextOpen", exit_policy="barrier", universe_growth=growth,
    )
    trades = ledger[ledger["filled"].fillna(False) & ~ledger["censored"].fillna(False)]

    cache: dict[str, pd.DataFrame] = {}
    rows = []
    skipped_scale = 0
    for _, trade in trades.iterrows():
        ticker = trade["ticker"]
        if ticker not in cache:
            cache[ticker] = collect_intraday.load("1h", ticker)
        hourly = cache[ticker]
        if hourly.empty or trade["entryDate"] < hourly.index[0]:
            continue

        # The daily cache is split/dividend adjusted while hourly bars are raw,
        # so the two price scales must be aligned on the entry date before any
        # barrier comparison is meaningful.
        same_day = hourly[hourly.index.normalize() == trade["entryDate"]]
        daily_close = panels[ticker]["Close"].get(trade["entryDate"])
        if same_day.empty or daily_close is None or not np.isfinite(daily_close):
            skipped_scale += 1
            continue
        scale = daily_close / float(same_day["Close"].iloc[-1])
        if not np.isfinite(scale) or scale <= 0:
            skipped_scale += 1
            continue
        scaled = hourly[["Open", "High", "Low", "Close"]] * scale

        replay = _replay_hourly(
            scaled, trade["entryDate"], trade["entryPrice"],
            trade["targetPct"], trade["stopPct"], bar.max_hold,
        )
        if replay is None:
            continue
        rows.append(
            {
                "ticker": ticker,
                "entryDate": trade["entryDate"],
                "dailyReason": trade["exitReason"],
                "hourlyReason": replay["reason"],
                "dailyRet%": trade["retNet"] * 100,
                "hourlyRet%": replay["retNet"] * 100,
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        print("no overlapping trades between the daily ledger and hourly coverage")
    elif skipped_scale:
        print(f"skipped {skipped_scale} trades that could not be price-aligned")
    return table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="DT1_oversold", choices=list(strategies.REGISTRY))
    args = parser.parse_args()

    table = compare(args.strategy)
    if table.empty:
        return

    agree = (table["dailyReason"] == table["hourlyReason"]).mean() * 100
    difference = table["hourlyRet%"] - table["dailyRet%"]
    print(f"\n=== {args.strategy}: daily vs hourly exit replay ===")
    print(f"overlapping trades      : {len(table)}")
    print(f"same exit reason        : {agree:.1f}%")
    print(f"daily mean return       : {table['dailyRet%'].mean():.2f}%")
    print(f"hourly mean return      : {table['hourlyRet%'].mean():.2f}%")
    print(f"mean difference         : {difference.mean():.2f}pp")
    print(f"trades unresolved in 1h : {(table['hourlyReason'] == 'ambiguousHour').sum()}")
    print("\nexit reason crosstab (rows=daily, cols=hourly):")
    print(pd.crosstab(table["dailyReason"], table["hourlyReason"]).to_string())

    verdict = (
        "daily result is trustworthy for this rule"
        if abs(difference.mean()) < 0.5 and agree > 85
        else "daily and hourly disagree: treat the daily number as path-dependent"
    )
    print(f"\nverdict: {verdict}")


if __name__ == "__main__":
    main()
