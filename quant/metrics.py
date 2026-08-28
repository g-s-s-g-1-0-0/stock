"""Summary statistics derived from the trade ledger.

Realized return, maximum favourable excursion, maximum adverse excursion and
fixed checkpoints are always reported together. Reporting only one of them is
what made backtest output look unrelated to what a trader sees on screen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config


def _traded(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger
    mask = ledger["filled"].fillna(False)
    if "censored" in ledger.columns:
        mask &= ~ledger["censored"].fillna(False)
    if "dedupKept" in ledger.columns:
        mask &= ledger["dedupKept"].fillna(False)
    return ledger[mask]


def headline(ledger: pd.DataFrame) -> pd.Series:
    """One row that puts every yardstick side by side, in percent."""
    trades = _traded(ledger)
    if trades.empty:
        return pd.Series({"trades": 0})

    realized = trades["retNet"]
    wins = realized[realized > 0]
    losses = realized[realized <= 0]
    to_target = trades.loc[trades["exitReason"] == "target", "daysHeld"]

    out = {
        "signals": int(len(ledger)),
        "trades": int(len(trades)),
        "unfilled": int((~ledger["filled"].fillna(False)).sum()),
        "censored": int(ledger.get("censored", pd.Series(dtype=bool)).fillna(False).sum()),
        "realizedMean%": realized.mean() * 100,
        "realizedMedian%": realized.median() * 100,
        "mfeHoldMean%": trades["mfeHold"].mean() * 100,
        "mfeHoldMedian%": trades["mfeHold"].median() * 100,
        "maeHoldMean%": trades["maeHold"].mean() * 100,
        "holdEndMean%": trades["retHoldEnd"].mean() * 100,
        "winRate%": (realized > 0).mean() * 100,
        "payoff": abs(wins.mean() / losses.mean()) if len(losses) and losses.mean() != 0 else np.nan,
        "targetHit%": (trades["exitReason"] == "target").mean() * 100,
        "stopHit%": (trades["exitReason"] == "stop").mean() * 100,
        "daysToTargetMedian": to_target.median() if len(to_target) else np.nan,
        "daysHeldMean": trades["daysHeld"].mean(),
        "targetPctMean%": trades["targetPct"].mean() * 100,
        "stopPctMean%": trades["stopPct"].mean() * 100,
        "realizedP10%": realized.quantile(0.10) * 100,
        "worst%": realized.min() * 100,
        "ambiguous%": trades["barrierAmbiguous"].mean() * 100,
        "pessimisticMean%": trades["retPessimistic"].mean() * 100,
        "optimisticMean%": trades["retOptimistic"].mean() * 100,
    }
    for step in config.CHECKPOINTS:
        column = f"retN{step}"
        if column in trades.columns:
            out[f"holdN{step}Mean%"] = trades[column].mean() * 100
    if "excessRet" in trades.columns:
        out["excessMean%"] = trades["excessRet"].mean() * 100
        out["universeMean%"] = trades["universeRet"].mean() * 100
    return pd.Series(out)


def by_strength_decile(ledger: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """Results split by how strongly the signal conditions were satisfied.

    A signal that barely cleared its threshold and one that cleared it by a
    wide margin are different trades; averaging them together hides the edge.
    """
    trades = _traded(ledger)
    if trades.empty or trades["strength"].notna().sum() < bins * 4:
        return pd.DataFrame()
    labels = [f"Q{i + 1}" for i in range(bins)]
    bucket = pd.qcut(trades["strength"], bins, labels=labels, duplicates="drop")
    grouped = trades.groupby(bucket, observed=True)
    return pd.DataFrame(
        {
            "trades": grouped.size(),
            "realizedMean%": grouped["retNet"].mean() * 100,
            "realizedMedian%": grouped["retNet"].median() * 100,
            "mfeHoldMean%": grouped["mfeHold"].mean() * 100,
            "winRate%": grouped["retNet"].apply(lambda s: (s > 0).mean() * 100),
            "targetHit%": grouped["exitReason"].apply(lambda s: (s == "target").mean() * 100),
        }
    )


def by_era(ledger: pd.DataFrame) -> pd.DataFrame:
    """Results per market era. Previous studies only covered 2010 onward."""
    trades = _traded(ledger)
    if trades.empty:
        return pd.DataFrame()
    rows = {}
    dates = pd.to_datetime(trades["signalDate"])
    for label, start, end in config.ERAS:
        window = trades[(dates >= start) & (dates <= end)]
        if window.empty:
            rows[label] = {"trades": 0}
            continue
        rows[label] = {
            "trades": len(window),
            "realizedMean%": window["retNet"].mean() * 100,
            "realizedMedian%": window["retNet"].median() * 100,
            "mfeHoldMean%": window["mfeHold"].mean() * 100,
            "winRate%": (window["retNet"] > 0).mean() * 100,
            "targetHit%": (window["exitReason"] == "target").mean() * 100,
            "ambiguous%": window["barrierAmbiguous"].mean() * 100,
        }
    return pd.DataFrame(rows).T


def distribution(ledger: pd.DataFrame) -> pd.Series:
    """Deciles plus the share of total profit coming from the best trades."""
    trades = _traded(ledger)
    if trades.empty:
        return pd.Series(dtype=float)
    realized = trades["retNet"].sort_values()
    quantiles = {f"p{int(q * 100)}%": realized.quantile(q) * 100 for q in np.arange(0.1, 1.0, 0.1)}
    total = realized.clip(lower=0).sum()
    top = int(np.ceil(len(realized) * 0.10))
    quantiles["top10%ProfitShare%"] = (
        realized.nlargest(top).sum() / total * 100 if total > 0 else np.nan
    )
    quantiles["mfeTop20%Median%"] = trades["mfeHold"].nlargest(
        max(1, int(len(trades) * 0.20))
    ).median() * 100
    return pd.Series(quantiles)


def concentration(ledger: pd.DataFrame) -> pd.DataFrame:
    """Ticker concentration measured against gross profit.

    Net profit can sit near zero, which makes "share of net" explode into
    meaningless percentages, so contribution is expressed as a share of the
    total gross profit produced by winning trades.
    """
    trades = _traded(ledger)
    if trades.empty:
        return pd.DataFrame()
    gross_profit = trades["retNet"].clip(lower=0).sum()
    by_ticker = trades.groupby("ticker")["retNet"].agg(
        trades="size", sumRet="sum", grossProfit=lambda s: s.clip(lower=0).sum()
    )
    by_ticker["shareOfGrossProfit%"] = (
        by_ticker["grossProfit"] / gross_profit * 100 if gross_profit > 0 else np.nan
    )
    by_ticker["sumRet%"] = by_ticker["sumRet"] * 100
    return (
        by_ticker.sort_values("grossProfit", ascending=False)
        .head(10)[["trades", "sumRet%", "shareOfGrossProfit%"]]
    )


def ambiguity_verdict(ledger: pd.DataFrame) -> str:
    trades = _traded(ledger)
    if trades.empty:
        return "no trades"
    share = trades["barrierAmbiguous"].mean()
    if share > config.AMBIGUITY_LIMIT:
        return (
            f"NOT CONCLUSIVE on daily bars: {share:.1%} of trades touched both barriers "
            "in one session; hourly data is required to decide the order"
        )
    return f"conclusive on daily bars: {share:.1%} ambiguous"
