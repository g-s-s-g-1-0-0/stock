"""The vectorized QQQ regime must agree with the live market-state builder.

Strategies 1 and 2 are gated by market state, not by per-ticker signals alone:
the recovery-market flag decides whether Strategy 2 can fire at all, and the
peak alert force-sells every open position. A drift here moves every trade in
the backtest, so the whole state dict is compared date by date against
`calculator.market_regime.build_qqq_market_state` fed the same bars the live
service would have fetched on that day.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculator import sheet_sources as live
from calculator.market_regime import build_qqq_market_state, qqq_recent_ma200_min_distance
from quant import data
from quant import legacy_market

DAILY_FETCH_BARS = 320
"""`calc_technical_row` fetches this many daily bars."""

TWO_YEAR_BARS = 504
"""`qqq_market_state_snapshot` fetches range=2y for the recovery lookback."""

WEEKLY_FETCH_BARS = 105
"""range=2y&interval=1wk is about this many weekly bars."""

SAMPLE_STRIDE = 250


@pytest.fixture(scope="module")
def qqq() -> pd.DataFrame:
    frame = data.load_market("QQQ")
    if frame is None:
        pytest.skip("QQQ daily bars are missing from .bt_cache")
    return frame


@pytest.fixture(scope="module")
def state(qqq: pd.DataFrame) -> pd.DataFrame:
    return legacy_market.build_state(qqq)


def _sample_positions(qqq: pd.DataFrame) -> list[int]:
    return list(range(TWO_YEAR_BARS, len(qqq), SAMPLE_STRIDE))


def _live_state(qqq: pd.DataFrame, position: int) -> dict[str, object]:
    """Rebuild the state the service would have published on that date."""
    history = qqq.iloc[: position + 1]
    rows = [
        {
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
            "volume": float(row.Volume),
        }
        for row in history.tail(TWO_YEAR_BARS).itertuples()
    ]
    closes = [row["close"] for row in rows[-DAILY_FETCH_BARS:]]
    rsi_values = live.calc_rsi(closes)
    macd = live.calc_macd(closes)

    weekly = history["Close"].resample("W-FRI").last().dropna()
    weekly_closes = list(weekly.iloc[-WEEKLY_FETCH_BARS:])
    if weekly.index[-1] != history.index[-1]:
        weekly_closes[-1] = float(history["Close"].iloc[-1])

    qqq_row = {
        "close": closes[-1],
        "ma200": sum(closes[-200:]) / 200,
        "rsi": round(rsi_values[-1], 2),
        "rsiD1": round(rsi_values[-2], 2),
        "macdHist": macd["macdHist"],
        "macdHistD1": macd["macdHistD1"],
        "macdHistD2": macd["macdHistD2"],
    }
    return build_qqq_market_state(
        qqq_row,
        recent_min_dist=qqq_recent_ma200_min_distance(rows),
        weekly_rsi=round(live.calc_rsi(weekly_closes)[-1], 2),
    )


@pytest.fixture(scope="module")
def pairs(qqq: pd.DataFrame, state: pd.DataFrame) -> list[tuple[pd.Timestamp, dict, pd.Series]]:
    out = []
    for position in _sample_positions(qqq):
        stamp = qqq.index[position]
        out.append((stamp, _live_state(qqq, position), state.loc[stamp]))
    return out


@pytest.fixture(scope="module")
def peak_pairs(qqq: pd.DataFrame, state: pd.DataFrame) -> list[tuple[pd.Timestamp, dict, pd.Series]]:
    """Dates the vectorized state calls a peak, which a strided sample misses.

    The peak alert force-sells every open position, so its rare True branch
    needs checking directly rather than hoping a sample lands on one.
    """
    flagged = state.index[state["peakTriggered"].to_numpy(bool)]
    flagged = flagged[flagged >= qqq.index[TWO_YEAR_BARS]]
    positions = qqq.index.get_indexer(flagged)[::37][:12]
    return [(qqq.index[p], _live_state(qqq, p), state.iloc[p]) for p in positions]


def test_peak_dates_exist(peak_pairs):
    assert peak_pairs, "no peak alert ever fired; the rare branch is untested"


def test_peak_dates_match_live(peak_pairs):
    for stamp, expected, actual in peak_pairs:
        assert bool(expected["peakTriggered"]), f"{stamp} is a false peak"
        assert bool(actual["warnTriggered"]) == bool(expected["warnTriggered"]), stamp


def test_sample_covers_multiple_regimes(pairs):
    """A parity run that never sees a recovery market proves nothing about it."""
    flags = {bool(expected["isRecoveryMarket"]) for _, expected, _ in pairs}
    assert flags == {True, False}, "sampled dates must include recovery and normal markets"


def test_premium_matches(pairs):
    for stamp, expected, actual in pairs:
        assert actual["premiumPercent"] == pytest.approx(expected["premiumPercent"], abs=1e-6), stamp


def test_recovery_lookback_matches(pairs):
    for stamp, expected, actual in pairs:
        assert actual["recent60MinPremiumPercent"] == pytest.approx(
            expected["recent60MinPremiumPercent"], abs=1e-6
        ), stamp


def test_recovery_flag_matches(pairs):
    for stamp, expected, actual in pairs:
        assert bool(actual["isRecoveryMarket"]) == bool(expected["isRecoveryMarket"]), stamp


def test_buy_block_max_matches(pairs):
    for stamp, expected, actual in pairs:
        assert actual["buyBlockMax"] == pytest.approx(expected["buyBlockMax"]), stamp


def test_weekly_rsi_matches(pairs):
    for stamp, expected, actual in pairs:
        assert actual["weeklyRsi"] == pytest.approx(expected["weeklyRsi"], abs=1e-6), stamp


def test_daily_rsi_matches(pairs):
    for stamp, expected, actual in pairs:
        assert actual["dailyRsi"] == pytest.approx(expected["dailyRsi"], abs=1e-6), stamp
        assert actual["dailyRsiPrev"] == pytest.approx(expected["dailyRsiPrev"], abs=1e-6), stamp


def test_macd_hist_matches(pairs):
    """EMA seeding differs, so compare the rounded values the service compares."""
    for stamp, expected, actual in pairs:
        assert actual["macdHist"] == pytest.approx(expected["macdHist"], abs=0.05), stamp
        assert actual["macdHistD1"] == pytest.approx(expected["macdHistD1"], abs=0.05), stamp
        assert actual["macdHistD2"] == pytest.approx(expected["macdHistD2"], abs=0.05), stamp


def test_peak_and_warn_flags_match(pairs):
    for stamp, expected, actual in pairs:
        assert bool(actual["rsiHotAndFalling"]) == bool(expected["rsiHotAndFalling"]), stamp
        assert bool(actual["macdHistSlowing"]) == bool(expected["macdHistSlowing"]), stamp
        assert bool(actual["peakTriggered"]) == bool(expected["peakTriggered"]), stamp
        assert bool(actual["warnTriggered"]) == bool(expected["warnTriggered"]), stamp
