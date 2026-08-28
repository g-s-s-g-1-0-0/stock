"""Interest-watchlist event study for the recent capitulation-bottom pattern.

Primary output is the complete executable return path from D+1 through D+100.
D is the signal-confirmation close and entry is the next session open. Persistent
daily conditions are de-duplicated into episodes with a 20-session cooldown.
"""
from __future__ import annotations

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.indicators import add_indicators
from ma200_macd_golden import CACHE, FEE, OUT_DIR, build_qqq_state, dl

WATCHLIST_MAP = os.path.join(CACHE, "s4_watchlist_map.json")
HORIZON = 100
COOLDOWN = 20
CHECKPOINTS = (1, 3, 5, 10, 20, 40, 60, 100)


def load_watchlist() -> dict[str, str]:
    with open(WATCHLIST_MAP, encoding="utf-8") as f:
        return json.load(f)


def market_frame() -> pd.DataFrame:
    q = add_indicators(dl("QQQ"))
    state = build_qqq_state()
    q_fields = q[["RSI", "MACD_Hist", "MACD_Hist_D1"]].rename(
        columns={
            "RSI": "qqqRSI",
            "MACD_Hist": "qqqMACDHist",
            "MACD_Hist_D1": "qqqMACDHistD1",
        }
    )
    out = state.join(q_fields, how="left")
    out["qqqRsiMin3"] = out["qqqRSI"].rolling(3).min()
    out["qqqRet20"] = q["Close"].pct_change(20) * 100
    vix = dl("^VIX")
    if vix is not None:
        out["vix"] = vix["Close"].reindex(out.index, method="ffill")
        out["vixMax3"] = out["vix"].rolling(3).max()
    return out


def stock_frame(raw: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(raw).join(market, how="inner")
    close = d["Close"]
    d["MA20"] = close.rolling(20).mean()
    d["ma20Slope5"] = d["MA20"] / d["MA20"].shift(5) - 1
    d["dd252"] = close / close.rolling(252).max() - 1
    d["ret20"] = close.pct_change(20) * 100
    d["rs20"] = d["ret20"] - d["qqqRet20"]
    d["below200"] = close < d["MA200"]
    d["diBear"] = d["MinusDI"] > d["PlusDI"]
    d["golden"] = (d["MACD_Hist_D1"] <= 0) & (d["MACD_Hist"] > 0)
    return d.dropna(
        subset=[
            "premium",
            "qqqRsiMin3",
            "MA200",
            "MA20",
            "ma20Slope5",
            "dd252",
            "rs20",
            "RSI",
            "CCI",
            "ADX",
            "PlusDI",
            "MinusDI",
        ]
    )


def masks(d: pd.DataFrame) -> dict[str, pd.Series]:
    market_setup = (
        d["premium"].between(0, 9, inclusive="both")
        & (d["regime"] == "정상장")
        & (d["qqqRsiMin3"] <= 40)
    )
    stock_setup = (
        (d["RSI"] <= 32)
        & d["diBear"]
        & (d["ADX"] >= 25)
        & (d["rs20"] < 0)
        & (d["ma20Slope5"] < 0)
    )
    core = market_setup & stock_setup
    recent_core = core.shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool)
    return {
        "시장조건만": market_setup,
        "종목조건만": stock_setup,
        "공통핵심": core,
        "공통핵심+MA200아래": core & d["below200"],
        "공통핵심+52주낙폭45": core & (d["dd252"] <= -0.45),
        "공통핵심+MA200+52주낙폭45": core & d["below200"] & (d["dd252"] <= -0.45),
        "공통핵심+CCI-100": core & (d["CCI"] <= -100),
        "공통핵심후5일내골든": d["golden"] & recent_core,
    }


def episode_indices(mask: pd.Series) -> list[int]:
    values = mask.fillna(False).to_numpy(dtype=bool)
    starts = np.flatnonzero(values & ~np.r_[False, values[:-1]])
    selected: list[int] = []
    last = -COOLDOWN - 1
    for index in starts:
        if index - last > COOLDOWN:
            selected.append(int(index))
            last = int(index)
    return selected


