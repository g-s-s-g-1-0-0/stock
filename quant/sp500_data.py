"""Backtest panels built on point-in-time S&P 500 membership.

Same features and same engine as the watchlist run; only the universe changes.
A name is tradeable on a date only if it was an index member on that date, and
the benchmark is the equal-weight return of that day's members. Both sides move
together, so excess return no longer rewards a universe picked in hindsight.
"""

from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

from quant import config, data, engine, features, sp500

STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sp500_cache"
)


def load_bars(min_bars: int = config.MIN_BARS) -> dict[str, pd.DataFrame]:
    bars: dict[str, pd.DataFrame] = {}
    for path in sorted(glob.glob(os.path.join(STORE, "*.pkl"))):
        ticker = os.path.basename(path)[:-4]
        if ticker.startswith("_"):
            continue
        frame = pd.read_pickle(path)
        if len(frame) >= min_bars:
            bars[ticker] = frame
    return bars


def _member_mask(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Wide boolean frame of index membership on the union trading calendar."""
    calendar = pd.DatetimeIndex(sorted(set().union(*(f.index for f in bars.values()))))
    daily = sp500.daily_membership(calendar)
    missing = [t for t in bars if t not in daily.columns]
    for ticker in missing:
        daily[ticker] = False
    return daily[sorted(bars)].astype(bool)


def build(min_bars: int = config.MIN_BARS) -> tuple[dict[str, pd.DataFrame], data.UniverseGrowth]:
    bars = load_bars(min_bars)
    print(f"loaded {len(bars)} S&P 500 ever-members with >= {min_bars} bars")

    members = _member_mask(bars)
    panels = features.build_panels(bars)

    for ticker, panel in panels.items():
        gate = members[ticker].reindex(panel.index).fillna(False)
        panel["eligible"] = panel["eligible"].astype(bool) & gate.to_numpy()
        panel["member"] = gate.to_numpy()

    returns = pd.DataFrame(
        {t: p["Close"].pct_change().where(p["member"]) for t, p in panels.items()}
    )
    benchmark = returns.mean(axis=1, skipna=True).rename("universeRet")
    counts = returns.notna().sum(axis=1)
    print(
        f"benchmark breadth: median {int(counts.median())} names/day, "
        f"min {int(counts[counts > 0].min())}"
    )

    panels = engine.attach_context(panels, features.market_features())
    return panels, data.UniverseGrowth(benchmark)


def eligible_counts(panels: dict[str, pd.DataFrame]) -> pd.Series:
    frame = pd.DataFrame({t: p["eligible"] for t, p in panels.items()})
    return frame.sum(axis=1)


def main() -> None:
    panels, _ = build()
    counts = eligible_counts(panels)
    print("\n--- tradeable names at year start ---")
    for year in range(2000, 2027):
        window = counts.loc[counts.index <= f"{year}-01-01"]
        if len(window):
            print(f"  {year}: {int(window.iloc[-1])}")


if __name__ == "__main__":
    main()
