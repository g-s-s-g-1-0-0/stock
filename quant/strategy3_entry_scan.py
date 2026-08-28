"""Is Strategy 3's edge in the entry, and was the earlier benchmark unfair?

Two separate questions, in order.

1. The exit study measured excess against a daily-rebalanced equal-weight index
   of point-in-time members. That basket earns a rebalancing premium a single
   held name cannot, so a one-name trade is structurally behind it. The control
   here is a placebo instead: on the same date, for the same number of
   sessions, buy a random eligible name. Same construction on both sides, so
   whatever the entry rule knows has to show up as a gap.

2. Given the placebo baseline, rank candidate entry filters by the forward
   excess they add, and keep only the ones that survive an era split and a
   train/test cut. A filter that only works after the fact is a filter fitted
   to the sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, legacy_run, sp500_data, strategy3_exit

HORIZONS = (10, 20)
PLACEBO_DRAWS = 5
SEED = 20260817

FEATURES = {
    "rsi14": "RSI(14)",
    "legPctBLow": "저가 %B",
    "atrPct": "ATR%",
    "bbWidthPct": "BB폭 백분위",
    "adx14": "ADX(14)",
    "volRatio20": "거래량비(20)",
    "legMa200Dist": "MA200 이격%",
    "distHigh52": "52주고점 대비",
    "dd60": "60일 고점 대비",
    "mom126": "6개월 모멘텀",
    "lowerTail": "아랫꼬리 비율",
    "qqqPremium": "QQQ 200일 이격",
    "closeVsMa20": "MA20 대비",
    "ma200Slope20": "MA200 20일 기울기",
    "macdTurn": "MACD 히스토그램 반등",
}


def _forward_net(panel: pd.DataFrame, horizon: int) -> pd.Series:
    """Next open to the close `horizon` sessions later, net of fees and slip."""
    entry = panel["Open"].shift(-1)
    exit_ = panel["Close"].shift(-(1 + horizon))
    fee = config.FEE_BPS / 10_000.0
    slip = panel["atrPct"].map(
        lambda a: max(config.SLIPPAGE_MIN_BPS, config.SLIPPAGE_ATR_FRACTION * a * 10_000.0)
        / 10_000.0
        if np.isfinite(a)
        else np.nan
    )
    gross = exit_ * (1 - slip) / (entry * (1 + slip)) - 1.0
    return gross - 2 * fee


def build_signal_frame(
    panels: dict[str, pd.DataFrame], state: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """One row per Strategy 3 signal, carrying its features and forward returns."""
    entries, _ = strategy3_exit.build_signals(panels, state)

    for panel in panels.values():
        panel["closeVsMa20"] = panel["Close"] / panel["ma20"] - 1.0
        panel["ma200Slope20"] = panel["ma200Slope"] / panel["Close"]
        panel["macdTurn"] = (
            panel["legMacdHist"].gt(panel["legMacdHistD1"])
            & panel["legMacdHistD1"].le(panel["legMacdHistD2"])
        ).astype(float)
        for horizon in HORIZONS:
            panel[f"fwd{horizon}"] = _forward_net(panel, horizon)

    rows = []
    for ticker, entry in entries.items():
        mask = entry.to_numpy(bool) & panels[ticker]["eligible"].to_numpy(bool)
        if not mask.any():
            continue
        panel = panels[ticker]
        frame = pd.DataFrame(
            {
                "ticker": ticker,
                "date": panel.index[mask],
                **{key: panel[key].to_numpy()[mask] for key in FEATURES},
                **{f"fwd{h}": panel[f"fwd{h}"].to_numpy()[mask] for h in HORIZONS},
            }
        )
        rows.append(frame)

    signals = pd.concat(rows, ignore_index=True).sort_values("date").reset_index(drop=True)
    signals["year"] = signals["date"].dt.year
    return signals, panels


def placebo(
    signals: pd.DataFrame, panels: dict[str, pd.DataFrame], draws: int = PLACEBO_DRAWS
) -> pd.DataFrame:
    """Random eligible name, same date, same horizon. The honest baseline.

    Drawn per signal date rather than per signal so the date mix matches
    exactly: Strategy 3 fires in clusters, and a control that ignored the
    clustering would be comparing different calendars.
    """
    rng = np.random.default_rng(SEED)
    pool: dict[pd.Timestamp, list[str]] = {}
    for ticker, panel in panels.items():
        eligible = panel.index[panel["eligible"].to_numpy(bool)]
        for stamp in eligible:
            pool.setdefault(stamp, []).append(ticker)

    lookup = {
        (ticker, stamp): idx
        for ticker, panel in panels.items()
        for idx, stamp in enumerate(panel.index)
    }

    out = []
    for stamp, group in signals.groupby("date"):
        names = pool.get(stamp)
        if not names:
            continue
        picks = rng.choice(names, size=len(group) * draws, replace=True)
        for ticker in picks:
            idx = lookup[(ticker, stamp)]
            panel = panels[ticker]
            out.append(
                {
                    "date": stamp,
                    "ticker": ticker,
                    **{f"fwd{h}": panel[f"fwd{h}"].to_numpy()[idx] for h in HORIZONS},
                }
            )
    frame = pd.DataFrame(out)
    frame["year"] = frame["date"].dt.year
    return frame


def _stats(values: pd.Series) -> dict:
    clean = values.dropna()
    return {
        "n": len(clean),
        "mean%": clean.mean() * 100,
        "median%": clean.median() * 100,
        "win%": clean.gt(0).mean() * 100,
        "std%": clean.std() * 100,
    }


def head_to_head(signals: pd.DataFrame, control: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in HORIZONS:
        column = f"fwd{horizon}"
        signal_stats = _stats(signals[column])
        control_stats = _stats(control[column])
        gap = signal_stats["mean%"] - control_stats["mean%"]
        pooled = np.sqrt(
            signal_stats["std%"] ** 2 / max(signal_stats["n"], 1)
            + control_stats["std%"] ** 2 / max(control_stats["n"], 1)
        )
        rows.append(
            {
                "horizon": horizon,
                "signal n": signal_stats["n"],
                "signal mean%": signal_stats["mean%"],
                "signal win%": signal_stats["win%"],
                "placebo n": control_stats["n"],
                "placebo mean%": control_stats["mean%"],
                "placebo win%": control_stats["win%"],
                "gap%p": gap,
                "t": gap / pooled if pooled > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def by_year(signals: pd.DataFrame, control: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    column = f"fwd{horizon}"
    signal_year = signals.groupby("year")[column].agg(["size", "mean"])
    control_year = control.groupby("year")[column].mean()
    table = pd.DataFrame(
        {
            "signals": signal_year["size"],
            "signal%": signal_year["mean"] * 100,
            "placebo%": control_year * 100,
        }
    )
    table["gap%p"] = table["signal%"] - table["placebo%"]
    return table


def feature_buckets(
    signals: pd.DataFrame, control_mean: dict[int, float], horizon: int = 20, bins: int = 5
) -> pd.DataFrame:
    """Quintile the signal population on each feature and read the gap.

    The bar is the placebo mean, not zero: a bucket that beats zero in a rising
    market has shown nothing.
    """
    column, rows = f"fwd{horizon}", []
    base = control_mean[horizon]
    for key, label in FEATURES.items():
        series = signals[key]
        if series.nunique(dropna=True) < bins:
            groups = series.fillna(-1).astype(float)
            buckets = groups.rank(method="dense").astype(int)
        else:
            buckets = pd.qcut(series.rank(method="first"), bins, labels=False, duplicates="drop")
        for bucket, group in signals.groupby(buckets):
            window = group[column].dropna()
            if len(window) < 200:
                continue
            rows.append(
                {
                    "feature": label,
                    "key": key,
                    "bucket": int(bucket),
                    "lo": series[group.index].min(),
                    "hi": series[group.index].max(),
                    "n": len(window),
                    "mean%": window.mean() * 100,
                    "gap%p": window.mean() * 100 - base,
                    "win%": window.gt(0).mean() * 100,
                }
            )
    return pd.DataFrame(rows)


def era_split(
    signals: pd.DataFrame, mask: pd.Series, control: pd.DataFrame, horizon: int = 20
) -> pd.DataFrame:
    """Does a candidate filter hold in every era, or in one lucky decade?"""
    column, rows = f"fwd{horizon}", []
    for label, start, end in config.ERAS:
        window = (signals["date"] >= start) & (signals["date"] <= end)
        kept = signals[window & mask][column].dropna()
        allsig = signals[window][column].dropna()
        base = control[(control["date"] >= start) & (control["date"] <= end)][column].dropna()
        if kept.empty or base.empty:
            continue
        rows.append(
            {
                "era": label,
                "kept n": len(kept),
                "kept%": kept.mean() * 100,
                "all signals%": allsig.mean() * 100,
                "placebo%": base.mean() * 100,
                "gap vs placebo%p": kept.mean() * 100 - base.mean() * 100,
            }
        )
    return pd.DataFrame(rows)


def matched_placebo(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    key: str,
    threshold: float,
    draws: int = PLACEBO_DRAWS,
) -> pd.DataFrame:
    """Placebo drawn only from names that also pass the filter under test.

    A filter like "MA200 rising fast" selects trending, higher-beta names, and
    those earn more over the next month whether or not anything washed out. The
    matched control removes that tilt: if the gap survives here, the washout
    rule is adding something on top of the trend it selects.
    """
    rng = np.random.default_rng(SEED + 1)
    wide_feature = pd.DataFrame({t: p[key] for t, p in panels.items()})
    wide_eligible = pd.DataFrame({t: p["eligible"] for t, p in panels.items()}).fillna(False)
    forward = {h: pd.DataFrame({t: p[f"fwd{h}"] for t, p in panels.items()}) for h in HORIZONS}

    pool_mask = wide_eligible.astype(bool) & wide_feature.ge(threshold)
    out = []
    for stamp, group in signals.groupby("date"):
        if stamp not in pool_mask.index:
            continue
        names = pool_mask.columns[pool_mask.loc[stamp].to_numpy(bool)]
        if not len(names):
            continue
        picks = rng.choice(names, size=len(group) * draws, replace=True)
        for ticker in picks:
            out.append(
                {
                    "date": stamp,
                    "ticker": ticker,
                    **{f"fwd{h}": forward[h].at[stamp, ticker] for h in HORIZONS},
                }
            )
    frame = pd.DataFrame(out)
    if not frame.empty:
        frame["year"] = frame["date"].dt.year
    return frame


def validate_filter(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    control: pd.DataFrame,
    key: str,
    label: str,
    train_end: str = "2012-12-31",
    horizon: int = 20,
) -> None:
    """Threshold from the train half only, then read the untouched test half."""
    column = f"fwd{horizon}"
    train = signals[signals["date"] <= train_end]
    threshold = train[key].quantile(0.8)
    mask = signals[key].ge(threshold)
    print(f"\n--- {label}: 상위 20% 임계값 {threshold:.4f} (1999-2012 구간에서만 산출) ---")

    matched = matched_placebo(signals, panels, key, threshold)
    for name, window in (("train 1999-2012", signals["date"] <= train_end),
                         ("test 2013-2026", signals["date"] > train_end)):
        kept = signals[window & mask][column].dropna()
        plain = control[control["date"].le(train_end) == (name.startswith("train"))][column].dropna()
        tuned = matched[matched["date"].le(train_end) == (name.startswith("train"))][column].dropna()
        print(
            f"  {name:<16} n={len(kept):>6}  signal {kept.mean() * 100:6.2f}%  "
            f"random placebo {plain.mean() * 100:6.2f}%  matched placebo {tuned.mean() * 100:6.2f}%  "
            f"gap(matched) {kept.mean() * 100 - tuned.mean() * 100:+5.2f}%p"
        )

    print("\n  era split vs random placebo:")
    print(era_split(signals, mask, control).round(2).to_string(index=False))
    print("\n  era split vs matched placebo:")
    print(era_split(signals, mask, matched).round(2).to_string(index=False))


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    signals, panels = build_signal_frame(panels, state)
    print(f"strategy 3 signals: {len(signals)} rows, {signals['ticker'].nunique()} names")

    control = placebo(signals, panels)
    print(f"placebo draws: {len(control)}")

    print("\n" + "=" * 92)
    print("1. Strategy 3 signal vs random eligible name, same date and horizon")
    print("=" * 92)
    print(head_to_head(signals, control).round(3).to_string(index=False))

    print("\n--- by year (20 sessions) ---")
    print(by_year(signals, control).round(2).to_string())

    control_mean = {h: control[f"fwd{h}"].dropna().mean() * 100 for h in HORIZONS}
    print("\n" + "=" * 92)
    print("2. Entry filter scan, quintiles of the signal population (20 sessions)")
    print(f"   bar to beat: placebo {control_mean[20]:.2f}%")
    print("=" * 92)
    buckets = feature_buckets(signals, control_mean)
    spread = (
        buckets.groupby(["feature", "key"])["gap%p"]
        .agg(best="max", worst="min")
        .assign(spread=lambda f: f["best"] - f["worst"])
        .sort_values("spread", ascending=False)
    )
    print(spread.round(2).to_string())
    print("\n--- top 3 features, bucket detail ---")
    for key in spread.reset_index()["key"].head(3):
        print(buckets[buckets["key"] == key].round(3).to_string(index=False))

    print("\n" + "=" * 92)
    print("3. Top filters: train/test cut and a filter-matched placebo")
    print("=" * 92)
    for key in spread.reset_index()["key"].head(3):
        validate_filter(signals, panels, control, key, FEATURES[key])

    signals.to_csv(f"{config.__file__.rsplit('/', 1)[0]}/out/s3_signals.csv", index=False)
    control.to_csv(f"{config.__file__.rsplit('/', 1)[0]}/out/s3_placebo.csv", index=False)
    buckets.to_csv(f"{config.__file__.rsplit('/', 1)[0]}/out/s3_feature_buckets.csv", index=False)
    print("\nsaved: quant/out/s3_signals.csv, s3_placebo.csv, s3_feature_buckets.csv")


if __name__ == "__main__":
    main()
