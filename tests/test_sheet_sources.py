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