def event_record(
    ticker: str,
    symbol: str,
    variant: str,
    d: pd.DataFrame,
    index: int,
) -> dict:
    entry_index = index + 1
    entry = d["Open"].iloc[entry_index] * (1 + FEE)
    record: dict[str, object] = {
        "ticker": ticker,
        "symbol": symbol,
        "variant": variant,
        "signalDate": d.index[index],
        "entryDate": d.index[entry_index],
        "entry": entry,
        "availableDays": min(HORIZON, len(d) - entry_index),
        "qqqPremium": d["premium"].iloc[index],
        "qqqRegime": d["regime"].iloc[index],
        "qqqRsi": d["qqqRSI"].iloc[index],
        "qqqRsiMin3": d["qqqRsiMin3"].iloc[index],
        "vix": d["vix"].iloc[index] if "vix" in d else np.nan,
        "stockRsi": d["RSI"].iloc[index],
        "cci": d["CCI"].iloc[index],
        "adx": d["ADX"].iloc[index],
        "diSpread": d["PlusDI"].iloc[index] - d["MinusDI"].iloc[index],
        "distMA200": (d["Close"].iloc[index] / d["MA200"].iloc[index] - 1) * 100,
        "dd252": d["dd252"].iloc[index] * 100,
        "rs20": d["rs20"].iloc[index],
    }
    available = int(record["availableDays"])
    for day in range(1, HORIZON + 1):
        if day <= available:
            exit_price = d["Close"].iloc[index + day] * (1 - FEE)
            record[f"d{day}"] = (exit_price / entry - 1) * 100
        else:
            record[f"d{day}"] = np.nan

    highs = d["High"].iloc[entry_index : entry_index + available].to_numpy()
    lows = d["Low"].iloc[entry_index : entry_index + available].to_numpy()
    for horizon in (20, 60, 100):
        length = min(horizon, available)
        if length == 0:
            record[f"mfe{horizon}"] = np.nan
            record[f"mae{horizon}"] = np.nan
            continue
        record[f"mfe{horizon}"] = (np.nanmax(highs[:length]) / entry - 1) * 100
        record[f"mae{horizon}"] = (np.nanmin(lows[:length]) / entry - 1) * 100
    for target in (10, 15):
        hits = np.flatnonzero(highs >= entry * (1 + target / 100))
        record[f"hit{target}Day"] = int(hits[0] + 1) if len(hits) else np.nan
    return record


def build_events() -> pd.DataFrame:
    market = market_frame()
    records: list[dict] = []
    for ticker, symbol in load_watchlist().items():
        raw = dl(symbol)
        if raw is None or len(raw) < 400:
            continue
        d = stock_frame(raw, market)
        if len(d) < HORIZON + 2:
            continue
        for variant, mask in masks(d).items():
            for index in episode_indices(mask):
                if index + 1 >= len(d):
                    continue
                records.append(event_record(ticker, symbol, variant, d, index))
    return pd.DataFrame(records)


def benchmark_returns(signal_dates: pd.Index) -> tuple[dict[int, dict], dict[int, dict]]:
    dates = set(pd.to_datetime(signal_dates))
    sums = {day: {} for day in range(1, HORIZON + 1)}
    counts = {day: {} for day in range(1, HORIZON + 1)}
    for symbol in load_watchlist().values():
        raw = dl(symbol)
        if raw is None or len(raw) < 2:
            continue
        positions = {date: index for index, date in enumerate(raw.index)}
        opens = raw["Open"].to_numpy()
        closes = raw["Close"].to_numpy()
        for date in dates:
            index = positions.get(date)
            if index is None or index + 1 >= len(raw):
                continue
            entry = opens[index + 1] * (1 + FEE)
            available = min(HORIZON, len(raw) - index - 1)
            for day in range(1, available + 1):
                value = (closes[index + day] * (1 - FEE) / entry - 1) * 100
                sums[day][date] = sums[day].get(date, 0.0) + value
                counts[day][date] = counts[day].get(date, 0) + 1
    watchlist = {
        day: {date: value / counts[day][date] for date, value in sums[day].items()}
        for day in range(1, HORIZON + 1)
    }

    qqq_raw = dl("QQQ")
    qqq_positions = {date: index for index, date in enumerate(qqq_raw.index)}
    qqq_open = qqq_raw["Open"].to_numpy()
    qqq_close = qqq_raw["Close"].to_numpy()
    qqq = {day: {} for day in range(1, HORIZON + 1)}
    for date in dates:
        index = qqq_positions.get(date)
        if index is None or index + 1 >= len(qqq_raw):
            continue
        entry = qqq_open[index + 1] * (1 + FEE)
        available = min(HORIZON, len(qqq_raw) - index - 1)
        for day in range(1, available + 1):
            qqq[day][date] = (qqq_close[index + day] * (1 - FEE) / entry - 1) * 100
    return watchlist, qqq


