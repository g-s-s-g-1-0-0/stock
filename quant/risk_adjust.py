"""Is SW-1's excess return alpha, or just exposure to volatile names?

Comparing a trade to the equal-weight universe rewards any strategy that
happens to pick high-volatility stocks, because volatile names have fatter
right tails. The honest control is a same-date basket of stocks with the same
volatility, so this module rebuilds the benchmark that way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, engine, run, strategies

DECILES = 10


def forward_returns(panels: dict[str, pd.DataFrame], hold: int) -> pd.DataFrame:
    """Return every ticker's executable hold-period return, indexed by signal date.

    Uses the same convention as the engine: enter at the next open, exit at the
    close ``hold`` sessions after the signal, both sides paying the fee.
    """
    fee = config.FEE_BPS / 10_000.0
    columns = {}
    for ticker, panel in panels.items():
        entry = panel["Open"].shift(-1)
        exit_price = panel["Close"].shift(-hold)
        columns[ticker] = (exit_price * (1 - fee)) / (entry * (1 + fee)) - 1.0
    return pd.DataFrame(columns)


def volatility_matched_benchmark(
    panels: dict[str, pd.DataFrame], hold: int
) -> pd.DataFrame:
    """Mean hold-period return per (date, volatility decile).

    This is the return you would have earned by buying an equal-weight basket
    of every stock that was as volatile as your pick, on the same day.
    """
    forward = forward_returns(panels, hold)
    volatility = pd.DataFrame({ticker: panel["atrPct"] for ticker, panel in panels.items()})
    volatility = volatility.reindex_like(forward)

    valid = forward.notna() & volatility.notna()
    ranked = volatility.where(valid).rank(axis=1, pct=True)
    decile = np.floor(ranked * DECILES).clip(upper=DECILES - 1)

    long = pd.DataFrame(
        {
            "forward": forward.where(valid).stack(),
            "decile": decile.stack(),
        }
    ).dropna()
    long.index.names = ["date", "ticker"]

    grouped = long.groupby(["date", "decile"])["forward"].agg(["mean", "size"])
    grouped = grouped[grouped["size"] >= 5]
    return grouped["mean"].unstack("decile"), decile


def evaluate(hold: int = 40, rank_min: float = 0.90) -> pd.DataFrame:
    panels, growth = run.prepare()
    bar = config.Barriers(4.0, 2.0, hold, "swing")
    signals = strategies.swing_momentum(panels, rank_min=rank_min)
    ledger = engine.build_ledger(
        panels, signals, bar, "SW1_momentum",
        entry_mode="nextOpen", exit_policy="time", universe_growth=growth,
    )
    trades = ledger[
        ledger["filled"].fillna(False)
        & ~ledger["censored"].fillna(False)
        & ledger["dedupKept"].fillna(False)
    ].copy()

    benchmark, decile = volatility_matched_benchmark(panels, hold)

    matched = []
    for _, trade in trades.iterrows():
        date, ticker = trade["signalDate"], trade["ticker"]
        try:
            bucket = decile.at[date, ticker]
            matched.append(benchmark.at[date, bucket])
        except (KeyError, ValueError):
            matched.append(np.nan)
    trades["matchedRet"] = matched
    trades["matchedExcess"] = trades["retNet"] - trades["matchedRet"]
    return trades


def report(trades: pd.DataFrame) -> None:
    usable = trades.dropna(subset=["matchedRet"])
    print(f"\ntrades with a volatility-matched control: {len(usable)} / {len(trades)}")
    print("\n--- benchmark comparison (mean %) ---")
    table = pd.Series(
        {
            "strategy": usable["retNet"].mean() * 100,
            "equalWeightUniverse": usable["universeRet"].mean() * 100,
            "volatilityMatchedBasket": usable["matchedRet"].mean() * 100,
            "excess vs equalWeight": usable["excessRet"].mean() * 100,
            "excess vs volatilityMatched": usable["matchedExcess"].mean() * 100,
        }
    )
    print(table.round(2).to_string())

    wins = (usable["matchedExcess"] > 0).mean() * 100
    print(f"\nbeat the volatility-matched basket: {wins:.1f}% of trades")

    error = usable["matchedExcess"].std() / np.sqrt(len(usable))
    tstat = usable["matchedExcess"].mean() / error if error > 0 else np.nan
    print(f"matched excess t-stat (overlapping trades, so optimistic): {tstat:.2f}")

    print("\n--- matched excess by era (%) ---")
    dates = pd.to_datetime(usable["signalDate"])
    rows = {}
    for label, start, end in config.ERAS:
        window = usable[(dates >= start) & (dates <= end)]
        rows[label] = {
            "trades": len(window),
            "strategy%": window["retNet"].mean() * 100 if len(window) else np.nan,
            "equalWeightExcess%": window["excessRet"].mean() * 100 if len(window) else np.nan,
            "matchedExcess%": window["matchedExcess"].mean() * 100 if len(window) else np.nan,
            "beatRate%": (window["matchedExcess"] > 0).mean() * 100 if len(window) else np.nan,
        }
    print(pd.DataFrame(rows).T.round(2).to_string())

    print("\n--- matched excess by year (%) ---")
    yearly = usable.groupby("year")["matchedExcess"].agg(["size", "mean"])
    yearly["mean"] *= 100
    yearly.columns = ["trades", "matchedExcess%"]
    print(yearly.round(2).to_string())
    positive = (yearly["matchedExcess%"] > 0).mean() * 100
    print(f"positive years on matched excess: {positive:.0f}%")


def main() -> None:
    trades = evaluate()
    report(trades)


if __name__ == "__main__":
    main()
