"""Validation that decides whether a result is real or fitted.

Three checks, in order of how often they kill a strategy:
parameter stability, chronological walk-forward, and a portfolio simulation
that applies the position limits real capital forces on you.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, data, engine, metrics, strategies
from quant.config import Barriers


def parameter_sweep(
    panels: dict[str, pd.DataFrame],
    growth: data.UniverseGrowth,
    exit_policy: str = "time",
) -> pd.DataFrame:
    """Vary SW-1 thresholds around the chosen values.

    A result that only exists at one setting is a fit, not an edge, so the
    neighbourhood matters more than the best cell.
    """
    rows = []
    for rank_min in (0.80, 0.85, 0.90, 0.95, 0.98):
        for max_hold in (20, 40, 60, 80):
            signals = strategies.swing_momentum(panels, rank_min=rank_min)
            bar = Barriers(4.0, 2.0, max_hold, "swing")
            ledger = engine.build_ledger(
                panels, signals, bar, "SW1_sweep",
                entry_mode="nextOpen", exit_policy=exit_policy, universe_growth=growth,
            )
            summary = metrics.headline(ledger)
            rows.append(
                {
                    "rankMin": rank_min,
                    "maxHold": max_hold,
                    "trades": summary.get("trades", 0),
                    "realizedMean%": summary.get("realizedMean%", np.nan),
                    "realizedMedian%": summary.get("realizedMedian%", np.nan),
                    "excessMean%": summary.get("excessMean%", np.nan),
                    # Longer holds mechanically accumulate more excess, so the
                    # per-20-day figure is what makes settings comparable.
                    "excessPer20d%": summary.get("excessMean%", np.nan) * 20 / max_hold,
                    "winRate%": summary.get("winRate%", np.nan),
                }
            )
    return pd.DataFrame(rows)


def regime_gate_test(
    panels: dict[str, pd.DataFrame], growth: data.UniverseGrowth
) -> pd.DataFrame:
    """Does the QQQ regime gate actually contribute, or is it decoration?"""
    rows = {}
    for label, require in (("withRegimeGate", True), ("noRegimeGate", False)):
        signals = strategies.swing_momentum(panels, require_regime=require)
        ledger = engine.build_ledger(
            panels, signals, config.SWING, "SW1_gate",
            entry_mode="nextOpen", exit_policy="time", universe_growth=growth,
        )
        summary = metrics.headline(ledger)
        rows[label] = summary[
            [
                column
                for column in ("trades", "realizedMean%", "realizedMedian%", "winRate%",
                               "universeMean%", "excessMean%", "realizedP10%", "worst%")
                if column in summary.index
            ]
        ]
    return pd.DataFrame(rows).T


def walk_forward(ledger: pd.DataFrame, train_years: int = 3) -> pd.DataFrame:
    """Rolling out-of-sample: each year evaluated after the preceding window.

    The engine has no fitted parameters inside a run, so this measures
    year-to-year persistence rather than in-sample optimism.
    """
    trades = ledger[
        ledger["filled"].fillna(False)
        & ~ledger.get("censored", pd.Series(False, index=ledger.index)).fillna(False)
        & ledger["dedupKept"].fillna(False)
    ]
    if trades.empty:
        return pd.DataFrame()
    years = sorted(trades["year"].unique())
    rows = []
    for year in years[train_years:]:
        window = trades[trades["year"] == year]
        if window.empty:
            continue
        rows.append(
            {
                "year": int(year),
                "trades": len(window),
                "realizedMean%": window["retNet"].mean() * 100,
                "excessMean%": window["excessRet"].mean() * 100
                if "excessRet" in window.columns
                else np.nan,
                "winRate%": (window["retNet"] > 0).mean() * 100,
            }
        )
    table = pd.DataFrame(rows)
    if not table.empty:
        positive = (table["realizedMean%"] > 0).mean() * 100
        table.attrs["positiveYears%"] = positive
    return table


def portfolio(
    ledger: pd.DataFrame, max_positions: int = 10, capital: float = 100_000.0
) -> tuple[pd.Series, pd.Series]:
    """Sequential portfolio with slot limits and equal position sizing.

    Event-study averages ignore that capital is finite; this shows what the
    same signals produce once only ``max_positions`` can be held at once.
    """
    trades = ledger[
        ledger["filled"].fillna(False)
        & ~ledger.get("censored", pd.Series(False, index=ledger.index)).fillna(False)
    ].sort_values(["entryDate", "strength"], ascending=[True, False])
    if trades.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    by_entry = {date: group for date, group in trades.groupby("entryDate")}
    calendar = pd.DatetimeIndex(sorted(set(trades["entryDate"]) | set(trades["exitDate"])))

    cash = capital
    equity = capital
    open_positions: list[dict] = []
    curve = {}
    taken = 0

    for today in calendar:
        still_open = []
        for position in open_positions:
            if position["exit"] <= today:
                cash += position["size"] * (1 + position["ret"])
            else:
                still_open.append(position)
        open_positions = still_open

        for _, row in by_entry.get(today, pd.DataFrame()).iterrows():
            if len(open_positions) >= max_positions:
                break
            size = equity / max_positions
            if size > cash:
                break
            cash -= size
            open_positions.append(
                {"exit": row["exitDate"], "size": size, "ret": row["retNet"]}
            )
            taken += 1

        equity = cash + sum(position["size"] for position in open_positions)
        curve[today] = equity

    series = pd.Series(curve).sort_index()
    peak = series.cummax()
    drawdown = series / peak - 1.0
    years = (series.index[-1] - series.index[0]).days / 365.25
    stats = pd.Series(
        {
            "tradesTaken": taken,
            "tradesSkipped": len(trades) - taken,
            "finalEquity": series.iloc[-1],
            "totalReturn%": (series.iloc[-1] / capital - 1) * 100,
            "cagr%": ((series.iloc[-1] / capital) ** (1 / years) - 1) * 100 if years > 0 else np.nan,
            "maxDrawdown%": drawdown.min() * 100,
            "years": years,
        }
    )
    return series, stats


def main() -> None:
    """Run every validation check for SW-1, the only strategy with excess return."""
    from quant import config as _config
    from quant.run import prepare

    pd.set_option("display.width", 200)
    panels, growth = prepare()

    print("\n=== SW-1 parameter stability (exit=time) ===")
    print(parameter_sweep(panels, growth).round(2).to_string(index=False))

    print("\n=== does the QQQ regime gate contribute? ===")
    print(regime_gate_test(panels, growth).round(2).to_string())

    signals = strategies.swing_momentum(panels)
    ledger = engine.build_ledger(
        panels, signals, _config.SWING, "SW1_momentum",
        entry_mode="nextOpen", exit_policy="time", universe_growth=growth,
    )

    print("\n=== SW-1 walk-forward by year ===")
    table = walk_forward(ledger)
    print(table.round(2).to_string(index=False))
    print("positive years: %.0f%%" % table.attrs.get("positiveYears%", float("nan")))

    print("\n=== SW-1 portfolio with slot limits ===")
    print("(open positions are held at cost, so real drawdown is deeper)")
    for slots in (5, 10, 20):
        _, stats = portfolio(ledger, max_positions=slots)
        print(f"\n-- max {slots} concurrent positions --")
        print(stats.round(2).to_string())


if __name__ == "__main__":
    main()
