"""보유 종목 의견 산정 회귀 테스트 (전략 1/2).

보유 중('보유 중' 매매로그가 있는) 종목은, 신규 진입 신호가 그 턴에 다시
발화하지 않더라도 보유용(hold) 조건이 유지되는 한 의견이 '매수'로 유지돼야 한다.
hold 조건을 실제로 이탈했을 때만 '관망'으로 내려간다.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator import pipeline


def make_technical_row(**overrides):
    """calc_technical_row가 돌려주는 형태의 완전한 행을 기본값으로 생성."""
    base = {
        "close": 110.0, "closeD1": 109.0, "open": 109.0, "high": 111.0, "low": 108.0,
        "volume": 1_000_000, "lowerTail": 1.0, "upperTail": 1.0, "bodyLength": 1.0,
        "ma5": 109.0, "ma20": 105.0, "ma20D1": 104.5, "ma20Prev5": 104.0,
        "ma60": 100.0, "ma144": 98.0, "ma200": 95.0,
        "rsi": 50.0, "rsiD1": 49.0, "rsiSignal": 48.0, "rsiSlope": 1.0,
        "cci": 0.0, "cciD1": 0.0, "cciSignal": 0.0, "cciSlope": 0.0,
        "macd": 0.0, "macdD1": 0.0, "macdSignal": 0.0,
        "macdHist": 0.5, "macdHistD1": 0.4, "macdHistD2": 0.3, "macdSlope": 0.0,
        "plusDI": 20.0, "minusDI": 18.0, "adx": 20.0, "adxD1": 19.0, "adxD2": 18.0, "adxSlope": 0.0,
        "pctB": 40.0, "pctBLow": 30.0, "pctBPeak": 50.0, "pctBPeakD1": 49.0,
        "bbWidth": 10.0, "bbWidthD1": 10.0, "bbWidthAvg60": 30.0,
        "volRatio": 1.0, "prevVolRatio": 1.0, "volRatio20": 1.0,
        "lrSlope": 0.0, "lrTrendline": 90.0,
    }
    base.update(overrides)
    return base


STOCK = {"ticker": "TEST", "name": "테스트", "market": "US"}
RECOVERY_MARKET = {
    "premiumPercent": -1.0,
    "buyBlockMax": 18,
    "regimeLabel": "회복장",
    "isRecoveryMarket": True,
    "warnTriggered": False,
}


def patch_sources(monkeypatch, row):
    monkeypatch.setattr(pipeline, "calc_technical_row", lambda ticker: row)
    monkeypatch.setattr(pipeline, "fetch_us_extended_price", lambda ticker: None)


def strategy1_hold_row():
    # 전략1 hold: 현재가 < MA200, VIX 완화 임계, RSI/CCI 과매도, LR 상승+터치, QQQ 하락장.
    return make_technical_row(
        close=90.0,
        ma200=100.0,
        rsi=30.0,
        cci=-160.0,
        lrSlope=0.1,
        lrTrendline=91.0,
        low=90.5,
    )


def test_held_strategy1_keeps_buy_when_hold_condition_met(monkeypatch):
    row = strategy1_hold_row()
    patch_sources(monkeypatch, row)
    market = {**RECOVERY_MARKET, "premiumPercent": -4.0, "isRecoveryMarket": False, "regimeLabel": "하락장"}

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=market, vix=28.0, holding_strategy_type="1", season_open=True
    )

    assert result["opinion"] == "매수"
    assert result["entrySignalCodes"] == "1"


def test_held_strategy1_turns_watch_when_hold_condition_lost(monkeypatch):
    row = strategy1_hold_row()
    row["close"] = 110.0  # MA200 위로 회복 → 전략1 hold 이탈
    patch_sources(monkeypatch, row)
    market = {**RECOVERY_MARKET, "premiumPercent": -4.0, "isRecoveryMarket": False, "regimeLabel": "하락장"}

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=market, vix=28.0, holding_strategy_type="1", season_open=True
    )

    assert result["opinion"] == "관망"


def test_held_strategy2_keeps_buy_when_season_and_recovery(monkeypatch):
    # 전략2 hold: 시즌 열림 + 회복장 + QQQ ≤ 차단선 (MA 터치는 hold에 불필요).
    row = make_technical_row(close=110.0, ma200=95.0, ma20=105.0)
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=RECOVERY_MARKET, vix=15.0, holding_strategy_type="2", season_open=True
    )

    assert result["opinion"] == "매수"
    assert result["entrySignalCodes"] == "2"


def test_held_strategy2_turns_watch_when_season_closed(monkeypatch):
    row = make_technical_row(close=110.0, ma200=95.0, ma20=105.0)
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=RECOVERY_MARKET, vix=15.0, holding_strategy_type="2", season_open=False
    )

    assert result["opinion"] == "관망"


def test_non_holding_stock_uses_entry_signal_only(monkeypatch):
    # 미보유: 전략2 진입 조건 일부만 충족(시즌 닫힘) → 관망.
    row = make_technical_row(close=105.0, low=104.0, ma20=105.0, ma200=90.0)
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=RECOVERY_MARKET, vix=15.0, holding_strategy_type=None, season_open=False
    )

    assert result["opinion"] == "관망"


def test_non_holding_strategy2_entry_when_season_open(monkeypatch):
    row = make_technical_row(close=105.0, low=104.0, ma20=105.0, ma60=100.0, ma144=98.0, ma200=90.0)
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=RECOVERY_MARKET, vix=15.0, holding_strategy_type=None, season_open=True
    )

    assert result["opinion"] == "매수"
    assert result["entrySignalCodes"] == "2"
    assert result["entryStrategy"] == "2. 상승 추세 이평선 눌림목"


def test_open_holding_strategies_reads_primary_code(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "read_cache",
        lambda name: {
            "rows": [
                {"ticker": "278470", "strategy": "2. 상승 추세 이평선 눌림목", "status": "보유 중"},
                {"ticker": "AAPL", "strategy": "1. 시장 공포 저점 진입", "status": "손절"},
            ]
        }
        if name == "trade-logs"
        else {},
    )

    holdings = pipeline.open_holding_strategies()

    assert holdings == {"278470": "2"}
