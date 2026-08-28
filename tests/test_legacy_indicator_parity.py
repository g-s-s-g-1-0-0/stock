"""The vectorized indicators must agree with the live per-row calculations.

Strategies A-H and 1/2/3 are threshold rules, so a small formula drift silently
moves signals in and out. These tests feed identical bars to both
implementations and compare the newest value.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculator import sheet_sources as live
from quant import legacy_indicators as vec

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sp500_cache")
TICKERS = ("AAPL", "JPM", "XOM", "KO", "NVDA")
BARS = 320


def _panel(ticker: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{ticker}.pkl")
    if not os.path.exists(path):
        pytest.skip(f"{ticker} not in .sp500_cache; run quant.collect_sp500 first")
    return pd.read_pickle(path).tail(BARS)


def _rows(panel: pd.DataFrame) -> list[dict[str, float]]:
    return [
        {
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
            "volume": float(row.Volume),
        }
        for row in panel.itertuples()
    ]


@pytest.fixture(params=TICKERS)
def pair(request):
    panel = _panel(request.param)
    computed = vec.add_legacy(panel.copy())
    return _rows(panel), computed.iloc[-1], request.param


def test_rsi_matches(pair):
    rows, latest, _ = pair
    expected = live.calc_rsi([r["close"] for r in rows])[-1]
    assert latest["legRsi"] == pytest.approx(expected, abs=1e-6)


def test_cci_matches(pair):
    rows, latest, _ = pair
    expected = live.calc_cci(rows, period=14)[-1]
    assert latest["legCci"] == pytest.approx(expected, abs=1e-6)


def test_bollinger_matches(pair):
    rows, latest, _ = pair
    expected = live.calc_bollinger(rows)
    assert latest["legPctB"] == pytest.approx(expected["pctB"], abs=0.01)
    assert latest["legPctBLow"] == pytest.approx(expected["pctBLow"], abs=0.01)
    assert latest["legBbWidth"] == pytest.approx(expected["bbWidth"], abs=0.01)
    assert latest["legBbWidthD1"] == pytest.approx(expected["bbWidthD1"], abs=0.01)
    assert latest["legBbWidthAvg60"] == pytest.approx(expected["bbWidthAvg60"], abs=0.01)


def test_linear_regression_matches(pair):
    rows, latest, _ = pair
    expected = live.calc_lr(rows)
    assert latest["legLrTrendline"] == pytest.approx(expected["lrTrendline"], abs=0.01)
    assert latest["legLrSlope"] == pytest.approx(expected["lrSlope"], abs=1e-5)


def test_volume_ratios_match(pair):
    rows, latest, _ = pair
    volumes = [r["volume"] for r in rows]
    assert latest["legVolRatio"] == pytest.approx(volumes[-1] / (sum(volumes[-5:]) / 5), abs=1e-6)
    assert latest["legVolRatio20"] == pytest.approx(volumes[-1] / (sum(volumes[-20:]) / 20), abs=1e-6)


def test_moving_averages_match(pair):
    rows, latest, _ = pair
    closes = [r["close"] for r in rows]
    assert latest["legMa20"] == pytest.approx(sum(closes[-20:]) / 20, abs=1e-6)
    assert latest["legMa60"] == pytest.approx(sum(closes[-60:]) / 60, abs=1e-6)
    assert latest["legMa144"] == pytest.approx(sum(closes[-144:]) / 144, abs=1e-6)
    assert latest["legMa200"] == pytest.approx(sum(closes[-200:]) / 200, abs=1e-6)
    assert latest["legMa20Prev5"] == pytest.approx(sum(closes[-25:-5]) / 20, abs=1e-6)


def test_macd_hist_close_enough(pair):
    """EMA seeding differs, so allow a small tolerance rather than exact equality."""
    rows, latest, _ = pair
    expected = live.calc_macd([r["close"] for r in rows])["macdHist"]
    assert latest["legMacdHist"] == pytest.approx(expected, abs=0.05)


def test_adx_close_enough(pair):
    rows, latest, _ = pair
    expected = live.calc_adx(rows)
    assert latest["legPlusDi"] == pytest.approx(expected["plusDI"], abs=1.0)
    assert latest["legMinusDi"] == pytest.approx(expected["minusDI"], abs=1.0)
    assert latest["legAdx"] == pytest.approx(expected["adx"], abs=1.5)
