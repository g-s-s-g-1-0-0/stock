"""Vectorized Strategy 1/2 entries must agree with the shipped rule engine.

`calculator.rules.evaluate_buy_condition` is the rule that actually trades. The
backtest replays it across 27 years, so every one of its six Strategy 1
conditions and four Strategy 2 conditions is compared against the live call on
the same bars.

Rare branches get their own samples: a strided sample is almost all False, so
it would pass even if the entry rule never fired at all.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculator import sheet_sources as live
from calculator.rules import IndicatorRow, evaluate_buy_condition
from quant import data, legacy_indicators, legacy_market, legacy_strategies

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sp500_cache")
TICKERS = ("AAPL", "JPM", "XOM", "KO", "NVDA")
FETCH_BARS = 320
"""`calc_technical_row` fetches this many daily bars."""

WARMUP = 400
SAMPLE_STRIDE = 200


@pytest.fixture(scope="module")
def state() -> pd.DataFrame:
    qqq = data.load_market("QQQ")
    vix = data.load_market("_VIX")
    if qqq is None or vix is None:
        pytest.skip("QQQ or _VIX bars are missing from .bt_cache")
    return legacy_market.build_state(qqq, vix["Close"])


def _load(ticker: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{ticker}.pkl")
    if not os.path.exists(path):
        pytest.skip(f"{ticker} not in .sp500_cache; run quant.collect_sp500 first")
    frame = pd.read_pickle(path)
    return frame[frame["Close"] > 0]


@pytest.fixture(scope="module")
def cases(state: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """Per ticker: raw bars, the live-indicator panel, and vectorized signals."""
    out = {}
    for ticker in TICKERS:
        bars = _load(ticker)
        bars = bars[bars.index.isin(state.index)]
        panel = legacy_indicators.add_legacy(bars.copy())
        signals = legacy_strategies.entry_conditions(panel, state)
        out[ticker] = (bars, panel, signals)
    return out


def _live_row(bars: pd.DataFrame, position: int) -> IndicatorRow:
    """The IndicatorRow the service would have built from that day's fetch."""
    history = bars.iloc[: position + 1].tail(FETCH_BARS)
    rows = [
        {
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
            "volume": float(row.Volume),
        }
        for row in history.itertuples()
    ]
    closes = [row["close"] for row in rows]
    lr = live.calc_lr(rows)
    return IndicatorRow(
        stock_name="test",
        current_price=closes[-1],
        ma200=sum(closes[-200:]) / 200,
        ma20=sum(closes[-20:]) / 20,
        ma60=sum(closes[-60:]) / 60,
        ma144=sum(closes[-144:]) / 144,
        rsi=round(live.calc_rsi(closes)[-1], 2),
        cci=round(live.calc_cci(rows, period=14)[-1], 2),
        lr_slope=lr["lrSlope"],
        lr_trendline=lr["lrTrendline"],
        candle_low=rows[-1]["low"],
    )


def _live_buy(
    bars: pd.DataFrame, state: pd.DataFrame, position: int, *, season_open: bool
) -> dict:
    stamp = bars.index[position]
    market = state.loc[stamp]
    return evaluate_buy_condition(
        _live_row(bars, position),
        vix=float(market["vix"]) if pd.notna(market["vix"]) else None,
        ixic_dist=float(market["premiumPercent"]) if pd.notna(market["premiumPercent"]) else None,
        ixic_filter_active=False,
        nasdaq_buy_block_max=float(market["buyBlockMax"]),
        is_recovery_market=bool(market["isRecoveryMarket"]),
        season_open=season_open,
    )


def _compare(bars, state, signals, positions, *, season_open):
    for position in positions:
        stamp = bars.index[position]
        expected = _live_buy(bars, state, position, season_open=season_open)
        actual = signals.loc[stamp]
        for number, flag in enumerate(expected["conditions"]["1"], start=1):
            assert bool(actual[f"s1cond{number}"]) == bool(flag), f"{stamp} s1cond{number}"
        season_flag, *market_flags = expected["conditions"]["2"]
        assert bool(season_flag) == season_open, f"{stamp} s2cond1"
        for number, flag in enumerate(market_flags, start=2):
            assert bool(actual[f"s2cond{number}"]) == bool(flag), f"{stamp} s2cond{number}"
        assert bool(actual["entry1"]) == (expected["strategyType"] == "1"), f"{stamp} entry1"
        entry2 = legacy_strategies.strategy2_entry(actual, season_open)
        assert bool(entry2) == (expected["strategyType"] == "2"), f"{stamp} entry2"


def _positions(bars: pd.DataFrame, mask: pd.Series, limit: int) -> list[int]:
    flagged = mask[mask].index
    flagged = flagged[flagged >= bars.index[WARMUP]]
    if len(flagged) == 0:
        return []
    step = max(1, len(flagged) // limit)
    return list(bars.index.get_indexer(flagged)[::step][:limit])


def test_strided_sample_matches(cases, state):
    for bars, _, signals in cases.values():
        _compare(bars, state, signals, range(WARMUP, len(bars), SAMPLE_STRIDE), season_open=False)


def test_strategy1_entries_are_real(cases, state):
    """Every date the vectorized rule buys, the live rule must buy too."""
    checked = 0
    for bars, _, signals in cases.values():
        positions = _positions(bars, signals["entry1"], 8)
        _compare(bars, state, signals, positions, season_open=False)
        checked += len(positions)
    assert checked > 0, "Strategy 1 never fired; its True branch is untested"


def test_strategy1_near_misses_match(cases, state):
    """Dates failing exactly one condition catch a rule that never fires."""
    checked = 0
    for bars, _, signals in cases.values():
        conditions = signals[[f"s1cond{n}" for n in range(1, 7)]]
        positions = _positions(bars, conditions.sum(axis=1).eq(5), 8)
        _compare(bars, state, signals, positions, season_open=False)
        checked += len(positions)
    assert checked > 0, "no near-miss dates found; the sample is too narrow"


def test_strategy2_entries_are_real(cases, state):
    """Strategy 2 only exists while the season is open, so force it open."""
    checked = 0
    for bars, _, signals in cases.values():
        eligible = signals["s2cond2"] & signals["s2cond3"] & signals["s2cond4"] & ~signals["entry1"]
        positions = _positions(bars, eligible, 8)
        _compare(bars, state, signals, positions, season_open=True)
        checked += len(positions)
    assert checked > 0, "Strategy 2 never fired; its True branch is untested"


def test_strategy2_needs_open_season(cases):
    """A closed season must block every Strategy 2 entry, not merely fewer."""
    for bars, _, signals in cases.values():
        del bars
        assert not any(legacy_strategies.strategy2_entry(row, False) for _, row in signals.iterrows())
