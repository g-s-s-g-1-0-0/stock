"""보유 종목 의견 산정 회귀 테스트.

핵심: 보유 중('보유 중' 매매로그가 있는) 종목은, 신규 진입 신호가 그 턴에 다시
발화하지 않더라도 보유용(hold) 조건이 유지되는 한 의견이 '매수'로 유지돼야 한다.
hold 조건을 실제로 이탈했을 때만 '관망'으로 내려간다(GAS updateInvestmentOpinion.gs와 동일).
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
# QQQ 바닥/정상 필터 통과를 위한 시장 상태 (E/F는 nasdaq_bottom 필요).
MARKET_STATE = {"premiumPercent": 5.0, "buyBlockMax": 18, "regimeLabel": "정상", "isRecoveryMarket": False}


def patch_sources(monkeypatch, row):
    monkeypatch.setattr(pipeline, "calc_technical_row", lambda ticker: row)
    monkeypatch.setattr(pipeline, "fetch_us_extended_price", lambda ticker: None)


def e_strategy_hold_row():
    # E 보유 조건: 현재가>MA200, BB폭/60평균 < 0.5(스퀴즈), 저가%B <= 50.
    # 단, 신규 E '진입'은 A~D 우선순위 배제까지 충족해야 하므로 hold만 통과하도록 구성.
    return make_technical_row(
        close=110.0, ma200=95.0,
        bbWidth=10.0, bbWidthAvg60=30.0,  # 10/30 = 0.33 < 0.5 → 스퀴즈
        pctBLow=30.0,                      # <= 50
        macdHist=-0.1, macdHistD1=-0.2,    # 신규 A/C/D 진입 방지(MACD<=0 등)
        pctB=40.0,
    )


def test_held_e_stock_keeps_buy_when_hold_condition_met(monkeypatch):
    row = e_strategy_hold_row()
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=MARKET_STATE, vix=15.0, holding_strategy_type="2"
    )

    assert result["opinion"] == "매수"
    # 보유 매수의 경우 진입 전략 표시는 보유 전략 코드를 사용한다.
    assert result["entrySignalCodes"] == "E"


def test_held_e_stock_turns_watch_when_hold_condition_lost(monkeypatch):
    # 스퀴즈 해소(BB폭/60평균 >= 0.5) → E hold 조건 이탈 → 관망.
    row = e_strategy_hold_row()
    row["bbWidth"] = 20.0  # 20/30 = 0.66 >= 0.5
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=MARKET_STATE, vix=15.0, holding_strategy_type="2"
    )

    assert result["opinion"] == "관망"


def a_strategy_hold_not_entry_row():
    # A 보유(hold) 조건: 현재가>MA200 + 필터 + MACD Hist>0.
    # A '신규 진입'은 추가로 MACD 골든크로스(전일<=0 & 당일>0), 종가%B>80, RSI>70 필요.
    # 전일 MACD가 이미 양수면 골든크로스가 아니므로 신규 진입은 실패, hold만 통과한다.
    return make_technical_row(
        close=110.0, ma200=95.0,
        macdHist=0.5, macdHistD1=0.4,  # 이미 양수 → 신규 골든크로스 아님(hold는 MACD>0만 필요)
        pctB=85.0, rsi=72.0,           # 진입용 보조 조건은 충족시키되 골든크로스만 불성립
        bbWidth=20.0, bbWidthAvg60=30.0,  # E 스퀴즈 회피
        pctBLow=60.0,                      # E/F 저가%B 회피
    )


def test_held_a_stock_keeps_buy_without_fresh_golden_cross(monkeypatch):
    # 보유 A 종목: 신규 골든크로스가 다시 안 떠도 hold 조건 유지 시 '매수' 유지.
    row = a_strategy_hold_not_entry_row()
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=MARKET_STATE, vix=15.0, holding_strategy_type="1"
    )

    assert result["opinion"] == "매수"
    assert result["entrySignalCodes"] == "A"


def test_non_holding_stock_uses_entry_signal_only(monkeypatch):
    # 동일 행이라도 미보유 종목은 신규 진입(골든크로스) 미발화 시 관망(기존 동작 유지).
    row = a_strategy_hold_not_entry_row()
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=MARKET_STATE, vix=15.0, holding_strategy_type=None
    )

    assert result["opinion"] == "관망"


def test_non_holding_h_stock_uses_20ma_support_signal(monkeypatch):
    row = make_technical_row(
        close=103.0,
        open=102.0,
        low=99.8,
        ma20=100.0,
        ma20Prev5=99.5,
        ma200=90.0,
        macdHist=-0.1,
        macdHistD1=-0.2,
        pctB=45.0,
        pctBLow=30.0,
        bbWidth=20.0,
        bbWidthAvg60=30.0,
    )
    patch_sources(monkeypatch, row)

    result = pipeline.latest_technical_row(
        STOCK, qqq_market_state=MARKET_STATE, vix=15.0, holding_strategy_type=None
    )

    assert result["opinion"] == "매수"
    assert result["entrySignalCodes"] == "H"
    assert result["entryStrategy"] == "2. 이평선 눌림"


def test_open_holding_strategies_reads_primary_code(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "read_cache",
        lambda name: {
            "rows": [
                {"ticker": "278470", "strategy": "2. 이평선 눌림", "status": "보유 중"},
                {"ticker": "AAPL", "strategy": "1. 공황 저점", "status": "손절"},
            ]
        }
        if name == "trade-logs"
        else {},
    )

    holdings = pipeline.open_holding_strategies()

    assert holdings == {"278470": "E"}
