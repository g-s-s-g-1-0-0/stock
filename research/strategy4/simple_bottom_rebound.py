"""Simple bottom-rebound study: 20-day low plus a 20-day capitulation drop.

The condition was selected from 2001-2022 only:
  1) today's low is a new 20-session low
  2) the stock is down at least 30% over the last 20 sessions

Signal is confirmed at D close. Entry is D+1 open. Results show every D+1
through D+20 close and +10%/+15%/+20% target exits.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest_qqq_block_v2 import UNIVERSE
from research.strategy4.bottom_rebound_core import (
    episode_signals,
    event_path,
    simulate_exit,
)
from research.strategy4.ma200_macd_golden import CACHE, OUT_DIR

FEE = 0.001
HORIZON = 20
TARGETS = (0.10, 0.15, 0.20)
STOPS = (None, 0.10, 0.15)
TEST_START = pd.Timestamp("2023-01-01")


def cached_price(symbol: str) -> pd.DataFrame | None:
    path = os.path.join(CACHE, f"s4_{symbol.replace('^', '_')}.pkl")
    if not os.path.exists(path):
        return None
    raw = pd.read_pickle(path)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not set(needed).issubset(raw.columns):
        return None
    out = raw[needed].copy().dropna().sort_index()
    out = out[(out[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out if len(out) > 40 else None


def watchlist() -> dict[str, str]:
    path = os.path.join(CACHE, "s4_watchlist_map.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def masks(raw: pd.DataFrame) -> dict[str, pd.Series]:
    new_low = raw["Low"] <= raw["Low"].rolling(20).min().shift(1)
    capitulation = raw["Close"].pct_change(20, fill_method=None) <= -0.30
    return {
        "20일신저가_기준선": new_low.fillna(False),
        "20일신저가_20일수익-30%": (new_low & capitulation).fillna(False),
    }


def collect(symbols: dict[str, str], universe: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    events: list[dict] = []
    trades: list[dict] = []
    for ticker, symbol in symbols.items():
        raw = cached_price(symbol)
        if raw is None:
            continue
        for strategy, mask in masks(raw).items():
            for index in episode_signals(mask):
                path = event_path(raw, index, horizon=HORIZON, fee=FEE)
                path.update(
                    {
                        "ticker": ticker,
                        "symbol": symbol,
                        "universe": universe,
                        "strategy": strategy,
                        "period": "test" if raw.index[index] >= TEST_START else "pretest",
                    }
                )
                events.append(path)
                if strategy == "20일신저가_기준선":
                    continue
                for target in TARGETS:
                    for stop in STOPS:
                        trade = simulate_exit(
                            raw,
                            index,
                            target=target,
                            stop=stop,
                            horizon=HORIZON,
                            fee=FEE,
                        )
                        trade.update(
                            {
                                "ticker": ticker,
                                "symbol": symbol,
                                "universe": universe,
                                "strategy": strategy,
                                "period": path["period"],
                            }
                        )
                        trades.append(trade)
    return pd.DataFrame(events), pd.DataFrame(trades)


def path_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    scopes = [("all", events), ("test", events[events["period"] == "test"])]
    for scope, scoped in scopes:
        for (universe, strategy), group in scoped.groupby(["universe", "strategy"]):
            for day in range(1, HORIZON + 1):
                values = pd.to_numeric(group[f"d{day}"], errors="coerce").dropna()
                if values.empty:
                    continue
                rows.append(
                    {
                        "scope": scope,
                        "universe": universe,
                        "strategy": strategy,
                        "day": day,
                        "events": len(values),
                        "tickers": group.loc[values.index, "ticker"].nunique(),
                        "signalDates": group.loc[values.index, "signalDate"].nunique(),
                        "mean": values.mean() * 100,
                        "median": values.median() * 100,
                        "winRate": values.gt(0).mean() * 100,
                        "p25": values.quantile(0.25) * 100,
                        "p75": values.quantile(0.75) * 100,
                        "mfe": pd.to_numeric(
                            group.loc[values.index, f"mfe{day}"], errors="coerce"
                        ).mean()
                        * 100,
                        "mae": pd.to_numeric(
                            group.loc[values.index, f"mae{day}"], errors="coerce"
                        ).mean()
                        * 100,
                    }
                )
    result = pd.DataFrame(rows)
    baseline = result[result["strategy"] == "20일신저가_기준선"][
        ["scope", "universe", "day", "mean"]
    ].rename(columns={"mean": "baselineMean"})
    result = result.merge(baseline, on=["scope", "universe", "day"], how="left")
    result["baselineExcess"] = result["mean"] - result["baselineMean"]
    return result


def target_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    scopes = [("all", trades), ("test", trades[trades["period"] == "test"])]
    for scope, scoped in scopes:
        keys = ["universe", "strategy", "target", "stop"]
        for values, group in scoped.groupby(keys, dropna=False):
            universe, strategy, target, stop = values
            returns = pd.to_numeric(group["return"], errors="coerce").dropna()
            eligible = group.loc[returns.index]
            wins = returns[returns > 0]
            losses = returns[returns < 0]
            hit_days = pd.to_numeric(
                eligible.loc[eligible["reason"] == "target", "days"],
                errors="coerce",
            )
            rows.append(
                {
                    "scope": scope,
                    "universe": universe,
                    "strategy": strategy,
                    "target": target,
                    "stop": stop,
                    "trades": len(returns),
                    "targetHitRate": eligible["reason"].eq("target").mean() * 100,
                    "medianHitDay": hit_days.median(),
                    "winRate": returns.gt(0).mean() * 100,
                    "mean": returns.mean() * 100,
                    "median": returns.median() * 100,
                    "profitFactor": (
                        wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf
                    ),
                    "averageWin": wins.mean() * 100,
                    "averageLoss": losses.mean() * 100,
                    "worst": returns.min() * 100,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    discovery_symbols = {ticker: ticker for ticker in sorted(set(UNIVERSE))}
    all_events, all_trades = collect(discovery_symbols, "전체유니버스")
    watch_events, watch_trades = collect(watchlist(), "관심종목57")
    events = pd.concat([all_events, watch_events], ignore_index=True)
    trades = pd.concat([all_trades, watch_trades], ignore_index=True)

    paths = path_summary(events)
    targets = target_summary(trades)
    events.to_pickle(os.path.join(OUT_DIR, "simple_bottom_events.pkl"))
    paths.to_csv(os.path.join(OUT_DIR, "simple_bottom_d1_d20.csv"), index=False)
    targets.to_csv(os.path.join(OUT_DIR, "simple_bottom_targets.csv"), index=False)

    checkpoints = paths[
        (paths["scope"] == "test")
        & (paths["universe"] == "전체유니버스")
        & (paths["day"].isin([1, 3, 5, 10, 20]))
    ]
    exits = targets[
        (targets["scope"] == "test")
        & (targets["universe"] == "전체유니버스")
        & (targets["strategy"] == "20일신저가_20일수익-30%")
        & targets["stop"].isna()
    ]
    print("[2023~2026 D+N]")
    print(
        checkpoints[
            [
                "strategy",
                "day",
                "events",
                "mean",
                "median",
                "winRate",
                "baselineExcess",
            ]
        ].round(2).to_string(index=False)
    )
    print("\n[2023~2026 목표 청산 · 무손절 · 미달 D+20]")
    print(
        exits[
            [
                "target",
                "trades",
                "targetHitRate",
                "medianHitDay",
                "winRate",
                "mean",
                "median",
                "profitFactor",
                "worst",
            ]
        ].round(2).to_string(index=False)
    )


if __name__ == "__main__":
    main()