def attach_benchmarks(events: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    watchlist, qqq = benchmark_returns(result["signalDate"].unique())
    for day in range(1, HORIZON + 1):
        watch_values = result["signalDate"].map(watchlist[day])
        qqq_values = result["signalDate"].map(qqq[day])
        result[f"watchEx{day}"] = result[f"d{day}"] - watch_values
        result[f"qqqEx{day}"] = result[f"d{day}"] - qqq_values
    return result


def path_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, group in events.groupby("variant"):
        for day in range(1, HORIZON + 1):
            column = f"d{day}"
            sample = group.dropna(subset=[column])
            if sample.empty:
                continue
            values = sample[column]
            date_equal = sample.groupby("signalDate")[column].mean()
            watch_excess = sample[f"watchEx{day}"].dropna()
            qqq_excess = sample[f"qqqEx{day}"].dropna()
            rows.append(
                {
                    "variant": variant,
                    "day": day,
                    "events": len(sample),
                    "signalDates": sample["signalDate"].nunique(),
                    "tickers": sample["ticker"].nunique(),
                    "mean": values.mean(),
                    "median": values.median(),
                    "winRate": (values > 0).mean() * 100,
                    "p25": values.quantile(0.25),
                    "p75": values.quantile(0.75),
                    "dateEqualMean": date_equal.mean(),
                    "watchlistExcessMean": watch_excess.mean(),
                    "watchlistExcessMedian": watch_excess.median(),
                    "watchlistExcessWin": (watch_excess > 0).mean() * 100,
                    "qqqExcessMean": qqq_excess.mean(),
                    "qqqExcessMedian": qqq_excess.median(),
                }
            )
    return pd.DataFrame(rows)


def target_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, group in events.groupby("variant"):
        record: dict[str, object] = {
            "variant": variant,
            "events": len(group),
            "tickers": group["ticker"].nunique(),
            "signalDates": group["signalDate"].nunique(),
            "firstDate": group["signalDate"].min(),
            "lastDate": group["signalDate"].max(),
        }
        for horizon in (20, 60, 100):
            eligible = group[group["availableDays"] >= horizon]
            record[f"eligible{horizon}"] = len(eligible)
            record[f"mean{horizon}"] = eligible[f"d{horizon}"].mean()
            record[f"median{horizon}"] = eligible[f"d{horizon}"].median()
            record[f"win{horizon}"] = (eligible[f"d{horizon}"] > 0).mean() * 100
            record[f"mfe{horizon}"] = eligible[f"mfe{horizon}"].mean()
            record[f"mae{horizon}"] = eligible[f"mae{horizon}"].mean()
            for target in (10, 15):
                hit = eligible[f"hit{target}Day"].le(horizon)
                record[f"hit{target}By{horizon}"] = hit.mean() * 100
                days = eligible.loc[hit, f"hit{target}Day"]
                record[f"hit{target}MedianDay{horizon}"] = days.median()
        rows.append(record)
    return pd.DataFrame(rows)


def period_summary(events: pd.DataFrame) -> pd.DataFrame:
    bins = [
        (pd.Timestamp.min, pd.Timestamp("2015-12-31"), "~2015"),
        (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31"), "2016~2020"),
        (pd.Timestamp("2021-01-01"), pd.Timestamp("2023-12-31"), "2021~2023"),
        (pd.Timestamp("2024-01-01"), pd.Timestamp.max, "2024~2026"),
    ]
    rows = []
    for variant, group in events.groupby("variant"):
        for start, end, label in bins:
            sample = group[group["signalDate"].between(start, end)]
            if sample.empty:
                continue
            row = {
                "variant": variant,
                "period": label,
                "events": len(sample),
                "tickers": sample["ticker"].nunique(),
                "signalDates": sample["signalDate"].nunique(),
            }
            for day in (20, 60, 100):
                eligible = sample.dropna(subset=[f"d{day}"])
                row[f"mean{day}"] = eligible[f"d{day}"].mean()
                row[f"median{day}"] = eligible[f"d{day}"].median()
                row[f"win{day}"] = (eligible[f"d{day}"] > 0).mean() * 100
                row[f"watchEx{day}"] = eligible[f"watchEx{day}"].mean()
                row[f"qqqEx{day}"] = eligible[f"qqqEx{day}"].mean()
                row[f"n{day}"] = len(eligible)
            rows.append(row)
    return pd.DataFrame(rows)


def ticker_summary(events: pd.DataFrame) -> pd.DataFrame:
    selected = events[events["variant"].isin(["공통핵심", "공통핵심후5일내골든"])]
    rows = []
    for (variant, ticker), group in selected.groupby(["variant", "ticker"]):
        row = {
            "variant": variant,
            "ticker": ticker,
            "events": len(group),
            "firstDate": group["signalDate"].min(),
            "lastDate": group["signalDate"].max(),
        }
        for day in (20, 60, 100):
            eligible = group.dropna(subset=[f"d{day}"])
            row[f"n{day}"] = len(eligible)
            row[f"mean{day}"] = eligible[f"d{day}"].mean()
            row[f"median{day}"] = eligible[f"d{day}"].median()
            row[f"win{day}"] = (eligible[f"d{day}"] > 0).mean() * 100
            row[f"watchEx{day}"] = eligible[f"watchEx{day}"].mean()
        rows.append(row)
    return pd.DataFrame(rows)


def significance_summary(events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for variant, group in events.groupby("variant"):
        for day in (5, 20, 60, 100):
            column = f"watchEx{day}"
            sample = group.dropna(subset=[column])
            for cluster in ("signalDate", "ticker"):
                clustered = sample.groupby(cluster)[column].mean().to_numpy()
                if len(clustered) < 10:
                    continue
                boot = np.array(
                    [
                        rng.choice(clustered, len(clustered), replace=True).mean()
                        for _ in range(5000)
                    ]
                )
                low, high = np.percentile(boot, [2.5, 97.5])
                rows.append(
                    {
                        "variant": variant,
                        "day": day,
                        "cluster": cluster,
                        "clusters": len(clustered),
                        "watchlistExcess": clustered.mean(),
                        "ciLow": low,
                        "ciHigh": high,
                        "significant": low > 0 or high < 0,
                    }
                )
    return pd.DataFrame(rows)


def print_checkpoints(path: pd.DataFrame) -> None:
    table = path[path["day"].isin(CHECKPOINTS)].copy()
    columns = [
        "variant",
        "day",
        "events",
        "tickers",
        "mean",
        "median",
        "winRate",
        "watchlistExcessMean",
        "qqqExcessMean",
    ]
    print(table[columns].round(2).to_string(index=False))


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    events = attach_benchmarks(build_events())
    path = path_summary(events)
    targets = target_summary(events)
    periods = period_summary(events)
    tickers = ticker_summary(events)
    significance = significance_summary(events)

    events.to_pickle(os.path.join(OUT_DIR, "common_bottom_events.pkl"))
    path.to_csv(os.path.join(OUT_DIR, "common_bottom_d1_d100.csv"), index=False)
    targets.to_csv(os.path.join(OUT_DIR, "common_bottom_targets.csv"), index=False)
    periods.to_csv(os.path.join(OUT_DIR, "common_bottom_periods.csv"), index=False)
    tickers.to_csv(os.path.join(OUT_DIR, "common_bottom_tickers.csv"), index=False)
    significance.to_csv(
        os.path.join(OUT_DIR, "common_bottom_significance.csv"), index=False
    )

    print(
        f"events={len(events):,} variants={events['variant'].nunique()} "
        f"tickers={events['ticker'].nunique()} "
        f"period={events['signalDate'].min().date()}~{events['signalDate'].max().date()}"
    )
    print("\n[D+1~D+100 checkpoints]")
    print_checkpoints(path)
    print("\n[Targets / MFE / MAE]")
    print(targets.round(2).to_string(index=False))
    print("\n[Period stability]")
    print(periods.round(2).to_string(index=False))
    print("\n[Date-clustered watchlist excess confidence intervals]")
    print(significance.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
