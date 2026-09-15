from datetime import datetime
import json
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


def test_refresh_earnings_date_label_recomputes_stale_d_day():
    today = datetime(2026, 8, 13, 0, 5)

    assert sheet_sources.refresh_earnings_date_label("2026-08-13 (D-1)", today) == "2026-08-13 (D-0)"
    assert sheet_sources.refresh_earnings_date_label("2026-08-14 (D-2)", today) == "2026-08-14 (D-1)"
    assert sheet_sources.refresh_earnings_date_label("-", today) == "-"
    assert sheet_sources.refresh_earnings_date_label("미정", today) == "미정"


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


def test_korean_valuation_uses_naver_mobile_api(monkeypatch):
    annual_periods = ["202312", "202412", "202512", "202612"]
    quarter_periods = ["202501", "202502", "202503", "202504", "202601"]

    def finance(periods, consensus=False):
        titles = [{"key": key, "isConsensus": "Y" if consensus and key == periods[-1] else "N"} for key in periods]
        values = {
            "매출액": [100, 110, 120, 130, 140],
            "영업이익": [10, 11, 12, 13, 14],
            "EPS": [100, 110, 120, 130, 150],
            "ROE": [8, 9, 10, 11, 12],
            "부채비율": [50, 51, 52, 53, 54],
            "당좌비율": [120, 121, 122, 123, 124],
        }
        return {"financeInfo": {"trTitleList": titles, "rowList": [
            {"title": title, "columns": {key: {"value": str(value)} for key, value in zip(periods, row_values)}}
            for title, row_values in values.items()
        ]}}

    responses = {
        "/finance/annual": finance(annual_periods, consensus=True),
        "/finance/quarter": finance(quarter_periods),
        "/integration": {"totalInfos": [
            {"code": "marketValue", "key": "시총", "value": "1조 2,000억"},
            {"code": "per", "key": "PER", "value": "10.00배"},
            {"code": "pbr", "key": "PBR", "value": "1.50배"},
        ]},
        "/basic": {"closePrice": "10,000"},
    }

    def fake_fetch(url, **kwargs):
        if "/finance/annual" in url:
            return json.dumps(responses["/finance/annual"])
        if "/finance/quarter" in url:
            return json.dumps(responses["/finance/quarter"])
        if "/integration" in url:
            return json.dumps(responses["/integration"])
        if "/basic" in url:
            return json.dumps(responses["/basic"])
        raise AssertionError(url)

    monkeypatch.setattr(sheet_sources, "fetch_text", fake_fetch)
    monkeypatch.setattr(sheet_sources, "fetch_korean_earnings_date", lambda code: "-")

    values = sheet_sources.fetch_korean_valuation("000001")

    assert values[0] == "₩ 1조 2,000억"
    assert values[1] == "₩ 500억"
    assert values[9:12] == ["10.00", "1.50", "12.00%"]
    assert values[13] == "120,000,000"
