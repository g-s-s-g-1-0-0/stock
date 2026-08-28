"""Strategy definitions.

Each strategy states its hypothesis before its conditions. Conditions are
evaluated on the signal-day close only, and every strategy returns a
continuous ``strength`` score so results can be reported by strength decile
instead of being flattened into one average.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Signals = dict[str, pd.DataFrame]


def _empty(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal": pd.Series(False, index=panel.index, dtype=bool),
            "strength": pd.Series(np.nan, index=panel.index, dtype=float),
        }
    )


def _pack(panel: pd.DataFrame, mask: pd.Series, strength: pd.Series) -> pd.DataFrame:
    mask = mask.fillna(False).astype(bool) & panel["eligible"]
    return pd.DataFrame({"signal": mask, "strength": strength.where(mask)})


def cross_sectional_rank(panels: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    """Percentile rank of ``column`` across tickers on each date."""
    wide = pd.DataFrame({ticker: frame[column] for ticker, frame in panels.items()})
    return wide.rank(axis=1, pct=True)


def swing_washout(panels: dict[str, pd.DataFrame]) -> Signals:
    """SW-3. Market-wide forced selling pushes names below fair value.

    Reproduces the existing bottom-rebound idea so it can be re-measured with
    the corrected yardstick rather than replaced.
    """
    out: Signals = {}
    for ticker, panel in panels.items():
        stressed = panel["vix"].ge(22) | panel["qqqPremium"].le(-0.05)
        mask = (
            stressed
            & panel["isLow20"]
            & panel["rsi14"].lt(30)
            & panel["lowerTail"].ge(0.5)
            & panel["volRatio20"].ge(1.5)
        )
        strength = (
            (30 - panel["rsi14"]) / 15.0
            + (panel["lowerTail"] - 0.5) / 0.25
            + (panel["volRatio20"] - 1.5) / 1.5
            + (-panel["dd60"] - 0.15) / 0.15
        )
        out[ticker] = _pack(panel, mask, strength)
    return out


def swing_momentum(
    panels: dict[str, pd.DataFrame],
    rank_min: float = 0.90,
    dist_high_min: float = -0.15,
    adx_min: float = 20.0,
    require_regime: bool = True,
) -> Signals:
    """SW-1. The momentum premium is stable only while the index trends up.

    Thresholds are arguments so the same definition can be swept for
    parameter stability instead of being hard-coded at its best value.
    """
    ranks = cross_sectional_rank(panels, "mom126")
    out: Signals = {}
    for ticker, panel in panels.items():
        rank = ranks[ticker].reindex(panel.index)
        mask = (
            rank.ge(rank_min)
            & panel["distHigh52"].ge(dist_high_min)
            & panel["adx14"].gt(adx_min)
        )
        if require_regime:
            mask &= panel["qqqPremium"].gt(0) & panel["qqqMa200Rising"].fillna(0.0).gt(0.5)
        out[ticker] = _pack(panel, mask, rank * 10.0)
    return out


def swing_squeeze(panels: dict[str, pd.DataFrame]) -> Signals:
    """SW-2. Volatility contraction stores energy; volume confirms release."""
    out: Signals = {}
    for ticker, panel in panels.items():
        squeezed = panel["bbWidthPct"].le(0.20).rolling(5).sum().shift(1).ge(5)
        mask = (
            panel["qqqPremium"].gt(0)
            & squeezed
            & panel["ma20"].gt(panel["ma60"])
            & panel["ma60"].gt(panel["ma200"])
            & panel["distHigh52"].ge(-0.10)
            & panel["breakout20"]
            & panel["volRatio20"].ge(2.0)
        )
        strength = (panel["volRatio20"] - 2.0) + (0.20 - panel["bbWidthPct"]) * 10.0
        out[ticker] = _pack(panel, mask, strength)
    return out


def day_oversold(panels: dict[str, pd.DataFrame]) -> Signals:
    """DT-1. Short-term oversold inside an uptrend is a flow imbalance."""
    out: Signals = {}
    for ticker, panel in panels.items():
        mask = (
            panel["Close"].gt(panel["ma200"])
            & panel["rsi2"].lt(5)
            & panel["down3"]
        )
        strength = (5 - panel["rsi2"]) / 5.0 + (-panel["dd60"]) / 0.10
        out[ticker] = _pack(panel, mask, strength)
    return out


def day_gap_reversal(panels: dict[str, pd.DataFrame]) -> Signals:
    """DT-2 daily proxy. A newsless gap down is an overreaction.

    The real rule needs the first 60 intraday minutes. On daily bars the
    closest observable proxy is "gapped down but closed above the open", which
    is weaker evidence; hourly data replaces this once collected.
    """
    out: Signals = {}
    for ticker, panel in panels.items():
        mask = (
            panel["gap"].le(-0.04)
            & panel["Close"].shift(1).gt(panel["ma20"].shift(1))
            & panel["Close"].gt(panel["Open"])
        )
        strength = -panel["gap"] / 0.04 + panel["lowerTail"]
        out[ticker] = _pack(panel, mask, strength)
    return out


def day_gap_continuation_proxy(panels: dict[str, pd.DataFrame]) -> Signals:
    """DT-3. EOD proxy for a premarket ``gap-and-go`` continuation setup.

    The source setup enters around 10:00 after price clears the premarket
    high.  Historical premarket bars are not in the current data store, so
    this deliberately stricter proxy waits for a completed daily bar: a 5%+
    opening gap, close above the prior day's high, positive close, elevated
    volume, and an intact long-term trend.  It measures the hypothesis while
    keeping it distinct from the executable intraday rule.
    """
    out: Signals = {}
    for ticker, panel in panels.items():
        gap = panel["gap"]
        close_above_prior_high = panel["Close"].gt(panel["High"].shift(1))
        mask = (
            gap.ge(0.05)
            & close_above_prior_high
            & panel["Close"].gt(panel["Open"])
            & panel["Close"].gt(panel["ma200"])
            & panel["volRatio20"].ge(1.5)
        )
        strength = (
            (gap - 0.05) / 0.05
            + (panel["Close"] / panel["High"].shift(1) - 1.0) / 0.03
            + (panel["volRatio20"] - 1.5) / 1.5
        )
        out[ticker] = _pack(panel, mask, strength)
    return out


REGISTRY = {
    "SW3_washout": swing_washout,
    "SW1_momentum": swing_momentum,
    "SW2_squeeze": swing_squeeze,
    "DT1_oversold": day_oversold,
    "DT2_gap": day_gap_reversal,
    "DT3_gap_continuation_proxy": day_gap_continuation_proxy,
}
