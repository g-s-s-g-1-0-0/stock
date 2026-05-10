from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator import sheet_sources


def test_korean_earnings_d_day_uses_kst(monkeypatch):
    monkeypatch.setattr(sheet_sources, "kst_now", lambda: datetime(2026, 5, 10, 14, 0))

    assert sheet_sources.process_korean_earnings_date("2026/04/23") == "2026-04-23 (D+17)"


def test_us_earnings_d_day_uses_kst_and_amc_rollover(monkeypatch):
    monkeypatch.setattr(sheet_sources, "kst_now", lambda: datetime(2026, 5, 10, 14, 0))

    assert sheet_sources.process_us_earnings_date("May 20 AMC") == "2026-05-21 (D-11)"


def test_calc_technical_row_uses_sheet_cci_period_and_volume_ratios(monkeypatch):
    rows = []
    for index in range(220):
        base = 100 + index
        rows.append({
            "open": float(base - 1),
            "high": float(base + 2),
            "low": float(base - 3),
            "close": float(base),
            "volume": float(1000 + index * 10),
        })

    monkeypatch.setattr(sheet_sources, "fetch_ohlcv", lambda ticker: rows)

    row = sheet_sources.calc_technical_row("TEST")
    cci_values = sheet_sources.calc_cci(rows, period=14)

    assert row["cci"] == round(cci_values[-1], 2)
    assert row["cciD1"] == round(cci_values[-2], 2)
    assert row["macdSlope"] == round(row["macd"] - row["macdD1"], 2)
    assert row["volRatio"] == round(rows[-1]["volume"] / (sum(item["volume"] for item in rows[-5:]) / 5), 2)
    assert row["prevVolRatio"] == round(rows[-2]["volume"] / (sum(item["volume"] for item in rows[-6:-1]) / 5), 2)
    assert row["volRatio20"] == round(rows[-1]["volume"] / (sum(item["volume"] for item in rows[-20:]) / 20), 2)
