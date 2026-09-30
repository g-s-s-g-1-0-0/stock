import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator import market_signals


def test_timescale_close_uses_the_last_bar_field():
    message = {
        "m": "timescale_update",
        "p": ["cs", {"s1": {"s": [
            {"i": 0, "v": [1, 10, 11, 9, 10.5]},
            {"i": 1, "v": [2, 12, 13, 11, 12.25]},
        ]}}],
    }

    assert market_signals._closes_from_timescale(message) == {0: 10.5, 1: 12.25}


def test_signal_rows_use_market_breadth_and_plain_credit_name(monkeypatch):
    monkeypatch.setattr(market_signals, "_tradingview_closes", lambda symbol, bars: {
        "INDEX:MMTW": [61.4],
        "FRED:BAMLH0A0HYM2": [2.0] * 20 + [2.4],
    }[symbol])
    monkeypatch.setattr(market_signals, "_yahoo_closes", lambda symbol: [4.0] * 20 + [4.3])
    monkeypatch.setattr(market_signals, "_nyse_stock_count", lambda: 2838)

    signals = market_signals.build_market_signals()
    rows = dict(market_signals.market_signal_rows(signals))

    assert signals["status"] == "주의"
    assert rows["미국 주식 20일선 상회 비율"] == "61% (2,838개 중) · 정상"
    assert signals["breadth"]["count"] == 2838
    assert rows["미국 10년물 금리 20일 변화"] == "4.30% · 20거래일 +0.30%p · 주의"
    assert rows["미국 저신용 회사 추가금리 20일 변화"] == "2.40%p · 20거래일 +0.40%p · 정상"


def test_breadth_warning_sets_the_combined_signal(monkeypatch):
    monkeypatch.setattr(market_signals, "_tradingview_closes", lambda symbol, bars: {
        "INDEX:MMTW": [26.2],
        "FRED:BAMLH0A0HYM2": [3.0] * 21,
    }[symbol])
    monkeypatch.setattr(market_signals, "_yahoo_closes", lambda symbol: [5.0] * 21)
    monkeypatch.setattr(market_signals, "_nyse_stock_count", lambda: None)

    signals = market_signals.build_market_signals()

    assert signals["breadth"]["status"] == "경고"
    assert signals["treasury"]["status"] == "정상"
    assert signals["status"] == "경고"


def test_failed_series_stays_undecided(monkeypatch):
    def fail_series(*_args):
        raise RuntimeError("down")

    monkeypatch.setattr(market_signals, "_tradingview_closes", fail_series)
    monkeypatch.setattr(market_signals, "_yahoo_closes", fail_series)

    rows = dict(market_signals.market_signal_rows(market_signals.build_market_signals()))

    assert rows["고점 신호 종합"] == "판단 불가"
    assert rows["미국 10년물 금리 20일 변화"] == "데이터 수집 실패 · 판단 불가"
    assert rows["미국 저신용 회사 추가금리 20일 변화"] == "데이터 수집 실패 · 판단 불가"
