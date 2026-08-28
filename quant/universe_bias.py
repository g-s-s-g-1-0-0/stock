"""Does SW-1's edge survive when the universe is not a list of today's winners?

The `.bt_cache` universe is a watchlist assembled in 2026, so its 2023-2026
cross-section is populated by names that earned a place on that list by winning
during exactly that window. "Buy the strongest names" is mechanically rewarded
inside a pool of already-known winners, which would show up as excess return
concentrated at the end of the sample -- and that is what we observe.

This module re-runs SW-1 on listing cohorts. Restricting to tickers that were
already trading long before the test window removes the recency of the
selection, though not the selection itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, data, engine, features, strategies


def _cohort(bars: dict[str, pd.DataFrame], listed_by: str) -> dict[str, pd.DataFrame]:
    cutoff = pd.Timestamp(listed_by)
    return {t: f for t, f in bars.items() if f.index.min() <= cutoff}


def run_cohort(listed_by: str, hold: int = 40) -> pd.DataFrame:
    """Backtest SW-1 with both picks and benchmark drawn from one listing cohort."""
    bars = _cohort(data.load_bars(), listed_by)
    growth = data.UniverseGrowth(data.universe_mean_return(bars))
    panels = engine.attach_context(features.build_panels(bars), features.market_features())

    bar = config.Barriers(4.0, 2.0, hold, "swing")
    ledger = engine.build_ledger(
        panels, strategies.swing_momentum(panels), bar, "SW1_momentum",
        entry_mode="nextOpen", exit_policy="time", universe_growth=growth,
    )
    trades = ledger[
        ledger["filled"].astype("boolean").fillna(False)
        & ~ledger["censored"].astype("boolean").fillna(False)
        & ledger["dedupKept"].astype("boolean").fillna(False)
    ].copy()
    trades["cohort"] = listed_by
    trades["cohortSize"] = len(bars)
    return trades


def era_table(trades: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(trades["signalDate"])
    rows = {}
    for label, start, end in config.ERAS:
        window = trades[(dates >= start) & (dates <= end)]
        rows[label] = {
            "trades": len(window),
            "realized%": window["retNet"].mean() * 100 if len(window) else np.nan,
            "excess%": window["excessRet"].mean() * 100 if len(window) else np.nan,
        }
    return pd.DataFrame(rows).T


def main() -> None:
    cohorts = ["2026-01-01", "2013-01-01", "2008-01-01", "2003-01-01"]
    summary = {}
    for listed_by in cohorts:
        trades = run_cohort(listed_by)
        size = int(trades["cohortSize"].iloc[0]) if len(trades) else 0
        label = f"listed by {listed_by[:4]} (n={size})"
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
        print(era_table(trades).round(2).to_string())
        summary[label] = {
            "trades": len(trades),
            "realized%": trades["retNet"].mean() * 100,
            "excess%": trades["excessRet"].mean() * 100,
        }

    print(f"\n{'=' * 70}\nfull sample by cohort\n{'=' * 70}")
    print(pd.DataFrame(summary).T.round(2).to_string())


if __name__ == "__main__":
    main()
